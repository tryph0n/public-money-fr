import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from core.tables.schemas import KEYS, SCHEMAS
from core.tables.writer import TableError, read_metadata, validate_table, write_table

COMMIT = "0123456789abcdef0123456789abcdef01234567"
BUILD_DATE = datetime.date(2026, 11, 26)


def good_frames() -> dict[str, pd.DataFrame]:
    """One valid two-row frame for each table."""
    return {
        "state_budget_lines": pd.DataFrame(
            {
                "year": pd.array([2020, 2020], dtype="int16"),
                "budget_part": ["BG", "BG"],
                "programme_code": ["101", "102"],
                "title_group": ["T2", "other"],
                "stage": ["voted", "voted"],
                "credit_type": ["AE", "CP"],
                "basis": ["budget", "budget"],
                "amount_eur": [1.5, -2.0],
                "source_id": ["a", "a"],
            }
        ),
        "nomenclature": pd.DataFrame(
            {
                "year": pd.array([2020, 2020], dtype="int16"),
                "programme_code": ["101", "102"],
                "budget_part": ["BG", "BG"],
                "programme_label": ["One", "Two"],
                "mission_code": ["JA", None],
                "mission_label": ["Justice", None],
                "mission_family": ["justice", "other"],
            }
        ),
        "state_revenue_lines": pd.DataFrame(
            {
                "year": pd.array([2024, 2024], dtype="int16"),
                "budget_part": ["BG", "BG"],
                "hierarchy_level": pd.array([0, None], dtype="Int8"),
                "line_label": ["Tax", "Other"],
                "line_code": ["1101", None],
                "category": ["c", "c"],
                "stage": ["voted", "collected"],
                "amount_eur": [1.0, 2.0],
                "source_id": ["a", "a"],
            }
        ),
        "state_employment": pd.DataFrame(
            {
                "year": pd.array([2020, 2020], dtype="int16"),
                "budget_part": ["BG", "BA"],
                "programme_code": ["101", "612"],
                "stage": ["voted", "executed"],
                "fte": [10.5, 3.0],
                "source_id": ["a", "a"],
            }
        ),
        "state_monthly": pd.DataFrame(
            {
                "year": pd.array([2024, 2024], dtype="int16"),
                "month": pd.array([1, 2], dtype="int8"),
                "hierarchy_level": pd.array([1, 1], dtype="int8"),
                "category": ["Dépenses", "Recettes"],
                "sub_category": ["x", None],
                "line_label": ["l", "l"],
                "amount_eur": [1.0, 2.0],
                "source_id": ["a", "a"],
            }
        ),
        "legislative_texts": pd.DataFrame(
            {
                "year": pd.array([2020, 2021], dtype="int16"),
                "source_id": ["a", "a"],
                "total": [1.0, 2.0],
            }
        ),
        "state_balance_sheet": pd.DataFrame(
            {
                "year": pd.array([2022, 2022], dtype="int16"),
                "statement": ["balance_sheet", "income_statement"],
                "line_label": ["l", "l"],
                "amount_eur": [1.0, 2.0],
                "source_id": ["a", "a"],
            }
        ),
        "performance_indicators": pd.DataFrame(
            {
                "year": pd.array([2022, 2022], dtype="int16"),
                "mission_label": ["m", "m"],
                "programme_code": ["176", None],
                "indicator_code": ["1.1", "1.1"],
                "indicator_label": ["i", "i"],
                "sub_indicator_code": [None, None],
                "sub_indicator_label": [None, None],
                "unit": ["%", "%"],
                "target_kind": ["numeric", "qualitative"],
                "target_value": [90.0, None],
                "target_text": [None, "En hausse"],
                "result_value": [80.0, None],
                "reported_attainment": [None, None],
                "source_id": ["a", "a"],
            }
        ),
        "macro_fr": pd.DataFrame(
            {
                "year": pd.array([2022, 2022], dtype="int16"),
                "month": pd.array([1, None], dtype="Int8"),
                "indicator": ["gdp", "gdp"],
                "sector": [None, "S13"],
                "value": [1.0, 2.0],
                "unit": ["eur", "pct_gdp"],
                "is_forecast": [False, True],
                "source_id": ["a", "a"],
            }
        ),
        "fiscal_commitments": pd.DataFrame(
            {
                "commitment_type": ["stability_programme", "programming_law"],
                "document": ["d", "d"],
                "document_date": [datetime.date(2016, 4, 1), datetime.date(2016, 5, 1)],
                "reference": [None, "art. 1"],
                "entry_method": ["file", "hand"],
                "target_year": pd.array([2019, 2019], dtype="int16"),
                "indicator": ["gross_debt", "gross_debt"],
                "value": [1.0, 2.0],
                "unit": ["eur", "pct"],
                "source_id": ["a", "a"],
            }
        ),
    }


