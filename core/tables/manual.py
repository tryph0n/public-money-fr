"""Committed rows of manual sources (decision D34).

A source of kind `manual` is a file that the owner downloads by hand; the refresh runner has
no copy of it. The project parser of that file runs on the machine of the owner, and
`extract_rows` writes its rows to one JSON Lines file for each source and table, which a pull
request commits. The build reads that file with `read_rows` and never the raw file.

File format: the first line is a header with the source id, the table name and the SHA-256 of
the raw file; each other line is one row, an object whose keys follow the column order of the
table. Dates are ISO strings. The writer is deterministic (same rows, same bytes), and a float
is written with the shortest text that reads back as the same number.
"""

import datetime
import json
import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pandera_pd

from core.fetch import adapters
from core.fetch.fetcher import DEFAULT_MANUAL_DIR
from core.fetch.lockfile import sha256_of
from core.sources.manifest import Source
from core.tables.schemas import SCHEMAS
from core.tables.writer import validate_table

logger = logging.getLogger(__name__)

DEFAULT_ROWS_DIR = Path(__file__).parents[1] / "sources" / "rows"

#: Parser of a manual source: gets its raw files, returns the rows of one table.
RowParser = Callable[[list[Path]], pd.DataFrame]


class ManualRowsError(ValueError):
    """The committed rows of a manual source are missing, stale or do not fit the table."""


def rows_path(rows_dir: Path, source_id: str, table: str) -> Path:
    """Return the committed file of a source and a table."""
    return rows_dir / source_id / f"{table}.jsonl"


def _cell(value: object) -> object:
    """Return the JSON value of a cell."""
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, datetime.date):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def render_rows(frame: pd.DataFrame, source_id: str, table: str, sha256: str) -> str:
    """Return the text of a committed file.

    Args:
        frame: The rows that the parser gives.
        source_id: Id of the manual source.
        table: Name of the table.
        sha256: SHA-256 of the raw file that the rows come from.

    Returns:
        A header line and one line for each row, each ending with a newline.
    """
    lines = [json.dumps({"source_id": source_id, "table": table, "sha256": sha256})]
    columns = list(frame.columns)
    for values in frame.itertuples(index=False, name=None):
        lines.append(json.dumps({c: _cell(v) for c, v in zip(columns, values, strict=True)}))
    return "\n".join(lines) + "\n"


