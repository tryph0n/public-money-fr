import dataclasses
import datetime
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import pyarrow.parquet as pq
import pytest
from huggingface_hub import CommitOperationAdd

from core.cli import main
from core.publish import publisher
from core.sources.manifest import Source, load_manifest
from core.tables.writer import write_table
from tests.test_tables import good_frames

COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
AMECO = "ameco-net-lending"
CRPA = "stability-programme-france-2016"
LFI = "lfi-2019-voted"
NOTE = "Kept the series FRA.1.0.99.0.UBLGE and wrote one row per year."
DAY = datetime.date(2026, 11, 1)


def macro_frame(value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "year": pd.array([2020, 2021], dtype="int16"),
            "month": pd.array([None, None], dtype="Int8"),
            "indicator": ["net_lending", "net_lending"],
            "sector": pd.array([None, None], dtype="string"),
            "value": [value, 2.0],
            "unit": ["eur", "eur"],
            "is_forecast": [False, False],
            "source_id": [AMECO, AMECO],
        }
    )


def write_macro(
    path: Path,
    *,
    value: float = 1.0,
    build_date: datetime.date = DAY,
    commit: str = COMMIT,
    sources: tuple[str, ...] = (AMECO,),
    note: str = NOTE,
) -> Path:
    write_table(
        macro_frame(value),
        "macro_fr",
        path,
        list(sources),
        changes={AMECO: note} if AMECO in sources else None,
        build_date=build_date,
        commit=commit,
    )
    return path


def write_commitments(path: Path) -> Path:
    frame = good_frames()["fiscal_commitments"].assign(source_id=CRPA)
    write_table(frame, "fiscal_commitments", path, [CRPA], build_date=DAY, commit=COMMIT)
    return path


@pytest.fixture
def manifest() -> dict[str, Source]:
    return load_manifest()


class FakeApi:
    """Returns stored values and records the calls."""

    def __init__(self, directory: Path, files: dict[str, bytes]) -> None:
        self.directory = directory
        self.files = files
        self.commits: list[tuple[list[str], str]] = []

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object:
        return None

    def list_repo_files(self, repo_id: str, *, repo_type: str) -> list[str]:
        return sorted(self.files)

    def hf_hub_download(self, repo_id: str, filename: str, *, repo_type: str) -> str:
        path = self.directory / "stored"
        path.write_bytes(self.files[filename])
        return str(path)

    def create_commit(
        self,
        repo_id: str,
        operations: Sequence[CommitOperationAdd],
        *,
        commit_message: str,
        repo_type: str,
    ) -> object:
        self.commits.append(([operation.path_in_repo for operation in operations], commit_message))
        return None


def upload_of(tmp_path: Path, manifest: dict[str, Source], *names: str) -> publisher.Upload:
    paths = [write_macro(tmp_path / "a.parquet")]
    if "commitments" in names:
        paths.append(write_commitments(tmp_path / "b.parquet"))
    return publisher.prepare("core", paths, manifest)


