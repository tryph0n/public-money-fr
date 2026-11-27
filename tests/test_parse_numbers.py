from decimal import Decimal
from pathlib import Path

import pytest

from core.parse.decoding import read_table
from core.parse.numbers import (
    AmountError,
    ScientificCell,
    find_scientific_cells,
    normalise_code,
    parse_amount,
)

FIXTURES = Path(__file__).parent / "fixtures" / "decoding"
RAW = Path(__file__).parent.parent / "data" / "raw"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("42 355 399", Decimal("42355399")),
        ("42 355 399", Decimal("42355399")),
        ("3397166072,6", Decimal("3397166072.6")),
        ("10690400,58", Decimal("10690400.58")),
        ("-12817067246,53", Decimal("-12817067246.53")),
        ("-4 763 863", Decimal("-4763863")),
        ("0", Decimal("0")),
        ("38958551", Decimal("38958551")),
    ],
)
def test_amount_is_parsed_exactly(text: str, expected: Decimal) -> None:
    assert parse_amount(text) == expected


def test_amounts_of_real_files_are_parsed() -> None:
    voted_2018 = read_table(FIXTURES / "LFI_2018_ACT_CAT_TIT_BG_CAS_CCF.csv")
    assert parse_amount(voted_2018.iloc[0]["AE LFI 2018"]) == Decimal("42355399")
    ae_cp_2024 = read_table(FIXTURES / "Annexe1-Etat_AE_CP-2024.csv")
    assert parse_amount(ae_cp_2024.iloc[0]["AE_Ouvertes"]) == Decimal("3397166072.6")
    revenue_2024 = read_table(FIXTURES / "Annexe1-Etat_Recettes.csv")
    assert parse_amount(revenue_2024.iloc[1]["Total des recouvrements"]) == Decimal("10690400.58")


def test_quoted_amount_text_is_not_an_amount() -> None:
    with pytest.raises(AmountError):
        parse_amount('"10690400,58"')


def test_empty_cell_is_none_not_zero() -> None:
    assert parse_amount("") is None
    assert parse_amount("   ") is None


def test_dash_of_revenue_2025_is_an_error_not_zero_nor_empty() -> None:
    table = read_table(FIXTURES / "Annexe1-Etat_Recettes 2025.csv")
    row = table[table["Ligne_de_prevision"] == "1799 - Autres taxes"]
    dash = row.iloc[-1]["Total_des_recouvrements"]
    assert dash.strip() == "-"
    assert dash != dash.strip()
    with pytest.raises(AmountError, match="Not an amount"):
        parse_amount(dash)
    with pytest.raises(AmountError):
        parse_amount("-")


def test_scientific_notation_is_not_read_as_an_exact_amount() -> None:
    with pytest.raises(AmountError, match="scientific"):
        parse_amount("1,07584E+11")
    with pytest.raises(AmountError, match="scientific"):
        parse_amount("-2,6931E+10")


def test_scientific_cell_of_titre_cat_2023_is_reported() -> None:
    cells = find_scientific_cells(FIXTURES / "Annexe1-Etat_Titre_Cat-2023.csv")
    assert cells == [ScientificCell(line=4, column_index=4, column="Depenses", text="1,07584E+11")]


def test_four_scientific_cells_of_ae_cp_2023_are_reported() -> None:
    cells = find_scientific_cells(FIXTURES / "Annexe1-Etat_AE_CP-2023.csv")
    assert [(c.line, c.column_index, c.column, c.text) for c in cells] == [
        (28, 1, "AE_Ouvertes", "1,44146E+11"),
        (28, 2, "AE_Consommees", "1,42448E+11"),
        (28, 3, "CP_Ouverts", "1,44146E+11"),
        (28, 4, "CP_Consommes", "1,42445E+11"),
    ]


@pytest.mark.skipif(
    not (RAW / "Annexe1-Etat_Titre_Cat-2023.csv").exists(), reason="raw file not downloaded"
)
def test_scientific_cell_of_titre_cat_2023_full_file_is_at_line_697() -> None:
    cells = find_scientific_cells(RAW / "Annexe1-Etat_Titre_Cat-2023.csv")
    assert [(c.line, c.column, c.text) for c in cells] == [(697, "Depenses", "1,07584E+11")]


