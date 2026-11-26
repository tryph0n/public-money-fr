import datetime
from pathlib import Path

import pytest
import yaml

from core.sources.manifest import MANIFEST_DIR, ManifestError, load_manifest, load_source

VALID = {
    "id": "demo",
    "title": "Demo",
    "producer": "Someone",
    "access": {"kind": "records", "portal": "data.example.org", "dataset_id": "demo-set"},
    "licence": {
        "name": "Licence Ouverte v2.0 (Etalab)",
        "url": "https://data.example.org/demo",
        "read_on": datetime.date(2026, 11, 26),
    },
    "grain": "One row per programme",
    "years": {"first": 2019, "last": 2019},
    "format": "CSV",
    "encoding": "UTF-8",
    "generation": "G3",
    "traps": ["A trap"],
    "status": "verified",
    "verified_on": datetime.date(2026, 11, 26),
}

NO_LICENCE = {
    "name": "notspecified",
    "url": "https://www.data.gouv.fr/datasets/57559e6c88ee382aa2640390/",
    "read_on": datetime.date(2026, 11, 26),
}


def write(tmp_path: Path, **changes: object) -> Path:
    data = {**VALID, **changes}
    path = tmp_path / "demo.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_valid_file_loads(tmp_path: Path) -> None:
    source = load_source(write(tmp_path))
    assert source.id == "demo"
    assert (source.first_year, source.last_year) == (2019, 2019)
    assert source.licence.read_on == datetime.date(2026, 11, 26)


def test_invalid_yaml_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("id: [unclosed", encoding="utf-8")
    with pytest.raises(ManifestError, match=r"^broken\.yaml: not valid YAML"):
        load_source(path)


def test_missing_field_names_file_and_field(tmp_path: Path) -> None:
    path = write(tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["producer"]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ManifestError, match=r"^demo\.yaml: producer: missing"):
        load_source(path)


def test_unknown_field_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match=r"^demo\.yaml: licence_name: unknown field"):
        load_source(write(tmp_path, licence_name="x"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "other"}, r"^demo\.yaml: id: 'other' must equal the file name"),
        ({"status": "done"}, r"^demo\.yaml: status: must be one of"),
        ({"years": {"first": 2020, "last": 2019}}, r"^demo\.yaml: years\.last"),
        ({"years": {"first": "2019", "last": 2019}}, r"^demo\.yaml: years\.first"),
        ({"verified_on": "yesterday"}, r"^demo\.yaml: verified_on: must be a date"),
        ({"traps": []}, r"^demo\.yaml: traps: must be a non-empty list"),
        ({"access": {"kind": "ftp"}}, r"^demo\.yaml: access\.kind"),
        (
            {"access": {"kind": "records", "portal": "p"}},
            r"^demo\.yaml: access\.dataset_id: missing",
        ),
        (
            {"licence": {**VALID["licence"], "url": ""}},  # type: ignore[dict-item]
            r"^demo\.yaml: licence\.url",
        ),
        (
            {"licence": {"name": "x", "url": "https://x"}},
            r"^demo\.yaml: licence\.read_on: missing",
        ),
    ],
)
def test_invalid_field_fails_with_file_and_field(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ManifestError, match=message):
        load_source(write(tmp_path, **changes))


def test_no_declared_licence_needs_basis_and_decision(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match=r"^demo\.yaml: licence\.basis: missing"):
        load_source(write(tmp_path, licence=NO_LICENCE))
    with pytest.raises(ManifestError, match=r"^demo\.yaml: licence\.decision: missing"):
        load_source(write(tmp_path, licence={**NO_LICENCE, "basis": "Articles L321-1, L322-1"}))


def test_no_declared_licence_loads_with_basis_and_decision(tmp_path: Path) -> None:
    licence = {**NO_LICENCE, "basis": "Articles L321-1, L322-1", "decision": "D24"}
    source = load_source(write(tmp_path, licence=licence))
    assert source.licence.basis == "Articles L321-1, L322-1"
    assert source.licence.decision == "D24"


def test_load_manifest_names_the_failing_file(tmp_path: Path) -> None:
    write(tmp_path)
    (tmp_path / "bad.yaml").write_text("id: bad\n", encoding="utf-8")
    with pytest.raises(ManifestError, match=r"^bad\.yaml: "):
        load_manifest(tmp_path)


def test_shipped_manifest_has_the_five_entries() -> None:
    sources = load_manifest(MANIFEST_DIR)
    kinds = {source.access["kind"] for source in sources.values()}
    assert kinds == {"records", "attachments", "data_gouv", "dbnomics", "manual"}
    assert len(sources) == 5
    for source in sources.values():
        assert source.licence.url.startswith("https://")
        assert source.licence.read_on == datetime.date(2026, 11, 26)


def test_shipped_2015_execution_uses_the_legal_basis() -> None:
    licence = load_manifest(MANIFEST_DIR)["plr-2015-execution"].licence
    assert licence.name == "notspecified"
    assert licence.basis is not None
    assert "L321-1" in licence.basis
    assert "L322-1" in licence.basis
    assert licence.decision is not None
    assert licence.decision.startswith("D24")
