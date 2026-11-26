"""Write a shared table to Parquet after it passes its schema.

`write_table` validates the frame against the schema of the table, checks the key, and
stores the source ids, the build date and the commit in the file. `read_metadata` reads
them back without loading the rows.
"""

import datetime
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.errors
import pyarrow as pa
import pyarrow.parquet as pq

from core.tables.schemas import FRAME_CHECK_COLUMNS, KEYS, SCHEMAS

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
    duplicates), the build date (ISO 8601) and the git commit of the code that built it.
    """

    table: str
    source_ids: tuple[str, ...]
    build_date: str
    commit: str


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


def _describe_frame_rule(check: str, cases: pd.DataFrame) -> str:
    """Describe a failed rule of the whole frame: its columns and each bad row once."""
    columns = ", ".join(FRAME_CHECK_COLUMNS.get(check, ()))
    rows = sorted(set(cases["index"].dropna()))
    where = f"rows {', '.join(str(row) for row in rows)}" if rows else "the frame as a whole"
    return f"rule {check} on columns ({columns}) fails for {where}"


def _describe_failures(failure_cases: pd.DataFrame) -> list[str]:
    """Describe all failure cases: a line for each cell, a line for each frame-level rule."""
    is_frame_rule = (failure_cases["schema_context"] == "DataFrameSchema") & ~failure_cases[
        "check"
    ].isin(_COLUMN_PRESENCE_CHECKS)
    lines = [_describe_failure(row) for row in failure_cases[~is_frame_rule].itertuples()]
    for check, cases in failure_cases[is_frame_rule].groupby("check", sort=False):
        lines.append(_describe_frame_rule(str(check), cases))
    return lines


def validate_table(frame: pd.DataFrame, table: str) -> pd.DataFrame:
    """Check a frame against the schema and the key of its table.

    Args:
        frame: The rows to check.
        table: Name of the shared table.

    Returns:
        The frame, unchanged.

    Raises:
        TableError: If the table is unknown, a column breaks the schema, or the key has
            duplicates. A null counts as one key value.
    """
    if table not in SCHEMAS:
        raise TableError(f"unknown table {table!r}; known tables: {', '.join(sorted(SCHEMAS))}")
    try:
        SCHEMAS[table].validate(frame, lazy=True)
    except pandera.errors.SchemaErrors as error:
        lines = _describe_failures(error.failure_cases)
        raise TableError(f"table {table!r} breaks its schema:\n" + "\n".join(lines)) from error
    key = KEYS.get(table)
    if key is not None:
        duplicated = frame.duplicated(subset=list(key), keep=False)
        if duplicated.any():
            raise TableError(
                f"table {table!r} has {int(duplicated.sum())} rows with a repeated key "
                f"({', '.join(key)}); a null counts as one value"
            )
    return frame


def _arrow_type(dtype: object) -> pa.DataType:
    name = str(dtype)
    return pa.string() if name.startswith("string") else _ARROW_TYPES[name]


def _to_arrow(frame: pd.DataFrame, table: str) -> pa.Table:
    """Convert a valid frame to Arrow with the types of the schema.

    An all-null nullable string column has no type of its own in pandas; the schema gives
    it, so the file reads back with the same types that the schema checks.
    """
    arrow = pa.Table.from_pandas(frame, preserve_index=False)
    for name, column in SCHEMAS[table].columns.items():
        index = arrow.schema.get_field_index(name)
        wanted = _arrow_type(column.dtype)
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
    build_date: datetime.date | None = None,
    commit: str | None = None,
) -> TableMetadata:
    """Validate a frame and write it as a Parquet file with metadata.

    Nothing is written when the frame breaks its schema or its key.

    Args:
        frame: The rows to write.
        table: Name of the shared table.
        path: Parquet file to write.
        source_ids: Manifest ids of the source files that the rows come from.
        build_date: Date of the build; today when omitted.
        commit: Git commit of the code; the checked-out commit when omitted.

    Returns:
        The metadata stored in the file.

    Raises:
        TableError: If the frame breaks the contract of the table.
        RuntimeError: If `commit` is omitted and git cannot give it.
    """
    validate_table(frame, table)
    metadata = TableMetadata(
        table=table,
        source_ids=tuple(sorted(set(source_ids))),
        build_date=(build_date or datetime.date.today()).isoformat(),
        commit=commit or current_commit(),
    )
    arrow = _to_arrow(frame, table)
    stored = {
        METADATA_KEY: json.dumps(
            {
                "table": metadata.table,
                "source_ids": list(metadata.source_ids),
                "build_date": metadata.build_date,
                "commit": metadata.commit,
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
    )
