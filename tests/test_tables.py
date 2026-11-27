import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from core.tables.schemas import KEYS, SCHEMAS, frame_check_columns
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
    with pytest.raises(TableError, match=r"column 'basis': missing column") as error:
        validate_table(frame, "state_budget_lines")
    assert "column 'state_budget_lines'" not in str(error.value)


def test_extra_column_is_refused() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["extra"] = 1
    with pytest.raises(TableError, match=r"column 'extra': unexpected column") as error:
        validate_table(frame, "state_budget_lines")
    assert "column 'state_budget_lines'" not in str(error.value)


def test_extra_column_is_allowed_in_legislative_texts() -> None:
    validate_table(good_frames()["legislative_texts"], "legislative_texts")


def test_code_column_refuses_a_number() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["programme_code"] = [101, 102]
    with pytest.raises(TableError, match="programme_code"):
        validate_table(frame, "state_budget_lines")


def test_code_keeps_leading_zero_as_text() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["programme_code"] = ["006", "102"]
    validate_table(frame, "state_budget_lines")


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


def test_change_notes_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    notes = {"b": "Kept the programme rows only.", "a": "Converted thousands to euros."}
    written = write_table(
        good_frames()["state_budget_lines"],
        "state_budget_lines",
        path,
        ["a", "b"],
        changes=notes,
        build_date=BUILD_DATE,
        commit=COMMIT,
    )
    metadata = read_metadata(path)
    assert metadata == written
    assert dict(metadata.changes) == notes
    assert list(metadata.changes) == ["a", "b"]


