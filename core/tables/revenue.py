"""Builder of `state_revenue_lines`: the State revenue by line, year and stage.

Each source file of revenue has its own shape, so each has a parser from the table of text to
the rows of the table. The load rules of a file are in the docstring of its parser.
"""

from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from core.parse.decoding import read_table
from core.parse.numbers import parse_amount
from core.tables.build import Builder, BuiltTable

TABLE = "state_revenue_lines"
DATASET = "core"

SOURCE_2024 = "plrg-2024-execution"
FILE_2024 = "Annexe1-Etat_Recettes.csv"
YEAR_2024 = 2024
BUDGET_PART = "BG"

LEVEL_2024 = "Niveau hiérarchique de la ligne"
STAGE_COLUMNS_2024 = {
    "LFI": "voted",
    "LFR/LFG": "amending_laws",
    "Total des recettes**": "collected",
    "Total des recouvrements": "collected_gross",
}

CHANGES_2024 = (
    "All rows of Annexe1-Etat_Recettes.csv are loaded, the rows labelled (total) included, "
    "with one row for each amount column that the table holds: LFI gives voted, LFR/LFG gives "
    "amending_laws, Total des recettes** gives collected and Total des recouvrements gives "
    "collected_gross. Total des prévisions is not loaded: it is LFI plus LFR/LFG in every row. "
    "Project choice: collected holds the net amount, the concept of LFI (the notice of the "
    "file says gross revenue minus the refunds and tax reliefs of the State), and the file "
    "fills it at hierarchy levels 3 and 4 only; collected_gross holds Total des recouvrements, "
    "the amount before those refunds and tax reliefs are deducted. Amounts are as published. "
    "The label is the execution line where it is filled, else the forecast line, without "
    "surrounding spaces."
)


def parse_revenue_2024(table: pd.DataFrame, source_id: str = SOURCE_2024) -> pd.DataFrame:
    """Turn the table of text of `Annexe1-Etat_Recettes.csv` (2024) into revenue rows.

    Every row is loaded, the rows labelled `(total)` included. `hierarchy_level` is
    `Niveau hiérarchique de la ligne` as published. `line_label` is `Ligne d'exécution` where
    it is filled, else `Ligne de prévision`, with surrounding spaces (non-breaking spaces
    included) removed. `line_code` is the digits before ` - ` at the start of the label, else
    null. `category` is `Catégorie` as published and `budget_part` is `BG`. Each column of
    `STAGE_COLUMNS_2024` gives one row for each row of the file; `Total des prévisions` is not
    loaded. An empty amount cell gives no row.

    Args:
        table: The file read as text (`core.parse.decoding.read_table`).
        source_id: Manifest id of the file.

    Returns:
        The rows of `state_revenue_lines`, in the order of the file and then of the stages.

    Raises:
        AmountError: If an amount cell is not an exact amount (a scientific notation or a
            lone `-` included).
    """
    execution = table["Ligne d'exécution"].str.strip()
    label = execution.where(execution != "", table["Ligne de prévision"].str.strip())
    base = pd.DataFrame(
        {
            "year": YEAR_2024,
            "budget_part": BUDGET_PART,
            "hierarchy_level": table[LEVEL_2024].astype("int8"),
            "line_label": label,
            "line_code": label.str.extract(r"^([0-9]+) - ", expand=False),
            "category": table["Catégorie"],
        }
    )
    parts = []
    for column, stage in STAGE_COLUMNS_2024.items():
        amounts = table[column].map(parse_amount).dropna()
        parts.append(
            base.loc[amounts.index].assign(
                stage=stage, amount_eur=amounts.astype("float64"), source_id=source_id
            )
        )
    rows = pd.concat(parts).sort_index(kind="stable").reset_index(drop=True)
    rows["year"] = rows["year"].astype("int16")
    rows["hierarchy_level"] = rows["hierarchy_level"].astype("Int8")
    for column in ("budget_part", "line_label", "line_code", "category", "stage", "source_id"):
        rows[column] = rows[column].astype("string")
    return rows


def _build(files: Mapping[str, list[Path]]) -> BuiltTable:
    path = next(path for path in files[SOURCE_2024] if path.name == FILE_2024)
    rows = parse_revenue_2024(read_table(path))
    return BuiltTable(rows, {SOURCE_2024: CHANGES_2024})


def builders() -> list[Builder]:
    """Return the builders of the shared revenue tables (entry point of the package)."""
    return [Builder(TABLE, DATASET, (SOURCE_2024,), _build)]
