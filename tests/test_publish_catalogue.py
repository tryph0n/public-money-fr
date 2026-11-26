import shutil
from pathlib import Path

import pytest

from core.publish.catalogue import TABLE_FILE, render_page, write_catalogue
from core.sources.manifest import MANIFEST_DIR, ManifestError, load_manifest


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    target = tmp_path / "manifest"
    target.mkdir()
    for path in MANIFEST_DIR.glob("*.yaml"):
        shutil.copy(path, target / path.name)
    return target


def read_pages(folder: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(folder.glob("*.md"))}


def test_one_page_per_entry_and_a_table(manifest_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    write_catalogue(out, manifest_dir)
    sources = load_manifest(manifest_dir)
    assert set(read_pages(out)) == {f"{source_id}.md" for source_id in sources} | {TABLE_FILE}
    table = (out / TABLE_FILE).read_text(encoding="utf-8")
    for source in sources.values():
        row = next(line for line in table.splitlines() if f"[{source.id}]" in line)
        for cell in (source.producer, source.licence.name, source.status):
            assert cell.replace("_", r"\_") in row or cell in row
        assert str(source.first_year) in row


def test_adding_and_removing_an_entry_adds_and_removes_a_page(
    manifest_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    write_catalogue(out, manifest_dir)
    before = read_pages(out)

    template = (manifest_dir / "ameco-net-lending.yaml").read_text(encoding="utf-8")
    extra = manifest_dir / "extra-source.yaml"
    extra.write_text(template.replace("ameco-net-lending", "extra-source"), encoding="utf-8")
    write_catalogue(out, manifest_dir)
    during = read_pages(out)
    assert set(during) - set(before) == {"extra-source.md"}
    assert "extra-source" in during[TABLE_FILE]
    for name, text in before.items():
        if name != TABLE_FILE:
            assert during[name] == text

    extra.unlink()
    write_catalogue(out, manifest_dir)
    assert read_pages(out) == before


def test_entry_without_licence_fails_and_writes_nothing(manifest_dir: Path, tmp_path: Path) -> None:
    path = manifest_dir / "ameco-net-lending.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index("licence:")
    end = next(i for i in range(start + 1, len(lines)) if not lines[i].startswith(" "))
    path.write_text("\n".join(lines[:start] + lines[end:]) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(ManifestError, match=r"ameco-net-lending\.yaml: licence: missing"):
        write_catalogue(out, manifest_dir)
    assert not out.exists()


def test_each_trap_is_a_warning_block() -> None:
    for source in load_manifest().values():
        page = render_page(source)
        assert page.count(":::{warning}") == len(source.traps)
        for trap in source.traps:
            assert f":::{{warning}}\n{trap}\n:::" in page.replace("\\", "")


def test_markup_in_a_value_is_escaped() -> None:
    source = next(iter(load_manifest().values()))
    changed = type(source)(**{**source.__dict__, "title": "a *b* | c_d"})
    assert r"a \*b\* \| c\_d" in render_page(changed)
