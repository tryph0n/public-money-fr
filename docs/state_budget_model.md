# State budget model

This page gives the rules that turn the State budget files of 2010 to 2025 into two shared
tables: `state_budget_lines` (one amount for each year, budget part, programme, title group,
stage and credit type) and `nomenclature` (the labels of each year and programme). The parsers
of the five generations of files apply these rules, so that one amount gets the same stage,
budget part and title group in every year. The schemas of the two tables are in
`core/tables/schemas.py`; the writer refuses a row that breaks them.

The figures on this page were measured on the full files on 27 November 2026, unless the text
gives another date.

| Generation | Years | Files |
| --- | --- | --- |
| G1 | execution 2010 to 2012, voted 2010 to 2014 | records of data.economie.gouv.fr, by programme, action and title (by category in voted 2013) |
| G2 | execution 2013 to 2016, voted 2015 to 2017 | pivot-table exports with a preamble (`Gestion;<year>`, `Type budget;<label>`) before the header |
| G3 | execution 2017 to 2020, voted 2018 to 2020 | long files, records and workbooks by programme, action, sub-action and category |
| G4 | voted 2021 to 2023 | bill, amendments and vote, with title 2 and other-title columns |
| G5 | 2023 to 2025 | annex files of the settlement bill (`Annexe1-*`, `Annexe2-*`) and the annex budget files (`BACEA-*`, `BAPOIA-*`) |
| RAP synthesis | execution 2021 and 2022 | workbooks of budget.gouv.fr (`RAP_synthese_2021.xls`, `RAP2022_synthese_chiffres.xls`), downloaded by hand |

## 0. Grain and columns

- One row of `state_budget_lines` for each year, budget part, programme, title group, stage and
  credit type. This is the key of the table. The programme is the finest grain: a parser sums
  the actions, sub-actions and categories of a programme.
- Commitment credits (AE) and payment credits (CP) are two rows. A column that gives one amount
  for both gives one AE row and one CP row with the same amount: `EXEC T2 (AE=CP)` of the
  execution 2017 staff file, `T2 AE=CP LFI 2018` of the voted 2018 staff file and
  `exec_t2_ae_cp_2018_rap_2018` of execution 2018.
- The four budget parts are kept apart. A total names the parts that it covers, because the
  files of some years do not hold all four parts.
- An empty source cell gives no row: it is never a zero, because an empty cell is not a
  published zero. A `0` cell is a published amount and gives a row. Negative amounts are kept.

Code columns:

| Column | Table | Definition |
| --- | --- | --- |
| `year` | both | year of the amounts (the year of the finance law), read in the file or in its manifest entry, never in a dataset id |
| `budget_part` | both | `BG`: budget général (general budget); `BA`: budgets annexes (annex budgets, programmes 6xx); `CAS`: comptes d'affectation spéciale (special allocation accounts, programmes 7xx); `CCF`: comptes de concours financiers (financial loan accounts, programmes 8xx) |
| `programme_code` | both | three digits as published, stored as text; the voted 2023 records give it as a number (`166.0`), which the parser writes as `166` |
| `title_group` | `state_budget_lines` | `T2`: title 2, staff costs; `other`: titles 1 and 3 to 7; `unsplit`: the file gives no title for the amount |
| `stage` | `state_budget_lines` | step of the budget that the amount describes (table below) |
| `credit_type` | `state_budget_lines` | `AE`: autorisations d'engagement, the ceiling of the legal commitments of the year; `CP`: crédits de paiement, the ceiling of the payments of the year |
| `basis` | `state_budget_lines` | `budget`: budget files, including the RAP synthesis workbooks of 2021 and 2022; `pdf_extraction`: amounts extracted from PDF files (2006 to 2009, not loaded yet) |
| `source_id` | `state_budget_lines` | manifest id of the source of the row (see the data catalogue) |
| `mission_code` | `nomenclature` | two letters as published (`JA`); null where the files of the year give a mission label only |
| `mission_family` | `nomenclature` | stable group of missions, so that a renamed mission keeps its group (rule 6) |

Stages:

