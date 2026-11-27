import dataclasses
from collections.abc import Mapping
from pathlib import Path

import pandas as pd
import pytest

from core.fetch.adapters import manual_name
from core.fetch.lockfile import Lockfile, sha256_of
from core.sources.manifest import MANIFEST_DIR, Source, load_manifest
from core.tables.build import Builder, BuildError, BuiltTable, build_tables, load_builders
from core.tables.manual import (
    DEFAULT_ROWS_DIR,
    ManualRowsError,
    RowParser,
    compare_rows,
    extract_rows,
    read_rows,
    rows_path,
)
from core.tables.writer import TableError
from tests.test_project_tables import KEY, mart_schema

REAL = load_manifest(MANIFEST_DIR)["stability-programme-france-2016"]
TABLE = "mart_example"
RAW_TEXT = b"2016;07;1;1234.56\n2016;08;0;0.30000000000000004\n"


def toy_parser(files: list[Path]) -> pd.DataFrame:
    rows = [line.split(";") for line in files[0].read_text(encoding="utf-8").splitlines()]
    return pd.DataFrame(
        {
            "year": pd.array([int(r[0]) for r in rows], dtype="int16"),
            "code": pd.array([r[1] for r in rows], dtype="string"),
            "flag": [r[2] == "1" for r in rows],
            "amount": [float(r[3]) for r in rows],
            "source_id": pd.array([REAL.id] * len(rows), dtype="string"),
        }
    )


@pytest.fixture
def manual_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "manual"
    folder.mkdir()
    (folder / manual_name(REAL)).write_bytes(RAW_TEXT)
    return folder


@pytest.fixture
def source() -> Source:
    return dataclasses.replace(REAL, access={**REAL.access, "sha256": sha256_of(RAW_TEXT)})


def extract(source: Source, manual_dir: Path, rows_dir: Path) -> Path:
    return extract_rows(
        toy_parser, source, TABLE, rows_dir, manual_dir, schema=mart_schema(), key=KEY
    )


def test_two_extractions_give_the_same_bytes(
    source: Source, manual_dir: Path, tmp_path: Path
) -> None:
    first = extract(source, manual_dir, tmp_path / "rows").read_bytes()
    second = extract(source, manual_dir, tmp_path / "rows").read_bytes()
    assert first == second
    assert first.splitlines()[0].decode() == (
        f'{{"source_id": "{source.id}", "table": "{TABLE}", "sha256": "{sha256_of(RAW_TEXT)}"}}'
    )


def test_code_with_a_leading_zero_and_amounts_read_back_as_the_parser_gave_them(
    source: Source, manual_dir: Path, tmp_path: Path
) -> None:
    path = extract(source, manual_dir, tmp_path / "rows")
    read = read_rows(path, TABLE, schema=mart_schema(), key=KEY)
    expected = toy_parser([manual_dir / manual_name(source)])
    pd.testing.assert_frame_equal(read, expected)
    assert read["code"].tolist() == ["07", "08"]
    assert read["amount"].tolist() == [1234.56, 0.1 + 0.2]
    assert [str(dtype) for dtype in read.dtypes] == [str(dtype) for dtype in expected.dtypes]


def test_a_cell_that_does_not_convert_to_its_column_type_fails(
    source: Source, manual_dir: Path, tmp_path: Path
) -> None:
    path = extract(source, manual_dir, tmp_path / "rows")
    path.write_text(path.read_text().replace('"year": 2016', '"year": "2016"', 1))
    with pytest.raises(ManualRowsError, match=r":2: column 'year'.*'2016'"):
        read_rows(path, TABLE, schema=mart_schema(), key=KEY)


def mart_builder(source: Source, seen: list[Path]) -> Builder:
    def build(files: Mapping[str, list[Path]]) -> BuiltTable:
        seen.extend(files[source.id])
        frame = read_rows(files[source.id][0], TABLE, schema=mart_schema(), key=KEY)
        return BuiltTable(frame, {source.id: "rows of the committed file"})

    return Builder(
        TABLE, "finance", (source.id,), build, schema=mart_schema(), key=KEY,
        manual_parsers={source.id: toy_parser},
    )  # fmt: skip


def run_build(builder: Builder, source: Source, rows_dir: Path, build_dir: Path) -> list[Path]:
    return build_tables(
        [builder], Lockfile(), build_dir / "raw", build_dir, {source.id: source}, rows_dir
    )