def test_rebuild_with_other_dates_and_commit_gives_the_same_hash(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    first = write_macro(tmp_path / "a.parquet", build_date=DAY, commit=COMMIT)
    again = write_macro(
        tmp_path / "b.parquet", build_date=datetime.date(2026, 11, 2), commit=OTHER_COMMIT
    )
    one = publisher.prepare("core", [first], manifest)
    two = publisher.prepare("core", [again], manifest)
    assert one.content_hash == two.content_hash
    assert one.files["README.md"] != two.files["README.md"]


def test_changed_rows_change_the_hash(tmp_path: Path, manifest: dict[str, Source]) -> None:
    first = publisher.prepare("core", [write_macro(tmp_path / "a.parquet")], manifest)
    changed = publisher.prepare("core", [write_macro(tmp_path / "b.parquet", value=3.0)], manifest)
    assert first.content_hash != changed.content_hash


def test_changed_card_text_changes_the_hash(tmp_path: Path, manifest: dict[str, Source]) -> None:
    path = write_macro(tmp_path / "a.parquet")
    noted = write_macro(tmp_path / "b.parquet", note="Kept one series only.")
    base = publisher.prepare("core", [path], manifest).content_hash
    assert publisher.prepare("core", [noted], manifest).content_hash != base
    source = manifest[AMECO]
    assert source.last_update is not None
    later = dataclasses.replace(
        source,
        last_update=dataclasses.replace(source.last_update, date=datetime.date(2026, 11, 25)),
    )
    dated = publisher.prepare("core", [path], {**manifest, AMECO: later}).content_hash
    assert dated != base


def test_row_groups_do_not_change_the_content_hash(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    path = write_macro(tmp_path / "a.parquet")
    split = tmp_path / "b.parquet"
    pq.write_table(pq.read_table(path), split, row_group_size=1)
    assert pq.ParquetFile(split).num_row_groups == 2
    first = publisher.prepare("core", [path], manifest)
    second = publisher.prepare("core", [split], manifest)
    assert first.content_hash == second.content_hash


def test_plan_adds_every_file_and_counts_the_tables(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    upload = upload_of(tmp_path, manifest, "commitments")
    plan = publisher.plan_commit([], None, upload)
    assert plan is not None
    assert all(isinstance(operation, CommitOperationAdd) for operation in plan.operations)
    assert [operation.path_in_repo for operation in plan.operations] == sorted(upload.files)
    assert plan.message == "data: publish 2 tables"
    one = publisher.plan_commit([], None, upload_of(tmp_path, manifest))
    assert one is not None
    assert one.message == "data: publish 1 table"


def test_plan_is_none_when_the_stored_hash_is_the_new_hash(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    upload = upload_of(tmp_path, manifest)
    present = ["README.md", "content.sha256", "data/macro_fr.parquet"]
    assert publisher.plan_commit(present, upload.content_hash, upload) is None
    assert publisher.plan_commit(present, "0" * 64, upload) is not None


def test_plan_refuses_a_table_file_that_the_upload_does_not_hold(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    upload = upload_of(tmp_path, manifest)
    present = ["data/old_b.parquet", "data/macro_fr.parquet", "data/old_a.parquet"]
    with pytest.raises(publisher.PublishError) as error:
        publisher.plan_commit(present, None, upload)
    assert "data/old_a.parquet, data/old_b.parquet" in str(error.value)
    assert "macro_fr" not in str(error.value)


def test_plan_refuses_even_when_the_stored_hash_is_the_new_hash(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    upload = upload_of(tmp_path, manifest)
    with pytest.raises(publisher.PublishError):
        publisher.plan_commit(["data/old.parquet"], upload.content_hash, upload)


def test_plan_keeps_the_other_files_without_blocking(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    upload = upload_of(tmp_path, manifest)
    present = [
        ".gitattributes",
        "notes.parquet",
        "extra/x.parquet",
        "data/notes.txt",
        "data/sub/y.parquet",
    ]
    plan = publisher.plan_commit(present, None, upload)
    assert plan is not None
    assert {operation.path_in_repo for operation in plan.operations} == set(upload.files)


def test_publish_commits_the_plan_through_the_client(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    api = FakeApi(tmp_path, {".gitattributes": b""})
    upload = upload_of(tmp_path, manifest)
    assert publisher.publish(api, upload)
    assert api.commits == [(sorted(upload.files), "data: publish 1 table")]


def test_publish_stops_before_any_commit_when_a_table_would_be_dropped(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    api = FakeApi(tmp_path, {"data/old.parquet": b"x"})
    with pytest.raises(publisher.PublishError, match=r"data/old\.parquet"):
        publisher.publish(api, upload_of(tmp_path, manifest))
    assert api.commits == []


def test_dry_run_prints_files_and_card_and_makes_no_network_call(
    tmp_path: Path,
    manifest: dict[str, Source],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(**kwargs: object) -> object:
        raise AssertionError("a Hub client was built")

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(publisher, "HfApi", refuse)
    path = write_macro(tmp_path / "a.parquet")
    upload = publisher.prepare("core", [path], manifest)
    assert main(["publish", "core", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("dry run: would upload to sam-bot/public-money-core")
    assert upload.content_hash in out
    for name, data in upload.files.items():
        assert f"  {name} ({len(data)} bytes)" in out
    assert upload.files["README.md"].decode() in out
    assert "delete" not in out.split("README.md:")[0]


def test_real_run_without_token_builds_no_client(
    tmp_path: Path, manifest: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(**kwargs: object) -> object:
        raise AssertionError("a Hub client was built")

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(publisher, "HfApi", refuse)
    path = write_macro(tmp_path / "a.parquet")
    assert publisher.run("core", [path], manifest, dry_run=False) == 1


def test_a_project_table_is_published_next_to_a_shared_table(
    tmp_path: Path,
    manifest: dict[str, Source],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = pa.DataFrameSchema(
        {
            "year": pa.Column("int16", description="Year."),
            "source_id": pa.Column("string", description="Source id."),
        },
        strict=True,
        name="mart_example",
    )
    frame = pd.DataFrame({"year": pd.array([2020], dtype="int16"), "source_id": [AMECO]})
    mart = tmp_path / "mart.parquet"
    write_table(
        frame,
        "mart_example",
        mart,
        [AMECO],
        changes={AMECO: NOTE},
        schema=schema,
        key=("year",),
        build_date=DAY,
        commit=COMMIT,
    )
    macro = write_macro(tmp_path / "macro.parquet")
    upload = publisher.prepare("core", [mart, macro], manifest)
    assert "data/mart_example.parquet" in upload.files
    assert "data/macro_fr.parquet" in upload.files
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert main(["publish", "core", str(mart), str(macro), "--dry-run"]) == 0
    assert "  data/mart_example.parquet (" in capsys.readouterr().out


def test_a_network_error_is_not_wrapped(
    tmp_path: Path, manifest: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Unreachable:
        def create_repo(self, *args: object, **kwargs: object) -> object:
            raise ConnectionError("no route")

    monkeypatch.setenv("HF_TOKEN", "test-value")
    monkeypatch.setattr(publisher, "HfApi", Unreachable)
    path = write_macro(tmp_path / "a.parquet")
    with pytest.raises(ConnectionError, match="no route"):
        main(["publish", "core", str(path)])


def test_missing_file_is_refused_with_its_path(
    tmp_path: Path, manifest: dict[str, Source], caplog: pytest.LogCaptureFixture
) -> None:
    missing = tmp_path / "none.parquet"
    with pytest.raises(publisher.PublishError, match=r"no such file: .*none\.parquet"):
        publisher.prepare("core", [missing], manifest)
    assert main(["publish", "core", str(missing), "--dry-run"]) == 2
    assert "no such file" in caplog.text


def test_unknown_dataset_and_duplicate_tables_are_refused(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    path = write_macro(tmp_path / "a.parquet")
    with pytest.raises(publisher.PublishError, match="unknown dataset"):
        publisher.prepare("other", [path], manifest)
    with pytest.raises(publisher.PublishError, match="same table"):
        publisher.prepare("core", [path, path], manifest)