| Stage | Definition | Years |
| --- | --- | --- |
| `bill` | credits of the finance bill (projet de loi de finances, PLF), as the government tabled it | where the file gives it: voted 2011 to 2014, 2016, 2017, 2021 to 2023 |
| `amendments` | change of the bill made by the amendments that Parliament adopted; it can be negative | as `bill` |
| `voted` | credits of the initial finance law (loi de finances initiale, LFI) | 2010 to 2025 |
| `amending_laws` | change made by the amending finance laws of the year (lois de finances rectificatives, LFR) | 2023 to 2025 |
| `carried_over` | credits carried over from the year before (reports from year N-1) | 2023 to 2025 |
| `regulatory_moves` | changes made during the year by decree or order: transfers, moves between programmes, decrees of advance, cancellations | 2023 to 2025 |
| `funds_attached` | credits opened from fonds de concours and attributions de produits (FDC and ADP), money given to the State for a set use | 2023 to 2025 |
| `asymmetric_fungibility` | credits moved from title 2 to other titles inside a programme (fongibilité asymétrique); for the BAPOIA annex budget, its moves between titles (`Fongibilite_intertitres`) | 2023 to 2025 |
| `opened` | all the credits open for the year: `voted` plus the five stages above | 2023 to 2025 |
| `executed` | credits used in the year: AE consumed, CP spent; the net amount where a file gives a gross and a net amount | 2010 to 2025 |