@pytest.mark.skipif(
    not (RAW / "Annexe1-Etat_AE_CP-2023.csv").exists(), reason="raw file not downloaded"
)
def test_ae_cp_2023_full_file_has_four_cells_at_line_28() -> None:
    cells = find_scientific_cells(RAW / "Annexe1-Etat_AE_CP-2023.csv")
    assert [(c.line, c.column) for c in cells] == [
        (28, "AE_Ouvertes"),
        (28, "AE_Consommees"),
        (28, "CP_Ouverts"),
        (28, "CP_Consommes"),
    ]


@pytest.mark.skipif(
    not (RAW / "Annexe1-Etat_Recettes-2023.csv").exists(), reason="raw file not downloaded"
)
def test_scientific_line_numbers_ignore_bare_cr_in_revenue_2023() -> None:
    cells = find_scientific_cells(RAW / "Annexe1-Etat_Recettes-2023.csv")
    assert {c.line for c in cells} >= {131, 322}
    assert 323 not in {c.line for c in cells}


def test_scientific_line_numbers_ignore_bare_cr_in_fixture() -> None:
    cells = find_scientific_cells(FIXTURES / "Annexe1-Etat_Recettes-2023.csv")
    assert [(c.line, c.column) for c in cells] == [
        (3, "Total_recouvrement"),
        (8, "LFI"),
        (8, "Total_prevision"),
    ]


def test_file_without_scientific_cell_gives_empty_list() -> None:
    assert find_scientific_cells(FIXTURES / "Annexe1-Etat_CP-2024.csv") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("348-11", "348-11"), ("07", "07"), ("#N/A", "#N/A"), ("7.0", "7"), ("2020.0", "2020")],
)
def test_code_stays_text(text: str, expected: str) -> None:
    assert normalise_code(text) == expected


def test_codes_of_real_files_stay_text() -> None:
    credits_2020 = read_table(FIXTURES / "LFI2020-crédits.csv")
    assert "348-11" in set(credits_2020["action"])
    staff_2020 = read_table(FIXTURES / "LFI2020-Emplois.csv")
    assert staff_2020.iloc[0]["ministere"] == "06"
    execution_2015 = read_table(FIXTURES / "PLR2015-Exec-Msn_CP-BG.csv", header_line=5)
    assert "07" in set(execution_2015["Action"])
    assert all(normalise_code(code) == code for code in execution_2015["Action"])


G2_BYTES = (
    b"Gestion;2016\nType Budget;Budget general\nCredits en euros\n"
    b"Mission;Titre;Montant\nA;T2;1\nB;T3;1,5E+10\n"
)


def test_scientific_cell_is_named_by_the_header_line_after_a_preamble() -> None:
    cells = find_scientific_cells(G2_BYTES, header_line=4)
    assert cells == [ScientificCell(6, 2, "Montant", "1,5E+10")]


def test_row_longer_than_the_line_one_header_raises_no_index_error() -> None:
    data = b"Gestion;2016\nA;B\nx;y;1,5E+10\n"
    assert find_scientific_cells(data, header_line=2) == [ScientificCell(3, 2, "", "1,5E+10")]
    assert find_scientific_cells(data) == [ScientificCell(3, 2, "", "1,5E+10")]


def test_extra_cell_of_a_row_longer_than_the_header_has_an_empty_column_name() -> None:
    cells = find_scientific_cells(b"A;B\n1;2;3,5E+09\n")
    assert cells == [ScientificCell(2, 2, "", "3,5E+09")]


def test_preamble_cell_that_looks_scientific_is_not_reported() -> None:
    data = b"Gestion;2016\nTotal;2,4E+09\nCredits en euros\nMission;Montant\nA;1,5E+10\n"
    assert find_scientific_cells(data, header_line=4) == [
        ScientificCell(5, 1, "Montant", "1,5E+10")
    ]
