"""One pandera schema for each shared table (version 1).

The columns, types and allowed values come from the "Shared tables" section of the
architecture plan. Every column has a description, and an amount column states its unit
there. A schema is strict: a column that the table does not define is an error. Codes are
strings kept as published, never numbers, and `year` is `int16`. The module also holds the
schema of the label frame that the State budget parsers return, which is not published.
"""

from collections.abc import Callable
from typing import Any

import pandas as pd
import pandera.pandas as pa

#: The four budget parts. `state_budget_lines` and `nomenclature` allow these only.
BUDGET_PARTS = ("BG", "BA", "CAS", "CCF")
#: Budget parts of `state_revenue_lines` and `state_employment`, which keep `unsplit` until
#: their follow-up ticket decides (M2-01a, issue #170).
BUDGET_PARTS_OR_UNSPLIT = (*BUDGET_PARTS, "unsplit")
UNITS = ("eur", "pct_gdp", "pct")


def _text(
    description: str,
    *,
    nullable: bool = False,
    allowed: tuple[str, ...] = (),
    pattern: str | None = None,
) -> pa.Column:
    checks = []
    if allowed:
        checks.append(pa.Check.isin(list(allowed)))
    if pattern is not None:
        checks.append(pa.Check.str_matches(rf"^{pattern}\Z"))
    return pa.Column("string", checks or None, nullable=nullable, description=description)


def _year(description: str = "Year.") -> pa.Column:
    return pa.Column("int16", description=description)


def _small_int(description: str, *, nullable: bool = False, low: int, high: int) -> pa.Column:
    dtype = "Int8" if nullable else "int8"
    return pa.Column(
        dtype,
        pa.Check.in_range(low, high),
        nullable=nullable,
        description=description,
    )


def _amount(description: str, *, nullable: bool = False) -> pa.Column:
    return pa.Column("float64", nullable=nullable, description=description)


def _source_id() -> pa.Column:
    return _text("Manifest id of the source file of the row.")


def frame_check(
    name: str, columns: tuple[str, ...], rule: Callable[[pd.DataFrame], Any]
) -> pa.Check:
    """Build a rule of the whole frame and record the columns that it reads.

    Args:
        name: Name of the rule; the error message shows it.
        columns: The columns that the rule reads.
        rule: Function of the frame that gives a boolean or a boolean series.

    Returns:
        The rule, to pass in the `checks` of a pandera schema. The columns stay on the rule,
        so two schemas can use one rule name without sharing columns.
    """
    check = pa.Check(rule, name=name)
    check.columns = columns  # type: ignore[attr-defined]
    return check


def frame_check_columns(check: pa.Check) -> tuple[str, ...] | None:
    """Return the columns that a rule built by `frame_check` reads, or None for another rule."""
    columns: tuple[str, ...] | None = getattr(check, "columns", None)
    return columns


def _schema(
    name: str,
    columns: dict[str, pa.Column],
    *,
    strict: bool = True,
    checks: list[pa.Check] | None = None,
) -> pa.DataFrameSchema:
    return pa.DataFrameSchema(columns, checks=checks, strict=strict, name=name)


_BUDGET_PART = "Budget part: BG, BA, CAS or CCF."
_BUDGET_PART_OR_UNSPLIT = (
    "Budget part: BG, BA, CAS, CCF, or unsplit where the source gives no part."
)
_PROGRAMME = "Programme code, three digits, kept as published."
PROGRAMME_CODE_PATTERN = r"[0-9]{3}"
MISSION_CODE_PATTERN = r"[A-Z]{2}"
LINE_CODE_PATTERN = r"[0-9]+"
_EUROS = "Amount in euros (not thousands or billions); may be negative."

