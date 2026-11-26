import datetime
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
from huggingface_hub import CommitOperationAdd

from core.cli import main
from core.fetch.lockfile import LockedFile, Lockfile
from core.publish import publisher
from core.publish.card import CC_BY_CHANGES, CardError, build_card, last_update
from core.sources.manifest import Source, load_manifest
from core.tables.writer import TableMetadata, write_table

COMMIT = "0123456789abcdef0123456789abcdef01234567"
AMECO = "ameco-net-lending"
CRPA = "stability-programme-france-2016"
PROGRAMME_DATE = datetime.date(2026, 10, 5)
DAY = datetime.date(2026, 11, 1)


class FakeApi:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.files: dict[str, bytes] = {}
        self.commits: list[str] = []

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object:
        return None

    def file_exists(self, repo_id: str, filename: str, *, repo_type: str) -> bool:
        return filename in self.files

    def hf_hub_download(self, repo_id: str, filename: str, *, repo_type: str) -> str:
        path = self.directory / filename.replace("/", "_")
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
        self.commits.append(commit_message)
        for operation in operations:
            assert isinstance(operation.path_or_fileobj, bytes)
            self.files[operation.path_in_repo] = operation.path_or_fileobj
        return None


def macro_frame(value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "year": pd.array([2020], dtype="int16"),
            "month": pd.array([None], dtype="Int8"),
            "indicator": ["net_lending"],
            "sector": pd.array([None], dtype="string"),
            "value": [value],
            "unit": ["eur"],
            "is_forecast": [False],
            "source_id": [AMECO],
        }
    )


def write_macro(
    path: Path,
    *,
    value: float = 1.0,
    build_date: datetime.date = DAY,
    sources: tuple[str, ...] = (AMECO,),
) -> Path:
    write_table(
        macro_frame(value),
        "macro_fr",
        path,
        list(sources),
        build_date=build_date,
        commit=COMMIT,
    )
    return path


def locked(day: str) -> Lockfile:
    return Lockfile({CRPA: {"pdf": LockedFile("a.pdf", 1, "0" * 64, day)}})


@pytest.fixture
def manifest() -> dict[str, Source]:
    return load_manifest()


@pytest.fixture
def lockfile() -> Lockfile:
    return locked(PROGRAMME_DATE.isoformat())


def metadata(sources: tuple[str, ...]) -> list[TableMetadata]:
    return [TableMetadata("macro_fr", sources, "2026-11-26", COMMIT)]


def test_two_publishes_in_a_row_create_one_commit(
    tmp_path: Path, manifest: dict[str, Source], lockfile: Lockfile
) -> None:
    api = FakeApi(tmp_path)
    first = write_macro(tmp_path / "a.parquet", build_date=datetime.date(2026, 11, 1))
    again = write_macro(tmp_path / "b.parquet", build_date=datetime.date(2026, 11, 2))
    assert publisher.publish(api, publisher.prepare("core", [first], manifest, lockfile))
    assert not publisher.publish(api, publisher.prepare("core", [again], manifest, lockfile))
    assert len(api.commits) == 1
    assert "data/macro_fr.parquet" in api.files


def test_changed_rows_create_a_second_commit(
    tmp_path: Path, manifest: dict[str, Source], lockfile: Lockfile
) -> None:
    api = FakeApi(tmp_path)
    first = write_macro(tmp_path / "a.parquet")
    changed = write_macro(tmp_path / "b.parquet", value=2.0)
    publisher.publish(api, publisher.prepare("core", [first], manifest, lockfile))
    publisher.publish(api, publisher.prepare("core", [changed], manifest, lockfile))
    assert len(api.commits) == 2


