import dataclasses
import datetime
from pathlib import Path

import pytest

from core.fetch.lockfile import LockedFile, Lockfile
from core.publish import publisher
from core.publish.freshness import StaleDateError, check_last_update
from core.sources.manifest import Source, load_manifest
from tests.test_publish_publisher import (
    AMECO,
    CRPA,
    LOCK,
    FakeApi,
    run_cli,
    write_commitments,
    write_macro,
)

OTHER = "f" * 64
TODAY = datetime.date(2026, 12, 1).isoformat()


@pytest.fixture
def manifest() -> dict[str, Source]:
    return load_manifest()


def relocked(lock: Lockfile, source_id: str, **changes: str) -> Lockfile:
    """Copy a lockfile and change the entry of the single file of a source."""
    entries = {key: dict(files) for key, files in lock.entries.items()}
    (key,) = entries[source_id]
    entries[source_id][key] = dataclasses.replace(entries[source_id][key], **changes)
    return Lockfile(entries)


def run_with_fake_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, path: Path, lock: Lockfile, manifest: object
) -> tuple[FakeApi, int | None]:
    api = FakeApi(tmp_path, {})
    monkeypatch.setenv("HF_TOKEN", "test-value")
    monkeypatch.setattr(publisher, "HfApi", lambda: api)
    return api, publisher.run("core", [path], manifest, lock, dry_run=False)  # type: ignore[arg-type]


def test_changed_remote_file_stops_the_publish_and_the_dry_run(
    tmp_path: Path, manifest: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_macro(tmp_path / "a.parquet")
    lock = relocked(LOCK, AMECO, sha256=OTHER)
    url = manifest[AMECO].last_update.url  # type: ignore[union-attr]
    for dry_run in (True, False):
        with pytest.raises(StaleDateError) as raised:
            publisher.run("core", [path], manifest, lock, dry_run=dry_run)
        message = str(raised.value)
        assert AMECO in message
        assert "AMECO16.TXT" in message
        assert url in message
    api = FakeApi(tmp_path, {})
    monkeypatch.setenv("HF_TOKEN", "test-value")
    monkeypatch.setattr(publisher, "HfApi", lambda: api)
    with pytest.raises(StaleDateError):
        publisher.run("core", [path], manifest, lock, dry_run=False)
    assert api.commits == []


def test_changed_manual_file_stops_the_publish(
    tmp_path: Path, manifest: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = manifest[CRPA]
    changed = dataclasses.replace(source, access={**source.access, "sha256": OTHER})
    path = write_commitments(tmp_path / "b.parquet")
    api = FakeApi(tmp_path, {})
    monkeypatch.setenv("HF_TOKEN", "test-value")
    monkeypatch.setattr(publisher, "HfApi", lambda: api)
    with pytest.raises(StaleDateError, match=rf"{CRPA}.*\.pdf.*{source.last_update.url[:30]}"):  # type: ignore[union-attr]
        publisher.run("core", [path], {**manifest, CRPA: changed}, LOCK, dry_run=False)
    assert api.commits == []


def test_first_fetch_and_an_old_date_do_not_stop_the_publish(
    tmp_path: Path, manifest: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = manifest[AMECO]
    assert source.last_update is not None
    old = dataclasses.replace(
        source, last_update=dataclasses.replace(source.last_update, date=datetime.date(2016, 4, 1))
    )
    lock = relocked(LOCK, AMECO, retrieved_on=TODAY)
    path = write_macro(tmp_path / "a.parquet")
    api, code = run_with_fake_client(monkeypatch, tmp_path, path, lock, {**manifest, AMECO: old})
    assert code == 0
    assert len(api.commits) == 1


def test_manifest_entries_on_main_pass_with_the_lockfile_on_main(
    manifest: dict[str, Source],
) -> None:
    check_last_update(manifest, manifest, LOCK)


def test_new_and_gone_files_stop_and_a_missing_entry_is_skipped(
    manifest: dict[str, Source], caplog: pytest.LogCaptureFixture
) -> None:
    entries = {key: dict(files) for key, files in LOCK.entries.items()}
    entries[AMECO]["EXTRA.TXT"] = LockedFile("EXTRA.TXT", 1, OTHER, TODAY)
    del entries["plrg-2024-execution"]["BACEA-Bilan-2024.csv"]
    with pytest.raises(StaleDateError) as raised:
        check_last_update([AMECO, "plrg-2024-execution"], manifest, Lockfile(entries))
    assert "new: EXTRA.TXT" in str(raised.value)
    assert "gone: BACEA-Bilan-2024.csv" in str(raised.value)
    check_last_update([AMECO], manifest, Lockfile())
    assert "not in the lockfile" in caplog.text


def test_cli_stops_with_code_2_and_needs_the_lockfile(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = write_macro(tmp_path / "a.parquet")
    stale = tmp_path / "stale.lock.json"
    stale.write_text(relocked(LOCK, AMECO, sha256=OTHER).dumps(), encoding="utf-8")
    assert run_cli(tmp_path, [path], "--dry-run", "--lock", str(stale)) == 2
    assert "Read the date again at" in caplog.text
    missing = tmp_path / "none.json"
    assert run_cli(tmp_path, [path], "--dry-run", "--lock", str(missing)) == 2
    assert "no lockfile" in caplog.text
