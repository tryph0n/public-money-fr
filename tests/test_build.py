import dataclasses
import io
import logging
import zipfile
from collections.abc import Iterator, Mapping
from pathlib import Path

import pandera.pandas as pa
import pytest

from core.cli import main
from core.sources.manifest import MANIFEST_DIR, Source, load_manifest
from core.tables.build import Builder, BuildError, BuiltTable, check_builders, validate_build
from core.tables.writer import write_table
from tests.fake_server import FakeServer, body, running_server
from tests.test_project_tables import COMMIT, DAY, KEY, mart_frame, mart_schema

SOURCE_ID = "ameco-net-lending"
MEMBER = "AMECO16.TXT"


@pytest.fixture
def server() -> Iterator[FakeServer]:
    with running_server() as fake:
        yield fake


def archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr(MEMBER, b"FRA;1;2\n")
    return buffer.getvalue()


def mart_builder(table: str = "mart_example", dataset: str = "finance") -> Builder:
    def build(files: Mapping[str, list[Path]]) -> BuiltTable:
        assert [path.name for path in files[SOURCE_ID]] == [MEMBER]
        return BuiltTable(mart_frame(), {SOURCE_ID: "kept the three series"})

    return Builder(table, dataset, (SOURCE_ID,), build, schema=mart_schema(), key=KEY)


@pytest.fixture
def workspace(server: FakeServer, tmp_path: Path) -> list[str]:
    """Options that point every command at a manifest of one source served locally."""
    server.serve("/ameco.zip", body(archive(), "application/zip"))
    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    text = (MANIFEST_DIR / f"{SOURCE_ID}.yaml").read_text(encoding="utf-8")
    old = "https://ec.europa.eu/economy_finance/db_indicators/ameco/documents/ameco16.zip"
    assert old in text
    (manifest_dir / f"{SOURCE_ID}.yaml").write_text(
        text.replace(old, f"{server.url}/ameco.zip"), encoding="utf-8"
    )
    return ["--manifest-dir", str(manifest_dir)]


def fetch_options(tmp_path: Path) -> list[str]:
    return ["--raw-dir", str(tmp_path / "raw"), "--lock", str(tmp_path / "lock.json")]


def build_options(tmp_path: Path) -> list[str]:
    return [*fetch_options(tmp_path), "--build-dir", str(tmp_path / "build")]


def test_fetch_build_validate_in_a_row_from_empty_folders(
    workspace: list[str], tmp_path: Path
) -> None:
    builders = [mart_builder()]
    assert main(["fetch", *workspace, *fetch_options(tmp_path)]) == 0
    assert main(["build", *workspace, *build_options(tmp_path)], builders) == 0
    assert (tmp_path / "build" / "finance" / "mart_example.parquet").is_file()
    assert main(["validate", *workspace, "--build-dir", str(tmp_path / "build")], builders) == 0


def test_build_filters_by_table_and_dataset_and_validate_by_dataset(
    workspace: list[str], tmp_path: Path
) -> None:
    builders = [mart_builder("mart_a", "finance"), mart_builder("mart_b", "security")]
    assert main(["fetch", *workspace, *fetch_options(tmp_path)]) == 0
    options = [*workspace, *build_options(tmp_path)]
    assert main(["build", "mart_b", *options], builders) == 0
    build = tmp_path / "build"
    assert [p.name for p in build.rglob("*.parquet")] == ["mart_b.parquet"]
    assert main(["build", "finance", *options], builders) == 0
    assert (build / "finance" / "mart_a.parquet").is_file()
    (build / "security" / "mart_b.parquet").write_bytes(b"not parquet")
    assert main(["validate", "finance", *workspace, "--build-dir", str(build)], builders) == 0
    assert main(["validate", "security", *workspace, "--build-dir", str(build)], builders) == 2
    assert main(["build", "nothing", *options], builders) == 2


def test_build_with_no_builder_exits_zero_and_writes_nothing(
    workspace: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["build", *workspace, *build_options(tmp_path)], []) == 0
    assert "no builder registered" in capsys.readouterr().out
    assert not (tmp_path / "build").exists()