def test_change_notes_default_to_none(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    frame = good_frames()["state_budget_lines"]
    write_table(frame, "state_budget_lines", path, ["a"], build_date=BUILD_DATE, commit=COMMIT)
    assert dict(read_metadata(path).changes) == {}


@pytest.mark.parametrize(
    ("notes", "message"),
    [
        ({"c": "Kept two rows."}, r"change notes for sources it does not use: c"),
        ({"a": "  "}, r"empty change notes for: a"),
    ],
)
def test_bad_change_notes_write_no_file(
    tmp_path: Path, notes: dict[str, str], message: str
) -> None:
    path = tmp_path / "t.parquet"
    frame = good_frames()["state_budget_lines"]
    with pytest.raises(TableError, match=message):
        write_table(
            frame,
            "state_budget_lines",
            path,
            ["a"],
            changes=notes,
            build_date=BUILD_DATE,
            commit=COMMIT,
        )
    assert not path.exists()


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


EXPECTED_KEYS = {
    "state_budget_lines": [
        "year",
        "budget_part",
        "programme_code",
        "title_group",
        "stage",
        "credit_type",
    ],
    "nomenclature": ["year", "programme_code"],
    "state_revenue_lines": ["year", "budget_part", "hierarchy_level", "line_label", "stage"],
    "state_employment": ["year", "programme_code", "stage"],
    "state_monthly": ["year", "month", "category", "sub_category", "line_label"],
    "state_balance_sheet": ["year", "statement", "line_label"],
    "performance_indicators": ["year", "programme_code", "indicator_code", "sub_indicator_code"],
    "macro_fr": ["year", "month", "indicator", "sector", "unit", "source_id"],
    "fiscal_commitments": ["document", "document_date", "target_year", "indicator"],
}


def test_keys_are_those_of_section_5() -> None:
    assert {table: list(key) for table, key in KEYS.items()} == EXPECTED_KEYS


@pytest.mark.parametrize("table", sorted(EXPECTED_KEYS))
def test_each_key_column_is_needed_to_tell_rows_apart(table: str) -> None:
    key = EXPECTED_KEYS[table]
    for column in key:
        assert column in KEYS[table], f"{table}: key column {column} is missing"
    assert len(KEYS[table]) == len(key), f"{table}: key has an extra column"


@pytest.mark.parametrize("code", ["7", "10", "1011", "10A", "", " 10", "١٢٣", "123\n"])
@pytest.mark.parametrize("table", ["state_budget_lines", "state_employment"])
def test_programme_code_must_be_three_digits(table: str, code: str) -> None:
    frame = good_frames()[table]
    frame.loc[0, "programme_code"] = code
    with pytest.raises(TableError, match="programme_code"):
        validate_table(frame, table)


def test_programme_code_three_digits_in_nomenclature_and_indicators() -> None:
    for table in ("nomenclature", "performance_indicators"):
        frame = good_frames()[table]
        frame.loc[0, "programme_code"] = "7"
        with pytest.raises(TableError, match="programme_code"):
            validate_table(frame, table)


def test_nullable_programme_code_keeps_its_null() -> None:
    frame = good_frames()["performance_indicators"]
    assert frame["programme_code"].isna().any()
    validate_table(frame, "performance_indicators")


@pytest.mark.parametrize("code", ["J", "JAA", "06", "ja", "J1", ""])
def test_mission_code_must_be_two_capital_letters(code: str) -> None:
    frame = good_frames()["nomenclature"]
    frame.loc[0, "mission_code"] = code
    with pytest.raises(TableError, match="mission_code"):
        validate_table(frame, "nomenclature")


def test_line_code_must_be_digits() -> None:
    frame = good_frames()["state_revenue_lines"]
    frame.loc[0, "line_code"] = "11A"
    with pytest.raises(TableError, match="line_code"):
        validate_table(frame, "state_revenue_lines")


def test_a_year_and_stage_cannot_mix_two_basis_values() -> None:
    frame = good_frames()["state_budget_lines"]
    frame["basis"] = ["budget", "pdf_extraction"]
    with pytest.raises(TableError, match="one_basis_for_each_year_and_stage"):
        validate_table(frame, "state_budget_lines")
    frame["stage"] = ["voted", "executed"]
    validate_table(frame, "state_budget_lines")


@pytest.mark.parametrize(
    ("changes", "rule"),
    [
        ({"target_value": [None, None]}, "target_value_filled_when_target_kind_is_numeric"),
        (
            {"target_kind": ["none", "qualitative"], "target_value": [90.0, None]},
            "target_value_null_when_target_kind_is_none",
        ),
        ({"target_text": [None, None]}, "target_text_filled_when_target_kind_is_qualitative"),
    ],
)
def test_target_columns_follow_target_kind(changes: dict[str, list[object]], rule: str) -> None:
    frame = good_frames()["performance_indicators"]
    for column, values in changes.items():
        frame[column] = values
    frame["target_value"] = frame["target_value"].astype("float64")
    with pytest.raises(TableError, match=rule):
        validate_table(frame, "performance_indicators")


def test_hand_entry_needs_a_reference_and_file_entry_has_none() -> None:
    frame = good_frames()["fiscal_commitments"]
    frame["reference"] = [None, None]
    with pytest.raises(TableError, match="reference_filled_when_entry_method_is_hand"):
        validate_table(frame, "fiscal_commitments")
    frame["reference"] = ["art. 2", "art. 1"]
    with pytest.raises(TableError, match="reference_null_when_entry_method_is_file"):
        validate_table(frame, "fiscal_commitments")


def test_all_null_nullable_column_round_trips_with_the_schema_types(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    frame = good_frames()["macro_fr"]
    frame["sector"] = pd.Series([None, None], dtype="string")
    frame["month"] = pd.array([None, None], dtype="Int8")
    frame["unit"] = ["eur", "pct"]
    write_table(frame, "macro_fr", path, ["a"], build_date=BUILD_DATE, commit=COMMIT)
    parquet_types = {field.name: str(field.type) for field in pq.read_schema(path)}
    assert parquet_types["sector"] == "string"
    assert parquet_types["month"] == "int8"
    back = pd.read_parquet(path)
    assert back["sector"].isna().all()
    validate_table(back, "macro_fr")


def test_all_null_object_column_is_written_as_string(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    frame = good_frames()["macro_fr"]
    frame["sector"] = [None, None]
    frame["unit"] = ["eur", "pct"]
    write_table(frame, "macro_fr", path, ["a"], build_date=BUILD_DATE, commit=COMMIT)
    assert str(pq.read_schema(path).field("sector").type) == "string"
    validate_table(pd.read_parquet(path), "macro_fr")


CROSS_COLUMN_CASES = [
    (
        "state_budget_lines",
        {"basis": ["budget", "pdf_extraction"], "stage": ["voted", "voted"]},
        "one_basis_for_each_year_and_stage",
        ("year", "stage", "basis"),
    ),
    (
        "performance_indicators",
        {"target_value": [None, None]},
        "target_value_filled_when_target_kind_is_numeric",
        ("target_kind", "target_value"),
    ),
    (
        "performance_indicators",
        {"target_kind": ["none", "qualitative"], "target_value": [90.0, None]},
        "target_value_null_when_target_kind_is_none",
        ("target_kind", "target_value"),
    ),
    (
        "performance_indicators",
        {"target_text": [None, None]},
        "target_text_filled_when_target_kind_is_qualitative",
        ("target_kind", "target_text"),
    ),
    (
        "fiscal_commitments",
        {"reference": [None, None]},
        "reference_filled_when_entry_method_is_hand",
        ("entry_method", "reference"),
    ),
    (
        "fiscal_commitments",
        {"reference": ["art. 2", "art. 1"]},
        "reference_null_when_entry_method_is_file",
        ("entry_method", "reference"),
    ),
]


def _cross_column_error(table: str, changes: dict[str, list[object]]) -> str:
    frame = good_frames()[table]
    for column, values in changes.items():
        frame[column] = values
    if "target_value" in changes:
        frame["target_value"] = frame["target_value"].astype("float64")
    with pytest.raises(TableError) as error:
        validate_table(frame, table)
    return str(error.value)


def test_every_frame_rule_declares_its_columns() -> None:
    covered = {rule for _, _, rule, _ in CROSS_COLUMN_CASES}
    checks = [check for schema in SCHEMAS.values() for check in schema.checks]
    assert {check.name for check in checks} == covered
    for check in checks:
        columns = frame_check_columns(check)
        assert columns is not None and len(columns) >= 2, check.name


@pytest.mark.parametrize(("table", "changes", "rule", "columns"), CROSS_COLUMN_CASES)
def test_cross_column_error_names_the_rule_and_every_column_it_reads(
    table: str, changes: dict[str, list[object]], rule: str, columns: tuple[str, ...]
) -> None:
    lines = [line for line in _cross_column_error(table, changes).splitlines() if rule in line]
    assert len(lines) == 1
    assert f"on columns ({', '.join(columns)})" in lines[0]


def test_three_bad_rows_of_one_rule_are_each_named_once() -> None:
    frame = good_frames()["performance_indicators"]
    frame = pd.concat([frame.iloc[[0]]] * 3, ignore_index=True)
    frame["target_value"] = pd.Series([None, None, None], dtype="float64")
    frame.index = pd.Index([10, 11, 12])
    with pytest.raises(TableError) as error:
        validate_table(frame, "performance_indicators")
    message = str(error.value)
    assert message.count("target_value_filled_when_target_kind_is_numeric") == 1
    assert message.splitlines()[-1].endswith("fails for rows 10, 11, 12")
    assert len(message.splitlines()) == 2


def test_a_rule_on_the_whole_frame_names_the_frame_when_no_row_is_bad() -> None:
    message = _cross_column_error(*CROSS_COLUMN_CASES[0][:2])
    assert "fails for the frame as a whole" in message
