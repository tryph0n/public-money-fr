import datetime
import re
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
    "last_update": {
        "date": datetime.date(2026, 10, 2),
        "url": "https://data.example.org/api/demo",
        "where": "Field modified of the dataset",
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


def test_last_update_loads_and_may_be_empty(tmp_path: Path) -> None:
    last_update = load_source(write(tmp_path)).last_update
    assert last_update is not None
    assert last_update.date == datetime.date(2026, 10, 2)
    assert last_update.url == "https://data.example.org/api/demo"
    assert last_update.where == "Field modified of the dataset"
    assert last_update.read_on == datetime.date(2026, 11, 26)
    assert load_source(write(tmp_path, last_update=None)).last_update is None


def test_last_update_is_a_required_key(tmp_path: Path) -> None:
    data = {key: value for key, value in VALID.items() if key != "last_update"}
    path = tmp_path / "demo.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ManifestError, match=r"^demo\.yaml: last_update: missing"):
        load_source(path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"where": ""}, r"^demo\.yaml: last_update\.where"),
        ({"url": None}, r"^demo\.yaml: last_update\.url"),
        ({"date": "soon"}, r"^demo\.yaml: last_update\.date: must be a date"),
        ({"other": 1}, r"^demo\.yaml: last_update\.other: unknown field"),
        (
            {"date": datetime.date(2026, 11, 20), "read_on": datetime.date(2026, 11, 19)},
            r"^demo\.yaml: last_update\.date: must not be after its read_on date",
        ),
    ],
)
def test_invalid_last_update_names_the_field(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    last_update = {**VALID["last_update"], **changes}  # type: ignore[dict-item]
    with pytest.raises(ManifestError, match=message):
        load_source(write(tmp_path, last_update=last_update))


def test_last_update_missing_key_is_named(tmp_path: Path) -> None:
    last_update = {**VALID["last_update"]}  # type: ignore[dict-item]
    del last_update["read_on"]
    with pytest.raises(ManifestError, match=r"^demo\.yaml: last_update\.read_on: missing"):
        load_source(write(tmp_path, last_update=last_update))


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


@pytest.mark.parametrize(
    "name", ["NotSpecified", "notspecified ", " NOTSPECIFIED", "NOTSPECIFIED\t"]
)
def test_no_declared_licence_name_is_normalised(tmp_path: Path, name: str) -> None:
    with pytest.raises(ManifestError, match=r"^demo\.yaml: licence\.basis: missing"):
        load_source(write(tmp_path, licence={**NO_LICENCE, "name": name}))


def test_duplicate_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(yaml.safe_dump(VALID) + "title: Other\n", encoding="utf-8")
    with pytest.raises(ManifestError, match=r"^demo\.yaml: not valid YAML.*duplicate key 'title'"):
        load_source(path)


def test_duplicate_key_in_a_nested_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "demo.yaml"
    text = yaml.safe_dump(VALID).replace("  last: 2019\n", "  last: 2019\n  last: 2020\n")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ManifestError, match=r"duplicate key 'last'"):
        load_source(path)


def test_future_dates_are_refused(tmp_path: Path) -> None:
    future = datetime.date.today() + datetime.timedelta(days=1)
    with pytest.raises(ManifestError, match=r"^demo\.yaml: verified_on: must not be in the future"):
        load_source(write(tmp_path, verified_on=future))
    with pytest.raises(
        ManifestError, match=r"^demo\.yaml: licence\.read_on: must not be in the future"
    ):
        load_source(write(tmp_path, licence={**VALID["licence"], "read_on": future}))  # type: ignore[dict-item]


def test_today_is_accepted(tmp_path: Path) -> None:
    load_source(write(tmp_path, verified_on=datetime.date.today()))


def test_archive_access_needs_its_keys(tmp_path: Path) -> None:
    access = {"kind": "archive", "download_url": "https://x/a.zip", "member": "A.TXT"}
    with pytest.raises(ManifestError, match=r"^demo\.yaml: access\.series: missing"):
        load_source(write(tmp_path, access=access))
    source = load_source(write(tmp_path, access={**access, "series": ["S1"]}))
    assert source.access["series"] == ["S1"]


def test_shipped_ameco_is_read_from_the_commission() -> None:
    source = load_manifest(MANIFEST_DIR)["ameco-net-lending"]
    assert source.access["kind"] == "archive"
    assert source.access["download_url"].startswith("https://ec.europa.eu/")
    assert "dbnomics" not in source.access["download_url"].lower()
    assert [code.split(".")[-1] for code in source.access["series"]] == ["UBLGE"] * 3


def test_shipped_stability_programme_has_no_declared_licence() -> None:
    licence = load_manifest(MANIFEST_DIR)["stability-programme-france-2016"].licence
    assert licence.name == "notspecified"
    assert licence.basis is not None
    assert "L321-1" in licence.basis
    assert "L322-1" in licence.basis
    assert licence.decision is not None
    assert licence.decision.startswith("D30")


def test_shipped_text_makes_no_absolute_gzip_claim() -> None:
    source = load_manifest(MANIFEST_DIR)["plrg-2024-execution"]
    assert "each served gzip" not in source.format
    assert "only when the client sends Accept-Encoding gzip" in source.format
    assert re.search(r"asks for gzip", " ".join(source.traps))


def test_load_manifest_names_the_failing_file(tmp_path: Path) -> None:
    write(tmp_path)
    (tmp_path / "bad.yaml").write_text("id: bad\n", encoding="utf-8")
    with pytest.raises(ManifestError, match=r"^bad\.yaml: "):
        load_manifest(tmp_path)


def test_shipped_manifest_has_the_five_entries() -> None:
    sources = load_manifest(MANIFEST_DIR)
    kinds = {source.access["kind"] for source in sources.values()}
    assert kinds == {"records", "attachments", "data_gouv", "archive", "manual"}
    assert len(sources) == 5
    for source in sources.values():
        assert source.licence.url.startswith("https://")
        assert source.licence.read_on == datetime.date(2026, 11, 26)


def test_shipped_last_update_dates_are_the_producer_dates() -> None:
    sources = load_manifest(MANIFEST_DIR)
    expected = {
        "ameco-net-lending": (datetime.date(2026, 11, 24), "economy-finance.ec.europa.eu"),
        "lfi-2019-voted": (datetime.date(2019, 3, 21), "data.economie.gouv.fr/api/"),
        "plrg-2024-execution": (datetime.date(2025, 4, 29), "plrg-2024/attachments"),
        "plr-2015-execution": (datetime.date(2016, 6, 6), "www.data.gouv.fr/api/1/datasets/"),
        "stability-programme-france-2016": (datetime.date(2016, 4, 13), "commission.europa.eu"),
    }
    for source_id, (date, host) in expected.items():
        last_update = sources[source_id].last_update
        assert last_update is not None
        assert last_update.date == date
        assert host in last_update.url
        assert last_update.read_on == datetime.date(2026, 11, 26)


def test_shipped_2015_execution_uses_the_legal_basis() -> None:
    licence = load_manifest(MANIFEST_DIR)["plr-2015-execution"].licence
    assert licence.name == "notspecified"
    assert licence.basis is not None
    assert "L321-1" in licence.basis
    assert "L322-1" in licence.basis
    assert licence.decision is not None
    assert licence.decision.startswith("D24")
