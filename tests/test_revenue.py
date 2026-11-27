from pathlib import Path

import pandas as pd

from core.parse.decoding import read_table
from core.tables.revenue import (
    CHANGES_2024,
    FILE_2024,
    SOURCE_2024,
    builders,
    parse_revenue_2024,
)
from core.tables.schemas import KEYS
from core.tables.writer import read_metadata, validate_table, write_table

FIXTURE = Path(__file__).parent / "fixtures" / "decoding" / FILE_2024
NBSP = " "
HEADER = (
    "Niveau hiérarchique de la ligne,Catégorie,Section,Ligne de prévision,Ligne d'exécution,"
    "LFI,LFR/LFG,Total des prévisions,Total des recouvrements,Total des recettes**\n"
)


def rows_of(text: str) -> pd.DataFrame:
    return parse_revenue_2024(read_table((HEADER + text).encode()))


def test_validate_table_accepts_the_stage_collected_gross() -> None:
    frame = rows_of("1,Recettes fiscales,S,1101 - A,110101 - B,0,0,0,5,0\n")
    assert "collected_gross" in set(frame["stage"])
    validate_table(frame, "state_revenue_lines")


def test_each_rule_of_the_2024_load() -> None:
    frame = rows_of(
        "0,Recettes fiscales,S,1101 - Impôt,,100,-10,90,0,0\n"
        f'1,Recettes fiscales,S,1101 - Impôt,110101 - Créances{NBSP},0,0,0,"7,5",0\n'
        '3,Recettes fiscales,S (total),Total (total),Sans code (total),100,-10,90,"8,5","6,25"\n'
    )
    assert len(frame) == 12
    by_row = {(row.hierarchy_level, row.stage): row.amount_eur for row in frame.itertuples()}
    assert by_row[(0, "voted")] == 100
    assert by_row[(0, "amending_laws")] == -10
    assert by_row[(1, "collected_gross")] == 7.5
    assert by_row[(3, "collected")] == 6.25
    assert not any(stage == "total" for _, stage in by_row)
    labels = frame.drop_duplicates("hierarchy_level").set_index("hierarchy_level")
    assert labels.loc[0, "line_label"] == "1101 - Impôt"
    assert labels.loc[1, "line_label"] == "110101 - Créances"
    assert labels.loc[3, "line_label"] == "Sans code (total)"
    assert labels.loc[0, "line_code"] == "1101"
    assert labels.loc[1, "line_code"] == "110101"
    assert pd.isna(labels.loc[3, "line_code"])
    assert set(frame["budget_part"]) == {"BG"}
    assert set(frame["year"]) == {2024}
    assert set(frame["category"]) == {"Recettes fiscales"}


def test_the_fixture_gives_one_row_for_each_row_and_stage_with_a_unique_key() -> None:
    frame = parse_revenue_2024(read_table(FIXTURE))
    assert len(frame) == 4 * len(read_table(FIXTURE))
    validate_table(frame, "state_revenue_lines")
    assert not frame.duplicated(subset=list(KEYS["state_revenue_lines"])).any()


def test_the_builder_gives_the_rows_and_the_change_note(tmp_path: Path) -> None:
    (builder,) = builders()
    assert builder.source_ids == (SOURCE_2024,)
    built = builder.build({SOURCE_2024: [FIXTURE]})
    path = tmp_path / "state_revenue_lines.parquet"
    write_table(built.frame, builder.table, path, list(builder.source_ids), changes=built.changes)
    metadata = read_metadata(path)
    assert metadata.changes == {SOURCE_2024: CHANGES_2024}
    assert "Total des prévisions is not loaded" in CHANGES_2024
