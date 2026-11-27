"""Write a table to Parquet after it passes its schema.

`write_table` validates the frame against the schema of the table, checks the key, and
stores the source ids, the change notes, the build date and the commit in the file.
A shared table takes its schema and key from `core.tables.schemas`; a project table passes
its own schema and key, under a name that no shared table has.
`read_metadata` reads them back without loading the rows.
"""

import datetime
import json
import logging
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.errors
import pandera.pandas as pandera_pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.tables.schemas import KEYS, SCHEMAS, frame_check_columns

logger = logging.getLogger(__name__)

METADATA_KEY = b"public_money_fr"

_COLUMN_PRESENCE_CHECKS = ("column_in_schema", "column_in_dataframe")

_ARROW_TYPES: dict[str, pa.DataType] = {
    "int8": pa.int8(),
    "Int8": pa.int8(),
    "int16": pa.int16(),
    "float64": pa.float64(),
    "bool": pa.bool_(),
    "date": pa.date32(),
}


class TableError(ValueError):
    """A frame breaks the contract of its table; the message names the table and column."""


@dataclass(frozen=True)
class TableMetadata:
    """What a written table says about itself.

    The fields are the table name, the manifest ids of the source files (sorted, without
    duplicates), the build date (ISO 8601), the git commit of the code that built it, and
    the change notes.
    """

    table: str
    source_ids: tuple[str, ...]
    build_date: str
    commit: str
    #: What the code that built the table changed in the data of a source, by source id.
    changes: Mapping[str, str] = field(default_factory=dict)


def current_commit() -> str:
    """Return the full SHA of the checked-out commit.

    Returns:
        The commit SHA.

    Raises:
        RuntimeError: If git cannot give the commit.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"cannot read the git commit: {error}") from error
    return result.stdout.strip()


def _describe_failure(row: Any) -> str:
    """Describe one failure case, naming the column that breaks the schema."""
    if row.check in _COLUMN_PRESENCE_CHECKS:
        kind = "missing" if row.check == "column_in_dataframe" else "unexpected"
        return f"column {row.failure_case!r}: {kind} column ({row.check})"
    return f"column {row.column!r}: {row.check} (failure case: {row.failure_case!r})"


def _describe_frame_rule(check: str, cases: pd.DataFrame, rule_columns: dict[str, str]) -> str:
    """Describe a failed rule of the whole frame: its columns and each bad row once."""
    columns = rule_columns.get(check, "")
    rows = sorted(set(cases["index"].dropna()))
    where = f"rows {', '.join(str(row) for row in rows)}" if rows else "the frame as a whole"
    return f"rule {check} on columns ({columns}) fails for {where}"


def _describe_failures(
    failure_cases: pd.DataFrame, schema: pandera_pd.DataFrameSchema
) -> list[str]:
    """Describe all failure cases: a line for each cell, a line for each frame-level rule."""
    is_frame_rule = (failure_cases["schema_context"] == "DataFrameSchema") & ~failure_cases[
        "check"
    ].isin(_COLUMN_PRESENCE_CHECKS)
    rule_columns = {
        check.name: ", ".join(columns)
        for check in schema.checks
        if check.name and (columns := frame_check_columns(check)) is not None
    }
    lines = [_describe_failure(row) for row in failure_cases[~is_frame_rule].itertuples()]
    for check, cases in failure_cases[is_frame_rule].groupby("check", sort=False):
        lines.append(_describe_frame_rule(str(check), cases, rule_columns))
    return lines


def _resolve(
    table: str,
    schema: pandera_pd.DataFrameSchema | None,
    key: tuple[str, ...] | None,
) -> tuple[pandera_pd.DataFrameSchema, tuple[str, ...] | None]:
    """Return the schema and key of a table: the shared ones, or the ones the caller gives."""
    if schema is None:
        if key is not None:
            raise TableError(f"table {table!r}: a key needs a schema; a shared table has its own")
        if table not in SCHEMAS:
            raise TableError(
                f"unknown table {table!r}; known tables: {', '.join(sorted(SCHEMAS))}; "
                "a project table passes its schema and key"
            )
        return SCHEMAS[table], KEYS.get(table)
    if table in SCHEMAS:
        raise TableError(f"table {table!r} is a shared table; a project table needs another name")
    if key is None:
        raise TableError(f"table {table!r}: a project table needs a key")
    unknown = [name for name in key if name not in schema.columns]
    if unknown:
        raise TableError(f"table {table!r}: key columns not in the schema: {', '.join(unknown)}")
    return schema, key


def validate_table(
    frame: pd.DataFrame,
    table: str,
    *,
    schema: pandera_pd.DataFrameSchema | None = None,
    key: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Check a frame against the schema and the key of its table.

    Args:
        frame: The rows to check.
        table: Name of the table. A shared table keeps its schema and key; a project table
            has a name that no shared table has.
        schema: Schema of a project table; omit it for a shared table.
        key: Columns of the key of a project table; required with `schema`.

    Returns:
        The frame, unchanged.

    Raises:
        TableError: If the table is unknown, a project table takes the name of a shared
            table or has no key, a column breaks the schema, or the key has duplicates. A
            null counts as one key value.
    """
    schema, key = _resolve(table, schema, key)
    try:
        schema.validate(frame, lazy=True)
    except pandera.errors.SchemaErrors as error:
        lines = _describe_failures(error.failure_cases, schema)
        raise TableError(f"table {table!r} breaks its schema:\n" + "\n".join(lines)) from error
    if key is not None:
        duplicated = frame.duplicated(subset=list(key), keep=False)
        if duplicated.any():
            raise TableError(
                f"table {table!r} has {int(duplicated.sum())} rows with a repeated key "
                f"({', '.join(key)}); a null counts as one value"
            )
    return frame


