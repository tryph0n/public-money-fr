import gzip
import io
from pathlib import Path

import pandas as pd
import pytest

from core.parse.decoding import (
    Preamble,
    decode,
    detect_delimiter,
    read_preamble,
    read_table,
)
from core.parse.numbers import parse_amount

FIXTURES = Path(__file__).parent / "fixtures" / "decoding"
RAW = Path(__file__).parent.parent / "data" / "raw"

# One row per row of the encoding table of research note R2: file, encoding, delimiter, line of
# the header, a column, and the text that the first data row holds in it.
ENCODING_ROWS = [
    ("LFI2016-BG-Action_Titre.csv", "cp1252", ";", 4, "AELF 2015", "61 692 523"),
    ("LFI2017-BG-Action_Titre.csv", "cp1252", ";", 4, "AELF 2016", "59 992 865"),
    (
        "SYNTHETIC-Ressource-budgetaire-CP.csv",
        "cp1252",
        ";",
        1,
        "Crédits CP ouverts par LFI",
        "123 456 789",
    ),
    ("LFI_2018_ACT_CAT_TIT_BG_CAS_CCF.csv", "cp1252", ";", 1, "AE LFI 2018", "42 355 399"),
    (
        "LFI2021_crédits-AE_CP.csv",
        "cp1252",
        ";",
        1,
        "Libellé Programme",
        "Accès au droit et à la justice",
    ),
    (
        "LFI2022_detaillee.csv",
        "cp1252",
        ";",
        1,
        "Libellé Programme",
        "Accès au droit et à la justice",
    ),
    ("Annexe1-Etat_CP-2024.csv", "utf-8", ";", 1, "Depenses_constatees", "768754525,17"),
    ("Annexe1-Etat_CP-2023.csv", "utf-8", ";", 1, "Depenses_constatees", "742542019,3"),
    ("Annexe1-Etat_CP-2025.csv", "utf-8", ";", 1, "Depenses_constatees", "1323874519,32"),
    ("Annexe1-Etat_Recettes.csv", "utf-8", ",", 1, "Total des recouvrements", "0"),
    ("Annexe1-Etat_Recettes-2023.csv", "utf-8", ";", 1, "LFI", "0"),
    ("Annexe1-Etat_Recettes 2025.csv", "utf-8", ";", 1, "Total_des_recouvrements", "2320714,24"),
    (
        "Séries longues SMB_DGFiP_2013-2023.csv",
        "utf-16",
        ";",
        1,
        "31/01/2013",
        "-12817067246,53",
    ),
    ("LFI2020-crédits.csv", "utf-8", ";", 1, "AE LFI 2020", "50 000"),
    ("LFI2020-Emplois.csv", "utf-8", ";", 1, "ETPT LFI 2020", "133 867"),
    (
        "LFI2020-Nomenclature.csv",
        "cp1252",
        ";",
        1,
        "Libelle",
        "Avances aux collectivités territoriales",
    ),
    ("PLR2017-Exec-Msn_CP-BG.csv", "cp1252", ";", 1, "Code Titre", "2"),
]


@pytest.mark.parametrize(
    ("name", "encoding", "delimiter", "header", "column", "text"), ENCODING_ROWS
)
def test_encoding_row_is_read_correctly(
    name: str, encoding: str, delimiter: str, header: int, column: str, text: str
) -> None:
    data = (FIXTURES / name).read_bytes()
    decoded, found = decode(data)
    assert found == encoding
    assert detect_delimiter(decoded.split("\n")[header - 1]) == delimiter
    table = read_table(FIXTURES / name, header_line=header)
    assert table.iloc[0][column] == text


def test_voted_2018_file_is_windows_1252_not_utf_8() -> None:
    data = (FIXTURES / "LFI_2018_ACT_CAT_TIT_BG_CAS_CCF.csv").read_bytes()
    assert data[3] == 0xE9
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")
    text, encoding = decode(data)
    assert encoding == "cp1252"
    assert text.startswith("Année LFI;")


def test_2020_credits_file_is_ascii() -> None:
    data = (FIXTURES / "LFI2020-crédits.csv").read_bytes()
    assert data.isascii()
    assert decode(data)[1] == "utf-8"


def test_utf16_file_keeps_its_accents_and_columns() -> None:
    table = read_table(FIXTURES / "Séries longues SMB_DGFiP_2013-2023.csv")
    assert table.columns[0] == "Niveau hiérarchique"
    assert table.iloc[0]["Catégorie"] == "Solde budgétaire"
    assert len(table.columns) == 138
    assert len(table) == 5


def test_comma_delimited_file_keeps_quoted_amount() -> None:
    table = read_table(FIXTURES / "Annexe1-Etat_Recettes.csv")
    assert len(table.columns) == 10
    assert table.iloc[1]["Total des recouvrements"] == "10690400,58"
    assert parse_amount(table.iloc[1]["Total des recouvrements"]) is not None