def test_build_uses_the_committed_rows_with_no_raw_file(
    source: Source, manual_dir: Path, tmp_path: Path
) -> None:
    rows_dir = tmp_path / "rows"
    committed = extract(source, manual_dir, rows_dir)
    (manual_dir / manual_name(source)).unlink()
    seen: list[Path] = []
    [table] = run_build(mart_builder(source, seen), source, rows_dir, tmp_path / "build")
    assert seen == [committed]
    frame = pd.read_parquet(table)
    assert frame["code"].tolist() == ["07", "08"]
    assert frame["amount"].tolist() == [1234.56, 0.1 + 0.2]


def test_build_refuses_a_committed_file_with_another_checksum_and_writes_nothing(
    source: Source, manual_dir: Path, tmp_path: Path
) -> None:
    rows_dir = tmp_path / "rows"
    committed = extract(source, manual_dir, rows_dir)
    other = "0" * 64
    committed.write_text(committed.read_text().replace(sha256_of(RAW_TEXT), other))
    with pytest.raises(BuildError) as error:
        run_build(mart_builder(source, []), source, rows_dir, tmp_path / "build")
    for part in (source.id, other, sha256_of(RAW_TEXT)):
        assert part in str(error.value)
    assert not (tmp_path / "build").exists()


def test_build_with_no_committed_file_says_to_extract(source: Source, tmp_path: Path) -> None:
    with pytest.raises(BuildError, match=rf"{source.id}.*run extract {TABLE}"):
        run_build(mart_builder(source, []), source, tmp_path / "rows", tmp_path / "build")


def test_equality_check_names_the_row_that_differs_and_skips_without_the_raw_file(
    source: Source, manual_dir: Path, tmp_path: Path
) -> None:
    rows_dir = tmp_path / "rows"
    committed = extract(source, manual_dir, rows_dir)
    options = {"schema": mart_schema(), "key": KEY}
    assert compare_rows(toy_parser, source, TABLE, rows_dir, manual_dir, **options) == []
    committed.write_text(committed.read_text().replace("1234.56", "1234.57"))
    [line] = compare_rows(toy_parser, source, TABLE, rows_dir, manual_dir, **options) or []
    assert "row 1" in line
    assert "'amount'" in line
    assert "1234.57" in line
    (manual_dir / manual_name(source)).unlink()
    assert compare_rows(toy_parser, source, TABLE, rows_dir, manual_dir, **options) is None


def test_extraction_without_the_raw_file_or_with_a_bad_rows_stops(
    source: Source, manual_dir: Path, tmp_path: Path
) -> None:
    (manual_dir / manual_name(source)).write_bytes(b"other")
    with pytest.raises(ManualRowsError, match="has SHA-256"):
        extract(source, manual_dir, tmp_path / "rows")
    (manual_dir / manual_name(source)).unlink()
    with pytest.raises(ManualRowsError, match="not in"):
        extract(source, manual_dir, tmp_path / "rows")
    (manual_dir / manual_name(source)).write_bytes(RAW_TEXT)
    broken: RowParser = lambda files: toy_parser(files).assign(amount=[1.0, 1.0], code=["1", "1"])  # noqa: E731
    with pytest.raises(TableError):
        extract_rows(
            broken, source, TABLE, tmp_path / "rows", manual_dir, schema=mart_schema(), key=KEY
        )
    assert not rows_path(tmp_path / "rows", source.id, TABLE).exists()


def registered_manual_tables() -> list[tuple[Builder, str]]:
    return [(b, source_id) for b in load_builders() for source_id in b.manual_parsers]


@pytest.mark.parametrize(("builder", "source_id"), registered_manual_tables())
def test_committed_rows_equal_the_parser_output(builder: Builder, source_id: str) -> None:
    """Runs on the machine that has the raw file in `data/manual/`; skipped elsewhere."""
    differences = compare_rows(
        builder.manual_parsers[source_id],
        load_manifest(MANIFEST_DIR)[source_id],
        builder.table,
        DEFAULT_ROWS_DIR,
        schema=builder.schema,
        key=builder.key,
    )
    if differences is None:
        pytest.skip(f"the raw file of {source_id} is not in data/manual/")
    assert differences == []