def test_every_schema_has_a_good_frame() -> None:
    assert set(good_frames()) == set(SCHEMAS)
    assert len(SCHEMAS) == 10


@pytest.mark.parametrize("table", sorted(SCHEMAS))
def test_good_frame_passes(table: str) -> None:
    validate_table(good_frames()[table], table)


@pytest.mark.parametrize("table", sorted(KEYS))
def test_key_columns_are_columns_of_the_schema(table: str) -> None:
    assert set(KEYS[table]) <= set(SCHEMAS[table].columns)


@pytest.mark.parametrize("table", sorted(SCHEMAS))
def test_every_column_has_a_description(table: str) -> None:
    for name, column in SCHEMAS[table].columns.items():
        assert column.description, f"{table}.{name} has no description"


def test_each_amount_column_states_its_unit() -> None:
    amount_columns = 0
    for table, schema in SCHEMAS.items():
        for name, column in schema.columns.items():
            if str(column.dtype) != "float64":
                continue
            amount_columns += 1
            description = (column.description or "").lower()
            assert "euros" in description or "etpt" in description or "unit" in description, (
                f"{table}.{name} does not state a unit"
            )
    assert amount_columns == 9


def test_amount_columns_in_euros_say_not_thousands() -> None:
    for table, schema in SCHEMAS.items():
        column = schema.columns.get("amount_eur")
        if column is not None:
            assert "not thousands or billions" in (column.description or ""), table


@pytest.mark.parametrize("table", sorted(SCHEMAS))
def test_year_is_int16_when_present(table: str) -> None:
    for name in ("year", "target_year"):
        column = SCHEMAS[table].columns.get(name)
        if column is not None:
            assert str(column.dtype) == "int16"


def test_broken_column_is_named() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["amount_eur"] = ["a", "b"]
    with pytest.raises(TableError, match="amount_eur"):
        validate_table(frame, "state_budget_lines")


def test_missing_column_is_named() -> None:
    frame = good_frames()["state_budget_lines"].drop(columns=["basis"])
    with pytest.raises(TableError, match="basis"):
        validate_table(frame, "state_budget_lines")


def test_extra_column_is_refused() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["extra"] = 1
    with pytest.raises(TableError, match="extra"):
        validate_table(frame, "state_budget_lines")


def test_extra_column_is_allowed_in_legislative_texts() -> None:
    validate_table(good_frames()["legislative_texts"], "legislative_texts")


def test_code_column_refuses_a_number() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["programme_code"] = [101, 102]
    with pytest.raises(TableError, match="programme_code"):
        validate_table(frame, "state_budget_lines")


def test_code_keeps_leading_zero_as_text() -> None:
    frame = good_frames()["nomenclature"]
    frame["mission_code"] = ["06", None]
    validate_table(frame, "nomenclature")


def test_year_must_be_int16() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["year"] = frame["year"].astype("int64")
    with pytest.raises(TableError, match="year"):
        validate_table(frame, "state_budget_lines")


def test_amount_must_be_float64() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["amount_eur"] = pd.array([1, 2], dtype="int64")
    with pytest.raises(TableError, match="amount_eur"):
        validate_table(frame, "state_budget_lines")


