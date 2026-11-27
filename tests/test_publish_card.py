import dataclasses
from pathlib import Path

import pytest
import yaml

from core.publish import publisher
from core.publish.card import CC_BY_4_URL, CardError, build_card
from core.sources.manifest import Source, load_manifest
from core.tables.writer import TableMetadata
from tests.test_publish_publisher import (
    AMECO,
    COMMIT,
    CRPA,
    LFI,
    NOTE,
    write_commitments,
    write_macro,
)


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
    undated = {**manifest, AMECO: dataclasses.replace(manifest[AMECO], last_update=None)}
    with pytest.raises(CardError, match=rf"no date of last update.*: {AMECO}$"):
        build_card("public-money-core", metadata((AMECO,)), undated)


def test_card_gives_the_attachment_date_of_the_plrg_input(manifest: dict[str, Source]) -> None:
    card = build_card("public-money-core", metadata(("plrg-2024-execution",)), manifest)
    assert "[2025-04-29](https://data.economie.gouv.fr/api/explore/v2.1/" in card
    assert "2024-04-17" not in card


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


PLR2015 = "plr-2015-execution"


@pytest.mark.parametrize(
    ("source_id", "page"),
    [
        (AMECO, "https://ec.europa.eu/economy_finance/db_indicators/ameco/documents/ameco16.zip"),
        (
            CRPA,
            "https://commission.europa.eu/publications/2016-european-semester-national-plans-france_en",
        ),
        (
            LFI,
            "https://data.economie.gouv.fr/explore/dataset/loi-de-finances-initiale-pour-2019-lfi-2019-1/",
        ),
        (PLR2015, "https://www.data.gouv.fr/datasets/57559e6c88ee382aa2640390/"),
    ],
)
def test_input_row_links_the_page_of_the_source_and_the_licence(
    manifest: dict[str, Source], source_id: str, page: str
) -> None:
    source = manifest[source_id]
    card = build_card("public-money-core", metadata((source_id,)), manifest)
    row = next(
        line for line in card.splitlines() if line.startswith("| [") and f"({source_id}) |" in line
    )
    assert row.startswith(f"| [{source.title}]({page}) ({source_id}) | ")
    assert f"]({source.licence.url}) | [" in row