def _read_lines(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the header and the rows of a committed file."""
    try:
        parsed = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, ValueError) as error:
        raise ManualRowsError(f"{path}: cannot be read as committed rows: {error}") from error
    if not parsed or not all(isinstance(item, dict) for item in parsed):
        raise ManualRowsError(f"{path}: a header line and one JSON object per row are expected")
    return parsed[0], parsed[1:]


def check_header(path: Path, source: Source, table: str) -> None:
    """Refuse a committed file that is missing, for another source or table, or stale.

    Args:
        path: The committed file.
        source: The manual source, with the SHA-256 that the manifest pins.
        table: The table that the file is for.

    Raises:
        ManualRowsError: If the file is missing or names another source or table, or records
            a SHA-256 other than the one of the manifest (the message gives both).
    """
    if not path.is_file():
        raise ManualRowsError(
            f"source {source.id}: no committed rows for table {table!r} at {path}; "
            f"run extract {table}"
        )
    header, _ = _read_lines(path)
    if header.get("source_id") != source.id or header.get("table") != table:
        raise ManualRowsError(
            f"{path}: header names source {header.get('source_id')!r} and table "
            f"{header.get('table')!r}, not {source.id!r} and {table!r}"
        )
    expected = source.access["sha256"]
    if header.get("sha256") != expected:
        raise ManualRowsError(
            f"source {source.id}: committed rows {path} come from a file with SHA-256 "
            f"{header.get('sha256')}, the manifest pins {expected}; extract the rows again"
        )


def _convert(value: object, dtype: str, where: str) -> object:
    """Return a cell as the Python value of a column type, or raise."""
    if value is None:
        return None
    if dtype.startswith("string"):
        ok = isinstance(value, str)
    elif dtype in ("int8", "Int8", "int16"):
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif dtype == "float64":
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        value = float(value) if ok else value  # type: ignore[arg-type]
    elif dtype == "bool":
        ok = isinstance(value, bool)
    elif dtype == "date":
        ok = False
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                pass
    else:
        raise ManualRowsError(f"{where}: column type {dtype!r} is not supported")
    if not ok:
        raise ManualRowsError(f"{where}: {value!r} does not convert to the type {dtype}")
    return value


def _column(values: list[object], dtype: str) -> "pd.Series[Any]":
    """Return the cells of a column as a pandas column of the given type."""
    if dtype == "date":
        return pd.Series(values, dtype=object)
    return pd.Series(pd.array(values, dtype=dtype))  # type: ignore[call-overload]


def read_rows(
    path: Path,
    table: str,
    *,
    schema: pandera_pd.DataFrameSchema | None = None,
    key: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Read the committed rows of a source and check them against the schema of the table.

    A builder calls this on the file that `build_tables` gives it; the build has already run
    `check_header`, so this function does not look at the SHA-256.

    Args:
        path: The committed file.
        table: Name of the table.
        schema: Schema of a project table; omit it for a shared table.
        key: Key of a project table.

    Returns:
        The rows, with the column types of the schema.

    Raises:
        ManualRowsError: If the file is for another table, a row lacks a column or has
            another one, or a cell does not convert to its column type.
        TableError: If the rows break the schema or the key.
    """
    columns = (schema or SCHEMAS[table]).columns
    header, rows = _read_lines(path)
    if header.get("table") != table:
        raise ManualRowsError(
            f"{path}: the file is for table {header.get('table')!r}, not {table!r}"
        )
    data: dict[str, list[object]] = {name: [] for name in columns}
    for number, row in enumerate(rows, start=2):
        if set(row) != set(columns):
            raise ManualRowsError(
                f"{path}:{number}: columns {sorted(row)} differ from those of table {table!r}"
            )
        for name, column in columns.items():
            where = f"{path}:{number}: column {name!r}"
            data[name].append(_convert(row[name], str(column.dtype), where))
    frame = pd.DataFrame(
        {name: _column(values, str(columns[name].dtype)) for name, values in data.items()}
    )
    return validate_table(frame, table, schema=schema, key=key)


def raw_files(source: Source, manual_dir: Path) -> list[Path] | None:
    """Find the raw files of a manual source in the manual folder.

    Args:
        source: The manual source.
        manual_dir: The folder where the owner puts the raw files.

    Returns:
        The files, or None if one is not in the folder.

    Raises:
        ManualRowsError: If a file has a SHA-256 other than the one of the manifest.
    """
    paths: list[Path] = []
    for name in adapters.file_keys(source):
        found = sorted(manual_dir.rglob(name)) if manual_dir.is_dir() else []
        if not found:
            return None
        digest = sha256_of(found[0].read_bytes())
        if digest != source.access["sha256"]:
            raise ManualRowsError(
                f"source {source.id}: {found[0]} has SHA-256 {digest}, "
                f"the manifest pins {source.access['sha256']}"
            )
        paths.append(found[0])
    return paths


def _parse(
    parse: RowParser,
    table: str,
    files: list[Path],
    schema: pandera_pd.DataFrameSchema | None,
    key: tuple[str, ...] | None,
) -> pd.DataFrame:
    """Run the parser and check its rows against the schema of the table."""
    return validate_table(parse(files), table, schema=schema, key=key)


def extract_rows(
    parse: RowParser,
    source: Source,
    table: str,
    rows_dir: Path,
    manual_dir: Path = DEFAULT_MANUAL_DIR,
    *,
    schema: pandera_pd.DataFrameSchema | None = None,
    key: tuple[str, ...] | None = None,
) -> Path:
    """Run the parser on the raw file and write the committed file.

    Args:
        parse: The project parser of the source for this table.
        source: The manual source.
        table: Name of the table.
        rows_dir: The folder of the committed files.
        manual_dir: The folder where the owner puts the raw files.
        schema: Schema of a project table; omit it for a shared table.
        key: Key of a project table.

    Returns:
        The committed file.

    Raises:
        ManualRowsError: If the raw file is not in the manual folder or has another SHA-256.
        TableError: If the rows break the schema or the key.
    """
    files = raw_files(source, manual_dir)
    if files is None:
        raise ManualRowsError(
            f"source {source.id}: the raw file is not in {manual_dir}; put it there "
            f"(download page: {source.access['page_url']})"
        )
    frame = _parse(parse, table, files, schema, key)
    path = rows_path(rows_dir, source.id, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_rows(frame, source.id, table, source.access["sha256"]), encoding="utf-8")
    logger.info("%s: wrote %d rows to %s", source.id, len(frame), path)
    return path


def compare_rows(
    parse: RowParser,
    source: Source,
    table: str,
    rows_dir: Path,
    manual_dir: Path = DEFAULT_MANUAL_DIR,
    *,
    schema: pandera_pd.DataFrameSchema | None = None,
    key: tuple[str, ...] | None = None,
) -> list[str] | None:
    """Compare the parser output with the committed file.

    Args:
        parse: The project parser of the source for this table.
        source: The manual source.
        table: Name of the table.
        rows_dir: The folder of the committed files.
        manual_dir: The folder where the owner puts the raw files.
        schema: Schema of a project table; omit it for a shared table.
        key: Key of a project table.

    Returns:
        None if the raw file is not in the manual folder (nothing to compare); else one line
        for each difference, naming the row and the column; empty if the rows are equal.
    """
    files = raw_files(source, manual_dir)
    if files is None:
        return None
    path = rows_path(rows_dir, source.id, table)
    check_header(path, source, table)
    committed = read_rows(path, table, schema=schema, key=key)
    parsed = _parse(parse, table, files, schema, key)
    lines: list[str] = []
    if len(committed) != len(parsed):
        lines.append(f"committed file has {len(committed)} rows, parser gives {len(parsed)}")
    for number in range(min(len(committed), len(parsed))):
        old, new = committed.iloc[number], parsed.iloc[number]
        for column in committed.columns:
            if not (pd.isna(old[column]) and pd.isna(new[column])) and old[column] != new[column]:
                lines.append(
                    f"row {number + 1}, column {column!r}: committed {old[column]!r}, "
                    f"parser {new[column]!r}"
                )
    return lines