def test_negative_amount_is_allowed() -> None:
    frame = good_frames()["state_budget_lines"]
    assert (frame["amount_eur"] < 0).any()
    validate_table(frame, "state_budget_lines")


def test_empty_amount_is_refused() -> None:
    frame = good_frames()["state_budget_lines"]
    frame.loc[0, "amount_eur"] = float("nan")
    with pytest.raises(TableError, match="amount_eur"):
        validate_table(frame, "state_budget_lines")


def test_unknown_allowed_value_is_refused() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["credit_type"] = ["AE", "XX"]
    with pytest.raises(TableError, match="credit_type"):
        validate_table(frame, "state_budget_lines")


def test_null_is_refused_in_a_column_that_is_not_nullable() -> None:
    frame = good_frames()["nomenclature"]
    frame["programme_label"] = ["One", None]
    with pytest.raises(TableError, match="programme_label"):
        validate_table(frame, "nomenclature")


def test_month_out_of_range_is_refused() -> None:
    frame = good_frames()["state_monthly"]
    frame["month"] = pd.array([1, 13], dtype="int8")
    with pytest.raises(TableError, match="month"):
        validate_table(frame, "state_monthly")


def test_unknown_table_is_refused() -> None:
    with pytest.raises(TableError, match="unknown table"):
        validate_table(pd.DataFrame(), "no_such_table")


def test_repeated_key_is_refused() -> None:
    frame = good_frames()["state_employment"]
    frame.loc[1, ["budget_part", "programme_code", "stage"]] = ["BG", "101", "voted"]
    with pytest.raises(TableError, match="repeated key"):
        validate_table(frame, "state_employment")


def test_two_nulls_in_a_key_are_a_duplicate() -> None:
    frame = good_frames()["macro_fr"]
    frame["month"] = pd.array([None, None], dtype="Int8")
    frame["sector"] = [None, None]
    frame["unit"] = ["eur", "eur"]
    with pytest.raises(TableError, match="repeated key"):
        validate_table(frame, "macro_fr")


def test_write_reads_back_metadata(tmp_path: Path) -> None:
    path = tmp_path / "out" / "t.parquet"
    frame = good_frames()["state_budget_lines"]
    written = write_table(
        frame,
        "state_budget_lines",
        path,
        ["b", "a", "b"],
        build_date=BUILD_DATE,
        commit=COMMIT,
    )
    metadata = read_metadata(path)
    assert metadata == written
    assert metadata.table == "state_budget_lines"
    assert metadata.source_ids == ("a", "b")
    assert metadata.build_date == "2026-11-26"
    assert metadata.commit == COMMIT


def test_written_rows_and_types_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    frame = good_frames()["state_budget_lines"]
    write_table(frame, "state_budget_lines", path, ["a"], build_date=BUILD_DATE, commit=COMMIT)
    back = pd.read_parquet(path)
    pd.testing.assert_frame_equal(back, frame)
    validate_table(back, "state_budget_lines")


@pytest.mark.parametrize("table", sorted(SCHEMAS))
def test_every_table_can_be_written(table: str, tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    write_table(good_frames()[table], table, path, ["a"], build_date=BUILD_DATE, commit=COMMIT)
    assert read_metadata(path).table == table
    assert pq.read_table(path).num_rows == 2


def test_write_defaults_to_today_and_git_commit(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    write_table(good_frames()["state_employment"], "state_employment", path, ["a"])
    metadata = read_metadata(path)
    assert metadata.build_date == datetime.date.today().isoformat()
    assert len(metadata.commit) == 40


def test_broken_frame_writes_no_file(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    frame = good_frames()["state_budget_lines"]
    frame["programme_code"] = [101, 102]
    with pytest.raises(TableError, match="programme_code"):
        write_table(frame, "state_budget_lines", path, ["a"], build_date=BUILD_DATE, commit=COMMIT)
    assert not path.exists()


def test_file_without_metadata_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "plain.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(path)
    with pytest.raises(TableError, match="no table metadata"):
        read_metadata(path)
