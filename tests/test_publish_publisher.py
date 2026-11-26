import dataclasses
import datetime
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest
import yaml
from huggingface_hub import CommitOperationAdd, CommitOperationDelete

from core.cli import main
from core.publish import publisher
from core.publish.card import CC_BY_4_URL, CardError, build_card
from core.sources.manifest import Source, load_manifest
from core.tables.writer import TableMetadata, write_table
from tests.test_tables import good_frames

COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
AMECO = "ameco-net-lending"
CRPA = "stability-programme-france-2016"
LFI = "lfi-2019-voted"
UNDATED = "plrg-2024-execution"
NOTE = "Kept the series FRA.1.0.99.0.UBLGE and wrote one row per year."
DAY = datetime.date(2026, 11, 1)


class FakeApi:
    def __init__(self, directory: Path, files: dict[str, bytes] | None = None) -> None:
        self.directory = directory
        self.files: dict[str, bytes] = dict(files or {})
        self.commits: list[str] = []

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object:
        assert repo_type == "dataset"
        assert exist_ok is True
        return None

    def repo_exists(self, repo_id: str, *, repo_type: str) -> bool:
        return bool(self.files)

    def list_repo_files(self, repo_id: str, *, repo_type: str) -> list[str]:
        return sorted(self.files)

    def hf_hub_download(self, repo_id: str, filename: str, *, repo_type: str) -> str:
        path = self.directory / filename.replace("/", "_")
        path.write_bytes(self.files[filename])
        return str(path)

    def create_commit(
        self,
        repo_id: str,
        operations: Sequence[CommitOperationAdd | CommitOperationDelete],
        *,
        commit_message: str,
        repo_type: str,
    ) -> object:
        self.commits.append(commit_message)
        for operation in operations:
            if isinstance(operation, CommitOperationDelete):
                del self.files[operation.path_in_repo]
            else:
                assert isinstance(operation.path_or_fileobj, bytes)
                self.files[operation.path_in_repo] = operation.path_or_fileobj
        return None


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


def metadata(
    sources: tuple[str, ...], changes: dict[str, str] | None = None
) -> list[TableMetadata]:
    notes = {AMECO: NOTE} if changes is None and AMECO in sources else changes or {}
    return [TableMetadata("macro_fr", sources, "2026-11-26", COMMIT, notes)]


def front_matter(card: str) -> dict[str, object]:
    head, _, _ = card.removeprefix("---\n").partition("---\n")
    data = yaml.safe_load(head)
    assert isinstance(data, dict)
    return data