STATE_BUDGET_LINES = _schema(
    "state_budget_lines",
    {
        "year": _year(),
        "budget_part": _text(_BUDGET_PART, allowed=BUDGET_PARTS),
        "programme_code": _text(_PROGRAMME, pattern=PROGRAMME_CODE_PATTERN),
        "title_group": _text(
            "Title group: T2 (title 2, staff), other (titles 1 and 3 to 7), or unsplit.",
            allowed=("T2", "other", "unsplit"),
        ),
        "stage": _text(
            "Budget stage of the amount.",
            allowed=(
                "bill",
                "amendments",
                "voted",
                "amending_laws",
                "carried_over",
                "regulatory_moves",
                "funds_attached",
                "asymmetric_fungibility",
                "opened",
                "executed",
            ),
        ),
        "credit_type": _text(
            "Credit type: AE (autorisations d'engagement) or CP (credits de paiement).",
            allowed=("AE", "CP"),
        ),
        "basis": _text(
            "Basis of the figure: budget or pdf_extraction.",
            allowed=("budget", "pdf_extraction"),
        ),
        "amount_eur": _amount(_EUROS),
        "source_id": _source_id(),
    },
    checks=[
        frame_check(
            "one_basis_for_each_year_and_stage",
            ("year", "stage", "basis"),
            lambda frame: frame.groupby(["year", "stage"])["basis"].nunique().le(1).all(),
        )
    ],
)

NOMENCLATURE = _schema(
    "nomenclature",
    {
        "year": _year(),
        "programme_code": _text(_PROGRAMME, pattern=PROGRAMME_CODE_PATTERN),
        "budget_part": _text(_BUDGET_PART, allowed=BUDGET_PARTS),
        "programme_label": _text("Programme label as published that year."),
        "mission_code": _text(
            "Mission code, two letters as published; null where the file gives a label only.",
            nullable=True,
            pattern=MISSION_CODE_PATTERN,
        ),
        "mission_label": _text(
            "Mission label as published that year; null where the source gives no mission.",
            nullable=True,
        ),
        "mission_family": _text("Stable mission grouping, one value of the reviewed mapping file."),
    },
)

#: Labels that a State budget parser returns next to its rows (docs page "State budget
#: model", rule 1). It is not a published table, so it is not in `SCHEMAS`: M2-07 merges the
#: frames of a year into `nomenclature`. Check a frame with
#: `validate_table(frame, "label_frame", schema=LABEL_FRAME, key=LABEL_FRAME_KEY)`.
LABEL_FRAME = _schema(
    "label_frame",
    {
        "year": _year("Year of the amounts, as in the budget rows."),
        "budget_part": _text(_BUDGET_PART, allowed=BUDGET_PARTS),
        "programme_code": _text(_PROGRAMME, pattern=PROGRAMME_CODE_PATTERN),
        "programme_label": _text(
            "Programme label as published, spaces around it removed; null where the file "
            "gives no programme label.",
            nullable=True,
            pattern=r"\S(?:[\s\S]*\S)?",
        ),
        "mission_code": _text(
            "Mission code, two letters as published; null where the file gives none. "
            "Never read from a label.",
            nullable=True,
            pattern=MISSION_CODE_PATTERN,
        ),
        "mission_label": _text(
            "Mission label as published; null where the file gives no mission.", nullable=True
        ),
        "source_id": _source_id(),
    },
)
#: One row per year, programme and source file.
LABEL_FRAME_KEY = ("year", "programme_code", "source_id")

STATE_REVENUE_LINES = _schema(
    "state_revenue_lines",
    {
        "year": _year(),
        "budget_part": _text(_BUDGET_PART_OR_UNSPLIT, allowed=BUDGET_PARTS_OR_UNSPLIT),
        "hierarchy_level": _small_int(
            "Hierarchy level of the line as published; null where the file has no level.",
            nullable=True,
            low=0,
            high=127,
        ),
        "line_label": _text("Label of the line, surrounding spaces removed."),
        "line_code": _text(
            "Digits before the first ' - ' of the label; null when the label has none.",
            nullable=True,
            pattern=LINE_CODE_PATTERN,
        ),
        "category": _text("Category as published."),
        "stage": _text(
            "Revenue stage of the amount: voted, amending_laws, collected (same concept as the "
            "voted line, net of refunds and tax reliefs) or collected_gross (collected before "
            "the refunds and tax reliefs of the State are deducted).",
            allowed=("voted", "amending_laws", "collected", "collected_gross"),
        ),
        "amount_eur": _amount(_EUROS),
        "source_id": _source_id(),
    },
)