def test_build_of_a_source_not_in_the_raw_cache_names_it_and_writes_nothing(
    workspace: list[str], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    code = main(["build", *workspace, *build_options(tmp_path)], [mart_builder()])
    assert code == 1
    assert SOURCE_ID in caplog.text
    assert "run fetch" in caplog.text
    assert not (tmp_path / "build").exists()


def test_a_failed_builder_names_its_table_and_leaves_no_file(
    workspace: list[str], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(files: Mapping[str, list[Path]]) -> BuiltTable:
        frame = mart_frame()
        frame.loc[0, "amount"] = 5.0
        return BuiltTable(frame, {SOURCE_ID: "x"})

    builder = dataclasses.replace(mart_builder(), build=broken)
    assert main(["fetch", *workspace, *fetch_options(tmp_path)]) == 0
    assert main(["build", *workspace, *build_options(tmp_path)], [builder]) == 1
    assert "mart_example" in caplog.text
    assert list((tmp_path / "build").rglob("*.parquet*")) == []


@pytest.fixture
def manifest() -> dict[str, Source]:
    return load_manifest(MANIFEST_DIR)


def write_file(
    path: Path, *, table: str = "mart_example", schema: pa.DataFrameSchema | None = None
) -> Path:
    frame = mart_frame()
    if schema is None:
        schema = mart_schema()
    else:
        frame.loc[0, "amount"] = 5.0
    write_table(
        frame,
        table,
        path,
        [SOURCE_ID],
        schema=schema,
        key=KEY,
        build_date=DAY,
        commit=COMMIT,
    )
    return path


def loose_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(mart_schema().columns, strict=True, name="mart_example")


def test_validate_accepts_a_good_build(tmp_path: Path, manifest: dict[str, Source]) -> None:
    write_file(tmp_path / "finance" / "mart_example.parquet")
    assert validate_build([mart_builder()], [], manifest, tmp_path) == []


def test_validate_refuses_a_table_that_breaks_its_schema(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    path = write_file(tmp_path / "finance" / "mart_example.parquet", schema=loose_schema())
    problems = validate_build([mart_builder()], ["finance"], manifest, tmp_path)
    assert len(problems) == 1
    assert problems[0].startswith(str(path))
    assert "amount_above_100_when_flagged" in problems[0]


def test_validate_refuses_a_file_with_no_registered_builder(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    path = write_file(tmp_path / "finance" / "mart_old.parquet", table="mart_old")
    problems = validate_build([mart_builder()], ["finance"], manifest, tmp_path)
    assert any(p.startswith(str(path)) and "no registered builder" in p for p in problems)


def test_validate_refuses_a_source_with_no_last_update(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    path = write_file(tmp_path / "finance" / "mart_example.parquet")
    manifest[SOURCE_ID] = dataclasses.replace(manifest[SOURCE_ID], last_update=None)
    problems = validate_build([mart_builder()], ["finance"], manifest, tmp_path)
    assert problems == [f"{path}: source {SOURCE_ID} has no last_update in the manifest"]


def test_validate_refuses_a_source_that_is_not_in_the_manifest(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    path = write_file(tmp_path / "finance" / "mart_example.parquet")
    del manifest[SOURCE_ID]
    problems = validate_build([mart_builder()], ["finance"], manifest, tmp_path)
    assert problems == [f"{path}: source {SOURCE_ID} is not in the manifest"]


def test_validate_refuses_the_missing_table_of_a_registered_builder(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    write_file(tmp_path / "finance" / "mart_example.parquet")
    problems = validate_build(
        [mart_builder(), mart_builder("mart_two")], ["finance"], manifest, tmp_path
    )
    missing = tmp_path / "finance" / "mart_two.parquet"
    assert problems == [f"{missing}: missing; build table 'mart_two'"]


def test_validate_command_gives_one_line_for_a_file_that_is_not_parquet(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "build" / "finance" / "mart_example.parquet"
    path.parent.mkdir(parents=True)
    path.write_text("hello")
    with caplog.at_level(logging.ERROR):
        code = main(["validate", "--build-dir", str(tmp_path / "build")], [mart_builder()])
    assert code == 2
    lines = [r.getMessage() for r in caplog.records if str(path) in r.getMessage()]
    assert len(lines) == 1
    assert "\n" not in lines[0]
    assert "Traceback" not in caplog.text


def test_check_builders_refuses_an_unknown_dataset_and_a_duplicate() -> None:
    with pytest.raises(BuildError, match="unknown dataset 'nowhere'"):
        check_builders([mart_builder(dataset="nowhere")])
    with pytest.raises(BuildError, match="two builders make table 'mart_example'"):
        check_builders([mart_builder(), mart_builder()])