def _arrow_type(table: str, column: str, dtype: object) -> pa.DataType:
    name = str(dtype)
    if name.startswith("string"):
        return pa.string()
    if name not in _ARROW_TYPES:
        raise TableError(
            f"table {table!r}: column {column!r} has type {name!r}, which the writer cannot "
            f"convert; supported: string, {', '.join(_ARROW_TYPES)}"
        )
    return _ARROW_TYPES[name]


def _to_arrow(frame: pd.DataFrame, table: str, schema: pandera_pd.DataFrameSchema) -> pa.Table:
    """Convert a valid frame to Arrow with the types of the schema.

    An all-null nullable string column has no type of its own in pandas; the schema gives
    it, so the file reads back with the same types that the schema checks.
    """
    wanted_types = {name: _arrow_type(table, name, c.dtype) for name, c in schema.columns.items()}
    arrow = pa.Table.from_pandas(frame, preserve_index=False)
    for name, wanted in wanted_types.items():
        index = arrow.schema.get_field_index(name)
        if arrow.schema.field(index).type != wanted:
            arrow = arrow.set_column(
                index, pa.field(name, wanted), arrow.column(index).cast(wanted)
            )
    return arrow


def write_table(
    frame: pd.DataFrame,
    table: str,
    path: Path,
    source_ids: list[str],
    *,
    changes: Mapping[str, str] | None = None,
    build_date: datetime.date | None = None,
    commit: str | None = None,
    schema: pandera_pd.DataFrameSchema | None = None,
    key: tuple[str, ...] | None = None,
) -> TableMetadata:
    """Validate a frame and write it as a Parquet file with metadata.

    Nothing is written when the frame breaks its schema or its key.

    Args:
        frame: The rows to write.
        table: Name of the table; a project table has a name that no shared table has.
        path: Parquet file to write.
        source_ids: Manifest ids of the source files that the rows come from.
        changes: What the code that builds the table changes in the data of a source, by
            source id: the series or rows it keeps, how it reshapes and converts them. The
            dataset card prints these notes; it needs one for each input under CC BY 4.0,
            whose licence asks that changes be indicated.
        build_date: Date of the build; today when omitted.
        commit: Git commit of the code; the checked-out commit when omitted.
        schema: Schema of a project table; omit it for a shared table.
        key: Columns of the key of a project table; required with `schema`.

    Returns:
        The metadata stored in the file.

    Raises:
        TableError: If the frame breaks the contract of the table, the project table takes
            the name of a shared table or has no key, a column has a type that the writer
            cannot convert to Arrow, or a change note is empty or names a source that is
            not in `source_ids`.
        RuntimeError: If `commit` is omitted and git cannot give it.
    """
    validate_table(frame, table, schema=schema, key=key)
    notes = dict(sorted((changes or {}).items()))
    stray = sorted(set(notes) - set(source_ids))
    if stray:
        raise TableError(
            f"table {table!r}: change notes for sources it does not use: {', '.join(stray)}"
        )
    empty = [source_id for source_id, note in notes.items() if not note.strip()]
    if empty:
        raise TableError(f"table {table!r}: empty change notes for: {', '.join(empty)}")
    metadata = TableMetadata(
        table=table,
        source_ids=tuple(sorted(set(source_ids))),
        build_date=(build_date or datetime.date.today()).isoformat(),
        commit=commit or current_commit(),
        changes=notes,
    )
    arrow = _to_arrow(frame, table, _resolve(table, schema, key)[0])
    stored = {
        METADATA_KEY: json.dumps(
            {
                "table": metadata.table,
                "source_ids": list(metadata.source_ids),
                "build_date": metadata.build_date,
                "commit": metadata.commit,
                "changes": notes,
            }
        ).encode()
    }
    arrow = arrow.replace_schema_metadata({**(arrow.schema.metadata or {}), **stored})
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(arrow, path)
    logger.info("wrote %d rows of %s to %s", len(frame), table, path)
    return metadata


def read_metadata(path: Path) -> TableMetadata:
    """Read the metadata of a table written by `write_table`.

    Args:
        path: Parquet file to read.

    Returns:
        The metadata stored in the file.

    Raises:
        TableError: If the file has no metadata of this project.
    """
    raw = (pq.read_schema(path).metadata or {}).get(METADATA_KEY)
    if raw is None:
        raise TableError(f"{path} has no table metadata; it was not written by write_table")
    data = json.loads(raw)
    return TableMetadata(
        table=data["table"],
        source_ids=tuple(data["source_ids"]),
        build_date=data["build_date"],
        commit=data["commit"],
        changes=data.get("changes", {}),
    )
