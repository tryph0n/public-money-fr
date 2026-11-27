from pathlib import Path

from core.fetch.lockfile import LockedFile, Lockfile
from core.fetch.pins import main, pin_problems
from core.sources.manifest import MANIFEST_DIR, load_manifest

SOURCE_ID = "ameco-net-lending"


def lock(sha: str, retrieved_on: str = "2026-11-26") -> Lockfile:
    return Lockfile({SOURCE_ID: {"a.txt": LockedFile("a.txt", 1, sha, retrieved_on)}})


def test_unchanged_lockfile_passes_even_with_another_retrieval_date() -> None:
    assert (
        pin_problems(lock("a" * 64), lock("a" * 64, "2026-12-27"), load_manifest(MANIFEST_DIR))
        == []
    )


def test_changed_checksum_names_the_source_the_file_and_the_date_page() -> None:
    manifest = load_manifest(MANIFEST_DIR)
    problems = pin_problems(lock("a" * 64), lock("b" * 64), manifest)
    assert len(problems) == 1
    assert SOURCE_ID in problems[0]
    assert "a.txt" in problems[0]
    last_update = manifest[SOURCE_ID].last_update
    assert last_update is not None
    assert last_update.url in problems[0]


def test_source_without_committed_entry_is_a_problem() -> None:
    problems = pin_problems(Lockfile(), lock("a" * 64), load_manifest(MANIFEST_DIR))
    assert len(problems) == 1
    assert SOURCE_ID in problems[0]
    assert "no entry" in problems[0]


def test_main_exit_codes(tmp_path: Path) -> None:
    (tmp_path / "old.json").write_text(lock("a" * 64).dumps(), encoding="utf-8")
    (tmp_path / "new.json").write_text(lock("b" * 64).dumps(), encoding="utf-8")
    assert main([str(tmp_path / "old.json"), str(tmp_path / "old.json")]) == 0
    assert main([str(tmp_path / "old.json"), str(tmp_path / "new.json")]) == 1