STATE_EMPLOYMENT = _schema(
    "state_employment",
    {
        "year": _year(),
        "budget_part": _text(_BUDGET_PART_OR_UNSPLIT, allowed=BUDGET_PARTS_OR_UNSPLIT),
        "programme_code": _text(_PROGRAMME, pattern=PROGRAMME_CODE_PATTERN),
        "stage": _text("Stage of the figure.", allowed=("bill", "amendments", "voted", "executed")),
        "fte": _amount("ETPT, full-time equivalent worked over the year."),
        "source_id": _source_id(),
    },
)

STATE_MONTHLY = _schema(
    "state_monthly",
    {
        "year": _year(),
        "month": _small_int("Month, 1 to 12.", low=1, high=12),
        "hierarchy_level": _small_int(
            "Hierarchy level as published; a sum uses one level only.", low=0, high=127
        ),
        "category": _text("Category as published."),
        "sub_category": _text("Sub-category as published.", nullable=True),
        "line_label": _text("Line label as published."),
        "amount_eur": _amount(
            "Amount in euros (not thousands or billions), cumulative from January according "
            "to version 0; may be negative."
        ),
        "source_id": _source_id(),
    },
)

LEGISLATIVE_TEXTS = _schema(
    "legislative_texts",
    {
        "year": _year(),
        "source_id": _source_id(),
    },
    strict=False,
)

STATE_BALANCE_SHEET = _schema(
    "state_balance_sheet",
    {
        "year": _year(),
        "statement": _text(
            "Statement: balance_sheet or income_statement.",
            allowed=("balance_sheet", "income_statement"),
        ),
        "line_label": _text("Line label as published."),
        "amount_eur": _amount(_EUROS),
        "source_id": _source_id(),
    },
)

PERFORMANCE_INDICATORS = _schema(
    "performance_indicators",
    {
        "year": _year("Year of the target and the result."),
        "mission_label": _text("Mission label as published."),
        "programme_code": _text(
            "Programme code, three digits; null for indicators with no programme code.",
            nullable=True,
            pattern=PROGRAMME_CODE_PATTERN,
        ),
        "indicator_code": _text("Indicator code as published."),
        "indicator_label": _text("Indicator label as published."),
        "sub_indicator_code": _text("Sub-indicator code as published.", nullable=True),
        "sub_indicator_label": _text("Sub-indicator label as published.", nullable=True),
        "unit": _text("Unit of the indicator as published (%, per mille, ...)."),
        "target_kind": _text(
            "Kind of target: numeric, qualitative or none.",
            allowed=("numeric", "qualitative", "none"),
        ),
        "target_value": _amount(
            "Target, in the unit of the `unit` column; filled when target_kind is numeric.",
            nullable=True,
        ),
        "target_text": _text(
            "Published text of the target when target_kind is qualitative.", nullable=True
        ),
        "result_value": _amount(
            "Result, in the unit of the `unit` column; null when the result is not a number.",
            nullable=True,
        ),
        "reported_attainment": _text(
            "Attainment of the target as published, never recomputed.", nullable=True
        ),
        "source_id": _source_id(),
    },
    checks=[
        frame_check(
            "target_value_filled_when_target_kind_is_numeric",
            ("target_kind", "target_value"),
            lambda frame: (frame["target_kind"] != "numeric") | frame["target_value"].notna(),
        ),
        frame_check(
            "target_value_null_when_target_kind_is_none",
            ("target_kind", "target_value"),
            lambda frame: (frame["target_kind"] != "none") | frame["target_value"].isna(),
        ),
        frame_check(
            "target_text_filled_when_target_kind_is_qualitative",
            ("target_kind", "target_text"),
            lambda frame: (frame["target_kind"] != "qualitative") | frame["target_text"].notna(),
        ),
    ],
)