def test_two_publishes_in_a_row_create_one_commit(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    api = FakeApi(tmp_path)
    first = write_macro(tmp_path / "a.parquet", build_date=DAY, commit=COMMIT)
    again = write_macro(
        tmp_path / "b.parquet", build_date=datetime.date(2026, 11, 2), commit=OTHER_COMMIT
    )
    assert publisher.publish(api, publisher.prepare("core", [first], manifest))
    assert not publisher.publish(api, publisher.prepare("core", [again], manifest))
    assert api.commits == ["data: publish 1 table"]
    assert set(api.files) == {"data/macro_fr.parquet", "README.md", "content.sha256"}


def test_changed_rows_create_a_second_commit(tmp_path: Path, manifest: dict[str, Source]) -> None:
    api = FakeApi(tmp_path)
    first = write_macro(tmp_path / "a.parquet")
    changed = write_macro(tmp_path / "b.parquet", value=3.0)
    publisher.publish(api, publisher.prepare("core", [first], manifest))
    publisher.publish(api, publisher.prepare("core", [changed], manifest))
    assert len(api.commits) == 2


def test_changed_card_text_creates_a_second_commit(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    api = FakeApi(tmp_path)
    path = write_macro(tmp_path / "a.parquet")
    noted = write_macro(tmp_path / "b.parquet", note="Kept one series only.")
    publisher.publish(api, publisher.prepare("core", [path], manifest))
    publisher.publish(api, publisher.prepare("core", [noted], manifest))
    source = manifest[AMECO]
    assert source.last_update is not None
    later = dataclasses.replace(
        source,
        last_update=dataclasses.replace(source.last_update, date=datetime.date(2026, 11, 25)),
    )
    publisher.publish(api, publisher.prepare("core", [noted], {**manifest, AMECO: later}))
    assert len(api.commits) == 3


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


def test_partial_publish_deletes_the_tables_it_does_not_hold(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    api = FakeApi(tmp_path, {".gitattributes": b"*.parquet filter=lfs\n"})
    macro = write_macro(tmp_path / "a.parquet")
    commitments = write_commitments(tmp_path / "b.parquet")
    publisher.publish(api, publisher.prepare("core", [macro, commitments], manifest))
    assert "data/fiscal_commitments.parquet" in api.files
    assert publisher.publish(api, publisher.prepare("core", [macro], manifest))
    assert api.commits[-1] == "data: publish 1 table, delete 1 stale file"
    assert set(api.files) == {
        ".gitattributes",
        "README.md",
        "content.sha256",
        "data/macro_fr.parquet",
    }
    card = api.files["README.md"].decode()
    for path in api.files:
        if path.endswith(".parquet"):
            assert f"| {path} |" in card


def test_a_stale_file_alone_creates_a_commit(tmp_path: Path, manifest: dict[str, Source]) -> None:
    api = FakeApi(tmp_path)
    upload = publisher.prepare("core", [write_macro(tmp_path / "a.parquet")], manifest)
    publisher.publish(api, upload)
    api.files["_ci_check/test.parquet"] = b"x"
    assert publisher.publish(api, upload)
    assert "_ci_check/test.parquet" not in api.files
    assert len(api.commits) == 2


def test_card_metadata_has_the_licence_and_one_config_per_table(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    paths = [write_macro(tmp_path / "a.parquet"), write_commitments(tmp_path / "b.parquet")]
    card = publisher.prepare("core", paths, manifest).files["README.md"].decode()
    assert front_matter(card) == {
        "license": "etalab-2.0",
        "language": ["fr"],
        "pretty_name": "public-money-core",
        "configs": [
            {"config_name": "fiscal_commitments", "data_files": "data/fiscal_commitments.parquet"},
            {"config_name": "macro_fr", "data_files": "data/macro_fr.parquet"},
        ],
    }
    assert card.count("---\n") == 2


def test_card_lists_inputs_producers_licences_and_build_date(manifest: dict[str, Source]) -> None:
    card = build_card("public-money-core", metadata((AMECO, CRPA, LFI)), manifest)
    for source_id in (AMECO, CRPA, LFI):
        source = manifest[source_id]
        assert source.id in card
        assert source.title in card
        assert source.producer in card
        assert source.licence.url in card
    assert "Creative Commons Attribution 4.0 International (CC BY 4.0)" in card
    assert "Licence Ouverte (Etalab)" in card
    assert "2026-11-26" in card
    assert "| macro_fr | data/macro_fr.parquet | 2026-11-26 |" in card


def test_card_gives_the_last_update_that_the_producer_states(
    manifest: dict[str, Source],
) -> None:
    card = build_card("public-money-core", metadata((AMECO, CRPA, LFI)), manifest)
    for source_id in (AMECO, CRPA, LFI):
        last_update = manifest[source_id].last_update
        assert last_update is not None
        assert f"| [{last_update.date.isoformat()}]({last_update.url}) |" in card
    assert "| [2019-03-21](https://data.economie.gouv.fr/api/explore/v2.1/" in card
    assert "Date of its last update: 2016-04-13, as stated at" in card
    assert "Date of its last update: 2026-11-26" not in card


def test_card_refuses_an_input_with_no_date_of_last_update(manifest: dict[str, Source]) -> None:
    with pytest.raises(CardError, match=rf"no date of last update.*: {UNDATED}$"):
        build_card("public-money-core", metadata((UNDATED,)), manifest)


def test_card_for_a_cc_by_input_gives_the_material_and_the_builder_notes(
    manifest: dict[str, Source],
) -> None:
    card = build_card("public-money-core", metadata((AMECO,)), manifest)
    assert "Credit: European Commission, DG Economic and Financial Affairs" in card
    assert f"Material: {manifest[AMECO].title}, {manifest[AMECO].access['download_url']}." in card
    assert CC_BY_4_URL in card
    assert f"Changes made by this project:\n\n- macro_fr: {NOTE}" in card
    assert "Series kept" not in card


def test_card_refuses_a_cc_by_input_without_a_change_note(manifest: dict[str, Source]) -> None:
    with pytest.raises(CardError, match=r"no change note for it: macro_fr$"):
        build_card("public-money-core", metadata((AMECO,), changes={}), manifest)


def test_card_for_an_input_with_no_licence_gives_its_basis_source_and_date(
    manifest: dict[str, Source],
) -> None:
    source = manifest[CRPA]
    card = build_card("public-money-core", metadata((CRPA,)), manifest)
    assert "Basis of the reuse: Articles L321-1 and L322-1" in card
    assert f"Source: {source.title}, {source.producer}; {source.access['page_url']}" in card
    assert "No licence declared" in card
    assert "notspecified" not in card
    assert "Changes made by this project" not in card
    licence = dataclasses.replace(source.licence, basis="Article L321-2 only.")
    changed = {**manifest, CRPA: dataclasses.replace(source, licence=licence)}
    card = build_card("public-money-core", metadata((CRPA,)), changed)
    assert "Basis of the reuse: Article L321-2 only." in card


def test_card_lists_only_the_inputs_of_its_tables(manifest: dict[str, Source]) -> None:
    card = build_card("public-money-core", metadata((AMECO,)), manifest)
    assert CRPA not in card
    assert "L322-1" not in card


def test_card_refuses_a_source_that_the_manifest_lacks(manifest: dict[str, Source]) -> None:
    with pytest.raises(CardError, match="nope"):
        build_card("public-money-core", metadata(("nope",)), manifest)


def test_dry_run_prints_files_deletions_and_card_and_writes_nothing(
    tmp_path: Path,
    manifest: dict[str, Source],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    api = FakeApi(tmp_path, {".gitattributes": b"", "data/old.parquet": b"x"})
    built: list[object] = []

    def reader(**kwargs: object) -> FakeApi:
        built.append(kwargs)
        return api

    monkeypatch.setattr(publisher, "HfApi", reader)
    path = write_macro(tmp_path / "a.parquet")
    upload = publisher.prepare("core", [path], manifest)
    assert publisher.run("core", [path], manifest, dry_run=True) == 0
    out = capsys.readouterr().out
    assert built == [{"token": False}]
    assert out.startswith("dry run: would upload to sam-bot/public-money-core")
    assert upload.content_hash in out
    for name, data in upload.files.items():
        assert f"  {name} ({len(data)} bytes)" in out
    assert "would delete 1 file:\n  data/old.parquet\n" in out
    assert upload.files["README.md"].decode() in out
    assert api.commits == []


def test_dry_run_through_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(publisher, "HfApi", lambda **kwargs: FakeApi(tmp_path))
    path = write_macro(tmp_path / "a.parquet")
    assert main(["publish", "core", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "data/macro_fr.parquet" in out
    assert "would delete 0 files" in out


def test_real_run_without_token_builds_no_client(
    tmp_path: Path, manifest: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(**kwargs: object) -> FakeApi:
        raise AssertionError("a Hub client was built")

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(publisher, "HfApi", refuse)
    path = write_macro(tmp_path / "a.parquet")
    assert publisher.run("core", [path], manifest, dry_run=False) == 1


def test_real_run_with_a_token_publishes_through_the_client(
    tmp_path: Path, manifest: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeApi(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "test-value")
    monkeypatch.setattr(publisher, "HfApi", lambda **kwargs: api)
    path = write_macro(tmp_path / "a.parquet")
    assert publisher.run("core", [path], manifest, dry_run=False) == 0
    assert api.commits == ["data: publish 1 table"]


def test_two_tables_make_a_plural_commit_message(
    tmp_path: Path, manifest: dict[str, Source]
) -> None:
    api = FakeApi(tmp_path)
    paths = [write_macro(tmp_path / "a.parquet"), write_commitments(tmp_path / "b.parquet")]
    publisher.publish(api, publisher.prepare("core", paths, manifest))
    assert api.commits == ["data: publish 2 tables"]


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