The coverage of each year, table and stage is shown by a later report ([#32](https://github.com/tryph0n/public-money-fr/issues/32)): some years lack a
budget part or a stage, for example voted 2019 has no annex budget.

## 1. Label frame

`state_budget_lines` has no label column, and `nomenclature.mission_family` is not nullable, so
a parser cannot write `nomenclature` rows. Each parser returns a label frame next to its budget
rows. The label frame is not a published table. It has no `mission_family`, because the
nomenclature build ([#27](https://github.com/tryph0n/public-money-fr/issues/27)) sets it from a reviewed mapping file. Its schema is `LABEL_FRAME` in
`core/tables/schemas.py`, with the key `LABEL_FRAME_KEY`; a parser checks its frame with
`validate_table(frame, "label_frame", schema=LABEL_FRAME, key=LABEL_FRAME_KEY)`.

| Column | Type | Rule |
| --- | --- | --- |
| `year` | int16 | year of the amounts, as for the budget rows |
| `budget_part` | string | as in `state_budget_lines` |
| `programme_code` | string | three digits, as in `state_budget_lines` |
| `programme_label` | string, nullable | as published, with the spaces around it removed (in the G5 files, without the code at its end, `... - 176`); null where the file gives no programme label (the voted G1 files and the voted G2 files by action) |
| `mission_code` | string, nullable | two letters as published; null where the file gives no code. Never read from a label |
| `mission_label` | string, nullable | as published; null where the file gives no mission |
| `source_id` | string | manifest id of the file |

- One row for each year, programme and source file. The nomenclature build merges the frames
  of a year, because `nomenclature` has one row for each year and programme: a value given by
  one file of the year fills the row that the other files of that year share.
- Where the files of one source give two labels for one programme, the parser keeps the longer
  label if the shorter one is its start (a label cut by the file), and fails otherwise.
- A label frame can hold a programme that has no budget row (a nomenclature file lists every
  programme). The nomenclature build keeps only the years and programmes of the budget rows.

## 2. Budget part

The parser reads the part from the part column or the preamble line of the file, where there is
one. A label that the table below does not list makes the parser fail.

| Files | Column or preamble line | Values |
| --- | --- | --- |
| G2 | preamble line `Type budget;<label>` or `Type Budget;<label>` | `Budget général` gives `BG`, `Comptes d'affectation spéciale` `CAS`, `Comptes de concours financiers` `CCF`, `Budgets annexes` `BA`; `All` (execution 2013 and 2014) gives no part, so the code rule applies |
| G3 | `Type de Budget (Hors Budgets annexes)` (field `type_de_budget_hors_budgets_annexes` in the records), `Type de Budget` in the staff files | the labels `Budget général`, `Comptes d'affectation spéciale`, `Comptes de concours financiers`, `Budgets annexes`; the execution 2018 dataset by action gives the codes `BG`, `CAS` and `CCF` in this column |
| G3 | `typeBudget` (execution 2019 and 2020, voted 2020) | `BG`, `CAS`, `CCF`, `BA` |
| G4 | `Type Mission` (2021, 2022), `type_mission` (2023) | `BG`, `CAS`, `CCF`, `BA` |
| G5 | `Categorie` of `Annexe2-Etat_AE` and `Annexe2-Etat_CP`, 2024 and 2025 | `Comptes d’affectation spéciale` (with a typographic apostrophe) gives `CAS`, `Comptes de concours financiers` `CCF` |
| RAP synthesis | `Budget`, the second column of the sheet `Crédits` | `BG`, `BA`, `CAS`, `CCF` |

Where the file gives no part, the part comes from the first digit of the programme code: `6`
gives `BA`, `7` gives `CAS`, `8` gives `CCF`, any other digit gives `BG`. This rule agrees with
the part column in every file that has both: voted 2021 and 2022 (`Type Mission`), voted 2023,
`Annexe2-Etat_CP-2024.csv` (its 17 CAS rows are 7xx, its 23 CCF rows are 8xx), execution 2019
and 2020 (`typeBudget`) and execution 2012 (its CAS and CCF missions). The programmes 401 to 412
and 414 of execution 2014 are in budget général missions, so they are `BG`.

A parser whose file holds only some parts fails on a code of another part, because the code
rule must not invent a part that the file does not hold. For example, the `Annexe1` files of
2023 to 2025 hold the budget général only, and the annex budget files of 2023 to 2025 hold the
annex budgets only.

**Pitfall:** execution 2012 (the AE and CP datasets by mission and programme) holds the budget
général and the CAS and CCF programmes in one file, with no part column: budget général CP
390,094,314,407 euros, CAS and CCF CP 167,635,003,931 euros. A parser that takes the whole file
as budget général counts the special accounts twice. The code rule gives the part.

## 3. Title group

| Case | Files | Title group |
| --- | --- | --- |
| a title code | most files | `2` gives `T2`; `1` and `3` to `7` give `other` |
| title code `#N/A` (a spreadsheet error value) and a category code | execution 2017, files by mission of the budget général: 7 rows (programmes 501 to 541, category `10`) | the first digit of the category: these rows are title 1, so `other`; they sum to 990,920,236 euros, the `T1` total of the files by ministry |
| a category code and no title column | voted 2013, G1 datasets by category | the first digit of the category; category `0` (11 rows, mission Pouvoirs publics, programmes 501 to 542) is title 1, so `other` |
| a long file of titles | execution 2011, AE dataset of the budget général (`t_categorie`, `valeur`) | `t_categorie` holds the titles `T1` to `T7`, not categories (title 2: 306 rows) |
| one column per title | G1 execution (`t1` to `t7`), G2 execution (`T1` to `T7`) | the column gives the title |
| title 2 and other-title columns | G4 voted 2021 to 2023, the G3 staff files, the voted annex budget files of G1 and G2, the RAP synthesis workbooks | the column gives the group, not `Code Titre` |
| no title and no category | voted 2020 and execution 2019 and 2020: 12 annex budget rows each year (12 of the 19 annex budget rows of each execution year) | `unsplit` |
| `Titre N` rows | annex budget files of 2023 to 2025 (`Libelle`) | `Titre 2` gives `T2`; `Titre 3` to `Titre 7` give `other` |
| `Titre` column | G5 `Annexe1` and `Annexe2` | `Titre 2 - Dépenses de personnel` gives `T2`; `Autres titres - Autres dépenses` gives `other` |

Why the first digit of the category is the title: wherever a file gives both codes, the title
equals the first digit of the category. Also, the voted G1 files by title have 11 rows of
title 1, in the same programmes. Why the column wins over `Code Titre` in G4:
`Code Titre` and `Catégorie` are empty on 12 annex budget rows of each of 2021 and 2022
(programmes 612, 613, 614, 623 and 624), whose amounts are in the other-title columns, and
`code_titre` is `4.0` on all 2,322 records of voted 2023.

Years on which the rule was checked:

| File | Rows compared | Rows that differ |
| --- | --- | --- |
| execution 2017, each file by mission of the budget général (title against category) | 2,847 | 0 |
| execution 2017, special account files, each credit type (title against category) | 135 | 0 |
| voted 2018 (title against category) | 2,172 | 0 |
| execution 2018 (title against category) | 3,060 | 0 |
| voted 2019 (title against category) | 2,260 | 0 |
| execution 2019 and 2020 (title against category) | every row with a title | 0 |
| voted 2020 (title against category) | 2,228 | 0 |
| G4 2021 and 2022 (a title 2 row with an other-title amount, or another title with a title 2 amount) | every row | 0 |

Annex budgets keep the title groups that their files give, because amounts are loaded as
published:

| Year and stage | Source of the title groups |
| --- | --- |
| voted 2012 to 2014 | G1 annex budget datasets, title 2 and other-title fields |
| voted 2016 and 2017 | `LFI2016-T2_HT2-BA-Programme.csv`, `LFI2017-T2_HT2-BA-Programme.csv`: `AE Titre 2`, `AE Autres titres`, `CP Titre 2`, `CP Autres titres` |
| executed 2017, voted 2018, executed 2018 | the staff files (title 2 and other titles) |
| executed 2019, voted 2020, executed 2020 | 12 rows each year with no title and no category give `unsplit` |
| voted 2021 to 2023 | the G4 title 2 and other-title columns |
| executed 2021 and 2022 | the title 2 and other-title columns of the RAP synthesis workbooks |
| 2023 to 2025 | the `Titre N` rows of the annex budget files |

**Warning:** in the files `LFI2016-T2_HT2-BA-Programme.csv` and `LFI2017-T2_HT2-BA-Programme.csv`
of the Direction du budget (data.economie.gouv.fr datasets
`loi-de-finances-initiale-pour-2016-lfi-2016` and `loi-de-finances-initiale-pour-2017-lfi-2017`),
voted title 2 of the annex budgets is 0, except 631,890 euros in CP for programme 624 in 2016.
Yet état C of the finance laws gives staff costs for programme 613 (1,142,277,693 euros in 2016,
1,183,200,877 in 2017) and programme 624 (75,188,918 and 73,900,000),
`LFI2017-ETP-BA-Programme.csv` lists staff for programme 613, and the execution 2017 staff file
gives 1,232,869,404 euros of title 2. The amounts are loaded as published, so voted title 2 of the annex budgets in 2016 and 2017 must
not be compared with executed title 2.

## 4. Stages

| Files | Columns | Stage |
| --- | --- | --- |
| G1 voted 2011 to 2014 | `aeplf`, `cpplf` | `bill` |
| G1 voted 2011 to 2014 | `aeamt`, `cpamt` | `amendments` |
| G1 voted 2011 to 2014 | `aelf`, `cplf` | `voted` |
| G1 voted 2011 | `aelf_2010`, `cplf_n1` | `voted` of 2010 |
| G1 voted 2012 to 2014 | `aelf_<year-1>`, `cplf_<year-1>` | none |
| G1 voted annex budgets 2012 to 2014 | title 2 and other-title fields | `voted` |
| G1 execution 2010 to 2012 | `t1` to `t7`; `valeur` (AE 2011) | `executed`; `total_general` is a check of each row |
| G2 execution 2013 to 2016 | `T1` to `T7` | `executed`; `Total général` is a check of each row |
| G2 voted 2016 and 2017 by action and title | `AEPLF`, `CPPLF` | `bill` |
| G2 voted 2016 and 2017 by action and title | `AEAMT`, `CPAMT` | `amendments` |
| G2 voted 2016 and 2017 by action and title | `AELF`, `CPLF` | `voted` |
| G2 voted 2016 (budget général and CCF) | `AELF 2015`, `CPLF 2015` | `voted` of 2015 |
| G2 voted 2017 | `AELF 2016`, `CPLF 2016` | none |
| G2 voted annex budgets 2016 and 2017 | `AE Titre 2`, `AE Autres titres`, `CP Titre 2`, `CP Autres titres` | `voted`; `Total AE` and `Total CP` are a check |
| G3 execution 2017 | `EXEC AE 2017` and `EXEC CP 2017`, each followed by a line break and `RAP 2017` (files by mission); `EXEC T2 (AE=CP)`, `EXEC AE Hors T2`, `EXEC CP Hors T2` (staff file) | `executed` |
| G3 execution 2018 | `exec_ae_2018_rap_2018`, `exec_cp_2018_rap_2018`; `exec_t2_ae_cp_2018_rap_2018`, `exec_ae_hors_t2_2018_rap_2018`, `exec_cp_hors_t2_2018_rap_2018` (annex budgets) | `executed` |
| G3 voted 2018 | `AE LFI 2018`, `CP LFI 2018`; `T2 AE=CP LFI 2018`, `AE HORS T2 LFI 2018`, `CP HORS T2 LFI 2018` (staff file) | `voted` |
| G3 voted 2019 | `ae_lfi_2019`, `cp_lfi_2019` | `voted` |
| G3 voted 2020 | `AE LFI 2020`, `CP LFI 2020` | `voted` |
| G3 execution 2019 and 2020 | `AE EXEC`, `CP EXEC` (sheet `Credits`) | `executed` |
| G4 2021 and 2022 | `AE T2 PLF`, `CP T2 PLF`, `AE HT2 PLF`, `CP HT2 PLF` | `bill` |
| G4 2021 and 2022 | `AE T2 AMD`, `CP T2 AMD`, `AE HT2 AMD`, `CP HT2 AMD` (case ignored) | `amendments` |
| G4 2021 and 2022 | `AE T2 LFI`, `CP T2 LFI`, `AE HT2 LFI`, `CP HT2 LFI` | `voted` |
| G4 2021 and 2022 | `AE ( T2 + HT2) LFI`, `CP ( T2 + HT2) LFI` | none: a check of each row |
| G4 2023 | `ae_t2_plf_2023`, `cp_t2_plf_2023`, `ae_hors_t2_plf_2023`, `cp_hors_t2_plf_2023` | `bill` |
| G4 2023 | `ae_t2_amendements_2023`, `cp_t2_amendements_2023`, `ae_hors_t2_amendements_2023`, `cp_hors_t2_amendements_2023` | `amendments` |
| G4 2023 | bill plus amendments of each record | `voted` (computed, see below) |
| RAP synthesis 2021 and 2022 | the title 2 and other-title columns of the executed block of the year (the AE and CP totals are a check) | `executed`; the voted and previous-year blocks are not read |
| G5 `Annexe1` and `Annexe2`, AE and CP | `LFI` | `voted` from 2024; in 2023 a check of voted 2023 |
| G5 `Annexe1` and `Annexe2`, AE and CP | `LFR` | `amending_laws` |
| G5 `Annexe1` and `Annexe2`, AE and CP | `Report_N-1` | `carried_over` |
| G5 `Annexe1` and `Annexe2`, AE and CP | `Mvts_reglementaires` | `regulatory_moves` |
| G5 `Annexe1` and `Annexe2`, AE and CP | `FDC_et_ADP` | `funds_attached` |
| G5 `Annexe1` and `Annexe2`, AE and CP | `Fongibilite_asymetrique` | `asymmetric_fungibility` |
| G5 `Annexe1` and `Annexe2`, AE and CP | `Total_AE_Ouvertes`, `Total_CP_Ouverts` | `opened` |
| G5 `Annexe1` and `Annexe2`, AE and CP | `AE_Consommees`, `Depenses_constatees` | `executed` |
| annex budget files 2023 to 2025 | `AE_Initiales`, `CP_Initiaux` (BACEA), `CP_Initiales` (BAPOIA) | `voted` from 2024; in 2023 a check of voted 2023 |
| annex budget files 2023 to 2025 | opening and cancellation linked to legislative measures (BACEA, two columns); `Modifications_..._liees_aux_mesures_legislatives` (BAPOIA) | `amending_laws`, the sum of the columns |
| annex budget files 2023 to 2025 | opening and cancellation linked to regulatory measures (BACEA, two columns); `Modifications_..._liees_aux_mesures_reglementaires` (BAPOIA) | `regulatory_moves`, the sum of the columns |
| annex budget files 2023 to 2025 | `Fongibilite_asymetrique` (BACEA), `Fongibilite_intertitres` (BAPOIA) | `asymmetric_fungibility` |
| annex budget files 2023 to 2025 | `Total_des_autorisations_d'engagement(_)`, `Total_des_credits_de_paiement(s)` | `opened` |
| annex budget files 2023 to 2025 | `Autorisations_consommees_nettes` (BACEA AE), `Autorisations_consommees` (BAPOIA AE, its only consumed column), `Depenses_nettes(_)` | `executed` |

The G5 files: `Annexe1-Etat_AE-2023.csv` has 13 columns, with no `Report_N+1`; the other AE and
CP files have one, and the `Annexe2` files of 2024 and 2025 start with a `Categorie` column. The
annex budget files (`BACEA-Dev_AEN`, `BACEA-Dev_CPN`, `BAPOIA-Synt_AE`, `BAPOIA-Synt_CP`) have
no `Report_N-1` and no `FDC_et_ADP` column, so the annex budgets have no `carried_over` and no
`funds_attached` rows.

Columns with no stage, and why:

- `Modif_Ouvertures` and `Modif_Annulations` (G5 files, and annex budget files of 2024 and
  2025), and the `Modifications_..._a_demander_...` columns of the 2023 annex budget files: they
  are changes asked for after the year (*"Modifications d'autorisations d'engagement a demander
  dans le projet de loi relative aux resultats de la gestion et portant approbation des comptes
  de l'annee"*, header of `2023_BACEA-Dev_AEN-2023.csv`), not credits of the year.
- `Report_N+1`, `Autorisations_reportees_a_N+1` and `Credits_reportes_a_N+1`: credits carried to
  the next year.
- `Recyclage_d'AE` (BACEA AE only): it is part of the opened AE of BACEA, so in BACEA AE the
  stages from `voted` to `asymmetric_fungibility` do not add up to `opened`. The difference is
  6,620,539.80 euros in 2023, 4,989,977.50 in 2024 and 6,499,897.67 in 2025.
- `Autorisations_consommees_brutes`, `Depenses_constatees` of the annex budget files,
  `Retablissement_de_credits` and `Retablissements_de_credits`: the gross amounts and the
  credits restored. `executed` is the net amount, because the budget presentation file gives
  the net amount: in `2023_BACEA-Pres_Bud-2023.csv`, title 2 of programme 613 is
  1,258,756,193.01 euros, its net title 2 spending.
- Row totals (`total_general`, `Total général`, `Total AE`, `Total CP`, the `T2 + HT2` columns):
  checks of each row.

`opened` equals the sum of the six columns from `LFI` to `Fongibilite_asymetrique`, without the
columns that have no stage: the largest difference is 0.50 euro per row (the 2023 `Annexe1` AE
and CP files, whose amounts are rounded to one decimal), and 0 in all other annex files of 2023
to 2025. The check cannot be made on programme 200 of `Annexe1` and programme 833 of `Annexe2`
in 2023, because their `LFI` cell is in scientific notation. In the 12 annex budget files, `opened` equals the sum of the columns between the
initial credits and the total, with `Recyclage_d'AE` in BACEA AE (difference 0).

### Voted 2010, 2015 and 2023

`voted` of a year comes from the file of that year. The previous-year columns of a later file
are not loaded. In the voted files of 2012 to 2014 they are a check of the vote of the year
before: in the 2012 and 2014 files they equal it exactly; in the 2013 file AE equals it and CP
is 20,000,000 euros lower. There are three exceptions.

- **Voted 2010** comes from the 2010 columns (`aelf_2010` and `cplf_n1`) of the voted 2011
  datasets, because no voted 2010 dataset exists. It has no `bill` and no `amendments`. In the
  budget général dataset these columns use the 2011 programmes: programmes 332, 333 and 334, new
  in 2011, give 0. Programmes executed in 2010 with no row in this file give no voted 2010 row:
  108, 171, 188, 189, 210, 213, 306, 311, 312, and 315 to 331 (credits opened by amending laws).
  Totals of the budget général: AE 378,607,060,452 euros (title 2: 116,894,561,224; other
  titles: 261,712,499,228); CP 375,318,937,490 euros (title 2: 116,894,561,224; other titles:
  258,424,376,266).
- **Voted 2015** comes from the 2015 columns of the 2016 files (budget général and CCF), because
  it has no other source. The CAS columns of the 2016 file lack programme 762, so voted 2015 of
  the CAS is not loaded.
- **Voted 2023** is bill plus amendments of the 2023 dataset, record by record, for each title
  group and credit type. This amount is computed by the project. The reason is an error of the
  source: in the dataset `credits-ae-et-cp-votes-nomenclature-par-destination-et-nature-lfi-2023`
  of the Direction du budget (data.economie.gouv.fr), the six voted columns (`*_lfi_2023`) hold
  `4.0` on every record. The `LFI` columns of the 2023 annex files are a check, not a source of
  `voted`: they equal the computed amount for every programme, except programmes 200 and 833,
  whose `LFI` cell is in scientific notation (`1,27055E+11`, `1,24824E+11`) and so not
  comparable. The initial credits of the 2023 annex budget files equal the computed amount of
  the annex budgets exactly.

## 5. `totals_only` and the budget part `unsplit`

Both are removed from `state_budget_lines`, and `unsplit` is removed from the budget parts of
`nomenclature`. The reason: no year needs them, because 2021 and 2022 are read from budget
files that give a part on each row (the RAP synthesis workbooks), and a value that no table
needs is not kept. The schema now refuses them.

The title group `unsplit` stays, because voted 2020 and execution 2019 and 2020 need it
(rule 3).

`state_revenue_lines` and `state_employment` keep the budget part `unsplit` for now, because
they have their own tickets. The follow-up ticket
[#170](https://github.com/tryph0n/public-money-fr/issues/170) decides for them.

## 6. Mission families

`mission_family` is an editorial grouping that the public pages show, so it is reviewed before
it is published:

1. The nomenclature build ([#27](https://github.com/tryph0n/public-money-fr/issues/27)) writes a mapping file from every mission label of 2010 to
   2025.
2. A second reviewer, who did not write the file, checks it against every mission label.
3. The owner of the project approves the file in the pull request of [#27](https://github.com/tryph0n/public-money-fr/issues/27).

## 7. One programme from 2010 to 2024

Programme 176, Police nationale (mission `Sécurité` in the 2011 file), in the budget général:

| Year | Files and generation | Budget part | Title groups | Stages |
| --- | --- | --- | --- | --- |
| 2010 | executed: `execution-2010-du-budget-general-en-ae` and `-en-cp` (G1, `t1` to `t7`); voted: `loi-de-finances-intiale-2011-budget-general` (G1, `aelf_2010`, `cplf_n1`, by `titre`) | `BG`, from the code rule (no part column) | `T2` from title 2; `other` from titles 3, 5 and 6 | `voted`, `executed` |
| 2016 | `LFI2016-BG-Action_Titre.csv` (G2 voted, `Titre`); `PLR2016-Exec-Msn_AE-BG.csv`, `PLR2016-Exec-Msn_CP-BG.csv` (G2 execution, `T1` to `T7`) | `BG`, from the preamble `Type Budget;Budget général` | `T2`, `other` | `bill`, `amendments`, `voted`, `executed` |
| 2019 | records of `loi-de-finances-initiale-pour-2019-lfi-2019-1` (G3 voted, `code_titre`); `PLR2019-Credits_Destination_Nature.xls`, sheet `Credits` (G3 execution, `titre`) | `BG`, from `type_de_budget_hors_budgets_annexes` (voted) and `typeBudget` (executed) | `T2`, `other` | `voted`, `executed` |
| 2024 | `Annexe1-Etat_AE-2024.csv`, `Annexe1-Etat_CP-2024.csv` (G5) | `BG`, from the code rule (`Annexe1` holds the budget général only) | `T2` from `Titre 2 - Dépenses de personnel`, `other` from `Autres titres - Autres dépenses` | the eight stages from `voted` to `executed` |

In 2010, for example, CP: voted title 2 7,717,769,783 euros and other titles 1,032,730,341
euros; executed title 2 7,820,376,749 euros and other titles 1,037,691,373 euros (read on the
portal on 27 November 2026). The 2010 execution datasets give a ministry, not a mission, so the
mission label of 2010 comes from the 2011 file. The 2024 files give the mission label only, so
`mission_code` is null in their label frame; their programme label is the `Programme` cell
without the code at its end (`... - 176`).

## Open questions

- Net or gross executed amounts: the annex budget files give both and `executed` takes the net
  amount. `AE_Consommees` and `Depenses_constatees` of the `Annexe1` and `Annexe2` files, and
  `Autorisations_consommees` of BAPOIA AE, are the only consumed column of their file, and the
  file does not say whether it is net of the credits restored. The check of the 2023 to 2025
  totals against the settlement laws ([#137](https://github.com/tryph0n/public-money-fr/issues/137))
  can answer it.
- The budget part `unsplit` in `state_revenue_lines` and `state_employment`:
  [#170](https://github.com/tryph0n/public-money-fr/issues/170).
- Voted annex budgets of 2010 and 2011: the shape of the attachment of the 2011 annex budget
  dataset (0 records) is not described yet, so its title groups are not known
  ([#132](https://github.com/tryph0n/public-money-fr/issues/132)).