MACRO_FR = _schema(
    "macro_fr",
    {
        "year": _year(),
        "month": _small_int(
            "Month, 1 to 12 for monthly series; null for yearly series.",
            nullable=True,
            low=1,
            high=12,
        ),
        "indicator": _text("Project name of the series."),
        "sector": _text(
            "Sector: S13 and its ESA 2010 sub-sectors, state, or null for a series of no sector.",
            nullable=True,
        ),
        "value": _amount("Value, in the unit of the `unit` column."),
        "unit": _text(
            "Unit of value: eur (euros, not billions), pct_gdp (per cent of GDP), pct (per cent).",
            allowed=UNITS,
        ),
        "is_forecast": pa.Column("bool", description="True for years after the last closed year."),
        "source_id": _source_id(),
    },
)

FISCAL_COMMITMENTS = _schema(
    "fiscal_commitments",
    {
        "commitment_type": _text(
            "Type of commitment: stability_programme or programming_law.",
            allowed=("stability_programme", "programming_law"),
        ),
        "document": _text("Title of the document or law as published."),
        "document_date": pa.Column(
            pa.Date,
            description="Date of the document or law; first day of the month if only a month.",
        ),
        "reference": _text(
            "Article of the law, or page of the document for a hand-entered value; "
            "null for rows read from a file.",
            nullable=True,
        ),
        "entry_method": _text("How the row was entered: file or hand.", allowed=("file", "hand")),
        "target_year": _year("Target year."),
        "indicator": _text("Variable name of the indicator."),
        "value": _amount("Value, in the unit of the `unit` column (billions stored as euros)."),
        "unit": _text("Unit of value: eur, pct_gdp or pct.", allowed=UNITS),
        "source_id": _source_id(),
    },
    checks=[
        frame_check(
            "reference_filled_when_entry_method_is_hand",
            ("entry_method", "reference"),
            lambda frame: (frame["entry_method"] != "hand") | frame["reference"].notna(),
        ),
        frame_check(
            "reference_null_when_entry_method_is_file",
            ("entry_method", "reference"),
            lambda frame: (frame["entry_method"] != "file") | frame["reference"].isna(),
        ),
    ],
)

#: For each table, the columns of its key. A null counts as one key value.
KEYS: dict[str, tuple[str, ...]] = {
    "state_budget_lines": (
        "year",
        "budget_part",
        "programme_code",
        "title_group",
        "stage",
        "credit_type",
    ),
    "nomenclature": ("year", "programme_code"),
    "state_revenue_lines": ("year", "budget_part", "hierarchy_level", "line_label", "stage"),
    "state_employment": ("year", "programme_code", "stage"),
    "state_monthly": ("year", "month", "category", "sub_category", "line_label"),
    "state_balance_sheet": ("year", "statement", "line_label"),
    "performance_indicators": (
        "year",
        "programme_code",
        "indicator_code",
        "sub_indicator_code",
    ),
    "macro_fr": ("year", "month", "indicator", "sector", "unit", "source_id"),
    "fiscal_commitments": ("document", "document_date", "target_year", "indicator"),
}

SCHEMAS: dict[str, pa.DataFrameSchema] = {
    schema.name: schema
    for schema in (
        STATE_BUDGET_LINES,
        NOMENCLATURE,
        STATE_REVENUE_LINES,
        STATE_EMPLOYMENT,
        STATE_MONTHLY,
        LEGISLATIVE_TEXTS,
        STATE_BALANCE_SHEET,
        PERFORMANCE_INDICATORS,
        MACRO_FR,
        FISCAL_COMMITMENTS,
    )
    if schema.name is not None
}