def test_changed_card_text_creates_a_second_commit(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    api = FakeApi(tmp_path)
    path = write_macro(tmp_path / "a.parquet", sources=(CRPA,))
    publisher.publish(api, publisher.prepare("core", [path], manifest, locked("2026-10-05")))
    publisher.publish(api, publisher.prepare("core", [path], manifest, locked("2026-11-20")))
    assert len(api.commits) == 2


def test_card_lists_inputs_producers_licences_and_build_date(
    manifest: dict[str, Source], lockfile: Lockfile
) -> None:
    card = build_card("public-money-core", metadata((AMECO, CRPA)), manifest, lockfile)
    for source_id in (AMECO, CRPA):
        source = manifest[source_id]
        assert source.id in card
        assert source.title in card
        assert source.producer in card
        assert source.licence.name in card
        assert source.licence.url in card
    assert "2026-11-26" in card
    assert "data/macro_fr.parquet" in card


def test_card_lists_only_the_inputs_of_its_tables(
    manifest: dict[str, Source], lockfile: Lockfile
) -> None:
    card = build_card("public-money-core", metadata((AMECO,)), manifest, lockfile)
    assert CRPA not in card
    assert "L322-1" not in card


def test_card_for_a_cc_by_input_says_what_was_changed(
    manifest: dict[str, Source], lockfile: Lockfile
) -> None:
    card = build_card("public-money-core", metadata((AMECO,)), manifest, lockfile)
    assert CC_BY_CHANGES in card
    assert "Credit: European Commission, DG Economic and Financial Affairs" in card
    assert "FRA.1.0.0.0.UBLGE" in card


def test_card_for_a_crpa_input_names_the_source_and_the_last_update(
    manifest: dict[str, Source], lockfile: Lockfile
) -> None:
    card = build_card("public-money-core", metadata((CRPA,)), manifest, lockfile)
    assert "articles L321-1 and L322-1" in card
    assert f"Source: {manifest[CRPA].title}, {manifest[CRPA].producer}" in card
    assert f"Date of its last update: {PROGRAMME_DATE.isoformat()}." in card
    assert CC_BY_CHANGES not in card


def test_last_update_falls_back_to_the_verified_date(manifest: dict[str, Source]) -> None:
    assert last_update(manifest[CRPA], Lockfile()) == manifest[CRPA].verified_on


def test_card_refuses_a_source_that_the_manifest_lacks(
    manifest: dict[str, Source], lockfile: Lockfile
) -> None:
    with pytest.raises(CardError, match="nope"):
        build_card("public-money-core", metadata(("nope",)), manifest, lockfile)


def test_dry_run_prints_the_files_and_uploads_nothing(
    tmp_path: Path,
    manifest: dict[str, Source],
    lockfile: Lockfile,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    path = write_macro(tmp_path / "a.parquet")
    upload = publisher.prepare("core", [path], manifest, lockfile)
    assert publisher.run("core", [path], manifest, lockfile, dry_run=True) == 0
    out = capsys.readouterr().out
    assert out.startswith("dry run: would upload to sam-bot/public-money-core")
    assert upload.content_hash in out
    for name, data in upload.files.items():
        assert f"  {name} ({len(data)} bytes)" in out


def test_dry_run_through_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    path = write_macro(tmp_path / "a.parquet")
    lock = tmp_path / "none.lock.json"
    assert main(["publish", "core", str(path), "--dry-run", "--lock", str(lock)]) == 0
    assert "data/macro_fr.parquet" in capsys.readouterr().out


def test_real_run_without_token_stops(
    tmp_path: Path,
    manifest: dict[str, Source],
    lockfile: Lockfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    path = write_macro(tmp_path / "a.parquet")
    assert publisher.run("core", [path], manifest, lockfile, dry_run=False) == 1


def test_unknown_dataset_and_duplicate_tables_are_refused(
    tmp_path: Path, manifest: dict[str, Source], lockfile: Lockfile
) -> None:
    path = write_macro(tmp_path / "a.parquet")
    with pytest.raises(publisher.PublishError, match="unknown dataset"):
        publisher.prepare("other", [path], manifest, lockfile)
    with pytest.raises(publisher.PublishError, match="same table"):
        publisher.prepare("core", [path, path], manifest, lockfile)
