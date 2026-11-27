"""Builders of tables, and the `build` and `validate` commands that run them.

A builder makes one table from the local files of the sources it reads. A project makes its
builders known through the entry point group `public_money_fr.builders` of its package
metadata: each entry point loads a callable that returns a sequence of `Builder`, so `core`
never names a project. The shared tables register the same way.

`build_tables` writes each table to `<build dir>/<dataset>/<table>.parquet`. `validate_build`
reads those files back and checks them before a publish.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol

import pandas as pd
import pandera.pandas as pandera_pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.fetch.lockfile import Lockfile
from core.publish.hf_check import DATASET_NAMES
from core.sources.manifest import Source
from core.tables.manual import (
    DEFAULT_ROWS_DIR,
    ManualRowsError,
    RowParser,
    check_header,
    rows_path,
)
from core.tables.writer import TableError, read_metadata, validate_table, write_table

BUILDER_GROUP = "public_money_fr.builders"
DEFAULT_BUILD_DIR = Path("data/build")


class BuildError(ValueError):
    """A build cannot run: an unknown name, a source that is not fetched, or a failed builder."""


@dataclass(frozen=True)
class BuiltTable:
    """What a builder returns: the rows and what it changed in the data of each source."""

    frame: pd.DataFrame
    #: Change notes by source id; see `write_table`.
    changes: Mapping[str, str]


class BuildFunction(Protocol):
    """A function that makes a table from the local files of its sources."""

    def __call__(self, files: Mapping[str, list[Path]], /) -> BuiltTable: ...


@dataclass(frozen=True)
class Builder:
    """One table, the dataset it goes to, the sources it reads and the function that makes it."""

    table: str
    #: One of `DATASET_NAMES`.
    dataset: str
    source_ids: tuple[str, ...]
    #: Gets the local files of each source (by source id, in the order of the manifest).
    build: BuildFunction
    #: Schema and key of a project table; both None for a shared table.
    schema: pandera_pd.DataFrameSchema | None = None
    key: tuple[str, ...] | None = None
    #: Parser of each manual source that the table reads, by source id; `extract` runs it.
    manual_parsers: Mapping[str, RowParser] = field(default_factory=dict)


def load_builders() -> list[Builder]:
    """Load the builders that installed packages declare.

    Returns:
        The builders of every entry point of the group `public_money_fr.builders`.
    """
    builders: list[Builder] = []
    for entry in entry_points(group=BUILDER_GROUP):
        builders.extend(entry.load()())
    return builders


def check_builders(builders: Sequence[Builder]) -> None:
    """Refuse builders that cannot work together.

    Args:
        builders: The registered builders.

    Raises:
        BuildError: If a dataset name is unknown or two builders make the same table of a
            dataset.
    """
    seen: set[tuple[str, str]] = set()
    for builder in builders:
        if builder.dataset not in DATASET_NAMES:
            raise BuildError(
                f"table {builder.table!r}: unknown dataset {builder.dataset!r}; "
                f"known: {', '.join(DATASET_NAMES)}"
            )
        identity = (builder.dataset, builder.table)
        if identity in seen:
            raise BuildError(f"two builders make table {builder.table!r} of {builder.dataset}")
        seen.add(identity)


def select_builders(builders: Sequence[Builder], names: Sequence[str]) -> list[Builder]:
    """Pick the builders of the named tables or datasets.

    Args:
        builders: The registered builders.
        names: Table names or dataset names; all builders if empty.

    Returns:
        The selected builders.

    Raises:
        BuildError: If a name is neither a dataset nor a registered table.
    """
    if not names:
        return list(builders)
    known = set(DATASET_NAMES) | {builder.table for builder in builders}
    unknown = [name for name in names if name not in known]
    if unknown:
        raise BuildError(
            f"unknown table or dataset: {', '.join(unknown)}; "
            f"datasets: {', '.join(DATASET_NAMES)}; "
            f"tables: {', '.join(sorted({b.table for b in builders})) or 'none registered'}"
        )
    return [b for b in builders if b.table in names or b.dataset in names]


def table_path(build_dir: Path, dataset: str, table: str) -> Path:
    """Return the file of a table in the build folder."""
    return build_dir / dataset / f"{table}.parquet"


def _raw_files(source_id: str, lock: Lockfile, raw_dir: Path) -> list[Path] | None:
    """Return the raw files of a source, or None if the cache lacks the source or a file."""
    entries = lock.entries.get(source_id)
    if not entries:
        return None
    paths = [raw_dir / source_id / entry.path for entry in entries.values()]
    return paths if all(path.is_file() for path in paths) else None


def build_tables(
    builders: Sequence[Builder],
    lock: Lockfile,
    raw_dir: Path,
    build_dir: Path,
    manifest: Mapping[str, Source],
    rows_dir: Path = DEFAULT_ROWS_DIR,
) -> list[Path]:
    """Run the builders and write their tables.

    All sources are checked before the first builder runs. For a source of kind `manual`, the
    builder gets the committed rows file of its table in place of the raw file, whether or
    not the raw file is on the machine, so that a local build and a runner build agree; it
    reads the file with `core.tables.manual.read_rows`. A table is written to a
    temporary file and moved into place, so a failed run leaves no partial file.

    Args:
        builders: The builders to run.
        lock: The lockfile that lists the files of the raw cache.
        raw_dir: The raw cache.
        build_dir: The build folder; one sub-folder for each dataset.
        manifest: The sources by id.
        rows_dir: The folder of the committed rows of manual sources.

    Returns:
        The files written.

    Raises:
        BuildError: If a source has no file in the raw cache (the message names it and says
            to run `fetch`), the committed rows of a manual source are missing or come from
            another file than the one the manifest pins (the message names the source and
            both checksums), or a builder fails (the message names the table).
    """
    inputs: dict[tuple[str, str], dict[str, list[Path]]] = {}
    for builder in builders:
        files: dict[str, list[Path]] = {}
        for source_id in builder.source_ids:
            source = manifest.get(source_id)
            if source is not None and source.access["kind"] == "manual":
                committed = rows_path(rows_dir, source_id, builder.table)
                try:
                    check_header(committed, source, builder.table)
                except ManualRowsError as error:
                    raise BuildError(f"table {builder.table!r}: {error}") from error
                files[source_id] = [committed]
                continue
            found = _raw_files(source_id, lock, raw_dir)
            if found is None:
                raise BuildError(
                    f"table {builder.table!r}: source {source_id} has no file in the raw cache "
                    f"{raw_dir}; run fetch {source_id}"
                )
            files[source_id] = found
        inputs[(builder.dataset, builder.table)] = files
    written: list[Path] = []
    for builder in builders:
        path = table_path(build_dir, builder.dataset, builder.table)
        temporary = path.with_name(path.name + ".part")
        try:
            built = builder.build(inputs[(builder.dataset, builder.table)])
            write_table(
                built.frame,
                builder.table,
                temporary,
                list(builder.source_ids),
                changes=built.changes,
                schema=builder.schema,
                key=builder.key,
            )
            temporary.replace(path)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            raise BuildError(f"table {builder.table!r}: {error}") from error
        written.append(path)
    return written


def _check_file(
    path: Path,
    registered: Mapping[str, Builder],
    manifest: Mapping[str, Source],
) -> list[str]:
    """Return the problems of one table file; each one names the file."""
    try:
        metadata = read_metadata(path)
    except TableError as error:
        return [str(error)]
    problems: list[str] = []
    builder = registered.get(metadata.table)
    if builder is None:
        problems.append(
            f"{path}: table {metadata.table!r} has no registered builder in this dataset; "
            "delete the file"
        )
    else:
        try:
            frame = pq.read_table(path).to_pandas()
            validate_table(frame, metadata.table, schema=builder.schema, key=builder.key)
        except (TableError, pa.ArrowException, OSError) as error:
            problems.append(f"{path}: {error}")
    for source_id in metadata.source_ids:
        source = manifest.get(source_id)
        if source is None:
            problems.append(f"{path}: source {source_id} is not in the manifest")
        elif source.last_update is None:
            problems.append(f"{path}: source {source_id} has no last_update in the manifest")
    return problems


def validate_build(
    builders: Sequence[Builder],
    datasets: Sequence[str],
    manifest: Mapping[str, Source],
    build_dir: Path,
) -> list[str]:
    """Read back the table files of the build folders and check them.

    Args:
        builders: All registered builders.
        datasets: The datasets to check; all four if empty.
        manifest: The sources by id.
        build_dir: The build folder.

    Returns:
        One line for each problem, each naming the file; empty if all is well.

    Raises:
        BuildError: If a dataset name is unknown.
    """
    unknown = [name for name in datasets if name not in DATASET_NAMES]
    if unknown:
        raise BuildError(
            f"unknown dataset: {', '.join(unknown)}; known: {', '.join(DATASET_NAMES)}"
        )
    problems: list[str] = []
    for dataset in datasets or DATASET_NAMES:
        registered = {b.table: b for b in builders if b.dataset == dataset}
        for path in sorted((build_dir / dataset).glob("*.parquet")):
            problems.extend(_check_file(path, registered, manifest))
        problems.extend(
            f"{table_path(build_dir, dataset, table)}: missing; build table {table!r}"
            for table in registered
            if not table_path(build_dir, dataset, table).is_file()
        )
    return problems