def test_gzip_stream_is_unpacked() -> None:
    data = gzip.compress("Mission;Titre\nJustice;2\n".encode("cp1252"))
    assert decode(data) == ("Mission;Titre\nJustice;2\n", "utf-8")


def test_byte_order_mark_of_utf8_is_dropped() -> None:
    text, encoding = decode(b"\xef\xbb\xbfMission;Titre\n")
    assert (text, encoding) == ("Mission;Titre\n", "utf-8")


@pytest.mark.parametrize(
    ("line", "expected"),
    [("a;b;c", ";"), ("a,b,c", ","), ("a;b,c;d", ";"), ("a,b;c,d", ",")],
)
def test_delimiter_is_the_more_frequent_one(line: str, expected: str) -> None:
    assert detect_delimiter(line) == expected


@pytest.mark.parametrize("line", ["abc", "a;b,c"])
def test_delimiter_that_cannot_be_chosen_is_an_error(line: str) -> None:
    with pytest.raises(ValueError, match="delimiter"):
        detect_delimiter(line)


@pytest.mark.parametrize(
    ("name", "preamble"),
    [
        ("LFI2016-BG-Action_Titre.csv", Preamble(2016, "Budget général")),
        ("LFI2017-BG-Action_Titre.csv", Preamble(2017, "Budget général")),
        ("PLR2015-Exec-Msn_CP-BG.csv", Preamble(2015, "Budget général")),
    ],
)
def test_preamble_gives_year_and_budget_part(name: str, preamble: Preamble) -> None:
    assert read_preamble(FIXTURES / name) == preamble


def test_file_without_preamble_is_an_error() -> None:
    with pytest.raises(ValueError, match="Gestion"):
        read_preamble(FIXTURES / "Annexe1-Etat_CP-2023.csv")


def test_table_after_preamble_starts_at_its_header() -> None:
    table = read_table(FIXTURES / "LFI2016-BG-Action_Titre.csv", header_line=4)
    assert list(table.columns[:5]) == ["Mission", "Programme", "Action", "Libellé action", "Titre"]
    assert len(table) == 4
    assert table.iloc[0]["Programme"] == "105"


def test_preamble_table_with_credit_type_line_starts_on_line_5() -> None:
    table = read_table(FIXTURES / "PLR2015-Exec-Msn_CP-BG.csv", header_line=5)
    assert table.columns[0] == "Mission"
    assert table.iloc[0]["Programme"] == "105"
    assert len(table) == 4


def test_revenue_2023_bare_cr_does_not_split_rows() -> None:
    path = FIXTURES / "Annexe1-Etat_Recettes-2023.csv"
    data = path.read_bytes()
    records = data.count(b"\r\n") - 1
    assert data.count(b"\r") - data.count(b"\r\n") == 2
    naive = pd.read_csv(io.BytesIO(data), sep=";", dtype=str)
    assert len(naive) == records + 2
    table = read_table(path)
    assert len(table) == records == 10
    labels = table["Ligne_d'execution"]
    assert sum(label.endswith(" ") for label in labels) == 2


@pytest.mark.skipif(
    not (RAW / "Annexe1-Etat_Recettes-2023.csv").exists(), reason="raw file not downloaded"
)
def test_revenue_2023_full_file_has_604_rows() -> None:
    assert len(read_table(RAW / "Annexe1-Etat_Recettes-2023.csv")) == 604


def test_label_with_line_break_is_one_row() -> None:
    table = read_table(FIXTURES / "LFI2020-Nomenclature.csv")
    assert len(table) == 7
    label = table[table["code"] == "10"].iloc[0]["Libelle"]
    assert label.startswith("Cat Dotations des pouvoirs publics\n")


def test_header_with_line_break_in_quotes_is_one_column() -> None:
    table = read_table(FIXTURES / "PLR2017-Exec-Msn_CP-BG.csv")
    assert "EXEC CP 2017\nRAP 2017" in table.columns
    assert len(table) == 5


def test_na_code_of_budget_file_stays_text_by_default() -> None:
    table = read_table(FIXTURES / "PLR2017-Exec-Msn_CP-BG.csv")
    rows = table[table["Code Mission"] == "PB"]
    assert len(rows) == 2
    assert list(rows["Code Titre"]) == ["#N/A", "#N/A"]
    assert list(rows["Titre"]) == ["#N/A", "#N/A"]


def test_na_text_of_european_commission_file_is_missing_when_listed() -> None:
    path = FIXTURES / "scp_database_France.csv"
    table = read_table(path, na_values=("NA",))
    assert table["nominal_growth"].isna().all()
    assert table.loc[0, "real_growth"] == "3"
    assert table.loc[0, "GDPlevel_bln"] == ""
    assert read_table(path)["nominal_growth"].eq("NA").all()


def test_empty_cell_is_missing_only_when_listed() -> None:
    path = FIXTURES / "LFI_2018_ACT_CAT_TIT_BG_CAS_CCF.csv"
    assert read_table(path).iloc[0]["Code Sous-Action"] == ""
    assert read_table(path, na_values=("",)).iloc[0].isna()["Code Sous-Action"]
