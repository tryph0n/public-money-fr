import datetime
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import pyarrow.parquet as pq
import pytest

from core.tables.schemas import PERFORMANCE_INDICATORS, frame_check
from core.tables.writer import TableError, read_metadata, validate_table, write_table
from tests.test_tables import good_frames

DAY = datetime.date(2026, 11, 1)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
KEY = ("year", "code")


def mart_schema(rule_name: str = "amount_above_100_when_flagged") -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            "year": pa.Column("int16", description="Year."),
            "code": pa.Column("string", description="Code."),
            "flag": pa.Column("bool", description="Flag."),
            "amount": pa.Column("float64", description="Amount in euros."),
            "source_id": pa.Column("string", description="Source id."),
        },
        checks=[
            frame_check(
                rule_name,
                ("flag", "amount"),
                lambda frame: ~frame["flag"] | (frame["amount"] > 100),
            )
        ],
        strict=True,
        name="mart_example",
    )


def mart_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "year": pd.array([2020, 2021], dtype="int16"),
            "code": pd.array(["001", "002"], dtype="string"),
            "flag": [True, False],
            "amount": [150.0, 5.0],
            "source_id": ["ameco-net-lending", "ameco-net-lending"],
        }
    )


def write_mart(path: Path, frame: pd.DataFrame) -> None:
    write_table(
        frame,
        "mart_example",
        path,
        ["ameco-net-lending"],
        schema=mart_schema(),
        key=KEY,
        build_date=DAY,
        commit=COMMIT,
    )


def test_project_table_round_trips_with_the_types_of_its_schema(tmp_path: Path) -> None:
    path = tmp_path / "mart.parquet"
    write_mart(path, mart_frame())
    metadata = read_metadata(path)
    assert metadata.table == "mart_example"
    assert metadata.source_ids == ("ameco-net-lending",)
    types = {field.name: str(field.type) for field in pq.read_schema(path)}
    assert types == {
        "year": "int16",
        "code": "string",
        "flag": "bool",
        "amount": "double",
        "source_id": "string",
    }


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (mart_frame().assign(amount=["x", "y"]), "column 'amount'"),
        (mart_frame().assign(code=["001", "001"], year=[2020, 2020]), "repeated key"),
    ],
)
def test_broken_project_frame_raises_and_writes_nothing(
    tmp_path: Path, frame: pd.DataFrame, message: str
) -> None:
    frame["year"] = frame["year"].astype("int16")
    path = tmp_path / "mart.parquet"
    with pytest.raises(TableError, match=message):
        write_mart(path, frame)
    assert not path.exists()


def test_failed_project_rule_names_its_columns_and_a_shared_rule_keeps_its_own() -> None:
    shared_rule = PERFORMANCE_INDICATORS.checks[0].name
    assert shared_rule is not None
    frame = mart_frame().assign(amount=[50.0, 5.0])
    with pytest.raises(TableError, match=r"on columns \(flag, amount\)"):
        validate_table(frame, "mart_example", schema=mart_schema(shared_rule), key=KEY)
    shared = good_frames()["performance_indicators"]
    shared["target_kind"] = "numeric"
    shared["target_value"] = pd.Series([None] * len(shared), dtype="float64")
    with pytest.raises(TableError, match=r"on columns \(target_kind, target_value\)"):
        validate_table(shared, "performance_indicators")


def test_project_table_cannot_take_the_name_of_a_shared_table() -> None:
    with pytest.raises(TableError, match="'macro_fr'"):
        validate_table(mart_frame(), "macro_fr", schema=mart_schema(), key=KEY)


def test_unsupported_column_type_is_named(tmp_path: Path) -> None:
    schema = pa.DataFrameSchema(
        {"year": pa.Column("int32", description="Year.")}, strict=True, name="mart_example"
    )
    frame = pd.DataFrame({"year": pd.array([2020], dtype="int32")})
    path = tmp_path / "mart.parquet"
    with pytest.raises(TableError, match=r"column 'year' has type 'int32'"):
        write_table(frame, "mart_example", path, [], schema=schema, key=("year",), commit=COMMIT)
    assert not path.exists()


def test_schema_and_key_must_come_together() -> None:
    with pytest.raises(TableError, match="needs a schema"):
        validate_table(good_frames()["macro_fr"], "macro_fr", key=("year",))
    with pytest.raises(TableError, match="needs a key"):
        validate_table(mart_frame(), "mart_example", schema=mart_schema())
    with pytest.raises(TableError, match="key columns not in the schema: nope"):
        validate_table(mart_frame(), "mart_example", schema=mart_schema(), key=("nope",))
