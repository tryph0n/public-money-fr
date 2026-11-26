# Fixtures of the decoding and number-parsing helpers

Each file is a byte-for-byte extract of a real file, at most 30 lines, kept with its own
encoding and line ends (`.gitattributes` turns off any line-end conversion here). "Lines" are
line numbers of the source file, counting LF bytes, the header being line 1, and a range such
as `1-8` is kept in order. The datasets are on `data.economie.gouv.fr` (attachment with the
file name as title) unless the source column says otherwise; they were read on 26 November
2026.

| Fixture | Source | Lines |
| --- | --- | --- |
| `LFI2016-BG-Action_Titre.csv` | `loi-de-finances-initiale-pour-2016-lfi-2016` | 1-8 |
| `LFI2017-BG-Action_Titre.csv` | `loi-de-finances-initiale-pour-2017-lfi-2017` | 1-8 |
| `RBDE-2015-Ressource-budgetaire-CP.csv` | `https://www.ccomptes.fr/sites/default/files/EzPublish/RBDE-2015-Ressource-budgetaire-CP.csv` (Cour des comptes) | 1-5 |
| `LFI_2018_ACT_CAT_TIT_BG_CAS_CCF.csv` | `loi-de-finances-initiale-pour-2018-lfi-2018` | 1-6 |
| `LFI2020-crédits.csv` | `projet-de-loi-de-finances-initiale-pour-2020-lfi-2020` | 1-8, 2046 |
| `LFI2020-Emplois.csv` | same dataset | 1-8 |
| `LFI2020-Nomenclature.csv` | same dataset | 1-4, 2464-2468 (row 2465-2466 holds a line break in a quoted label) |
| `LFI2021_crédits-AE_CP.csv` | `projet-de-loi-de-finances-initiale-pour-2021-lfi-2021` | 1-6 |
| `LFI2022_detaillee.csv` | `projet-de-loi-de-finances-initiale-pour-2022-lfi-2022` | 1-6 |
| `PLR2015-Exec-Msn_CP-BG.csv` | data.gouv.fr dataset `57559e6c88ee382aa2640390`, resource `PLR2015-Exec-Msn_CP-BG.csv` | 1-8, 11 |
| `PLR2017-Exec-Msn_CP-BG.csv` | data.gouv.fr dataset `5b116de2c751df6f660cccab`, resource `PLR2017-Exec-Msn_CP-BG.csv` | 1-5 (the header spans lines 1-2), 1949-1950 (`#N/A`) |
| `Annexe1-Etat_CP-2023.csv` | `projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-lannee-plrg-2023` | 1-8 |
| `Annexe1-Etat_AE_CP-2023.csv` | same dataset | 1-30 (line 28 holds four cells in scientific notation) |
| `Annexe1-Etat_Titre_Cat-2023.csv` | same dataset | 1-3, 697 (one cell in scientific notation) |
| `Annexe1-Etat_Recettes-2023.csv` | same dataset | 1, 130-131, 294-296, 321-322, 437-439 (lines 295 and 438 hold a bare CR in a label; 131 and 322 hold cells in scientific notation) |
| `Annexe1-Etat_CP-2024.csv` | `plrg-2024` | 1-8 |
| `Annexe1-Etat_AE_CP-2024.csv` | same dataset | 1-3 |
| `Annexe1-Etat_Recettes.csv` | same dataset | 1-6 |
| `Annexe1-Etat_CP-2025.csv` | `projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-lannee-plrg-2025` | 1-8 |
| `Annexe1-Etat_Recettes 2025.csv` | same dataset | 1, 173-176 (line 175 holds the amount `-`) |
| `Séries longues SMB_DGFiP_2013-2023.csv` | `situations-mensuelles-budgetaires-series-longues` | 1-6, re-encoded as UTF-16 with a byte-order mark as the source is |

`scp_database_France.csv` is not a byte extract. The European Commission file
`scp_database.xlsx` (SHA-256 `0dcaad5fb9bfed63def53ccd8a0c1208e0253e21095c987c246d2a1683b91f54`,
<https://economy-finance.ec.europa.eu/document/download/0c4dc557-d980-449b-b3f0-76737a269615_en?filename=scp_database.xlsx>)
is a workbook, so this file writes sheet `SCPs database`, row 1 and rows 820-823 (the first
four `FR` rows) as `;`-delimited UTF-8 text. Cells that hold the text `NA` in the sheet hold
`NA` here; empty cells are empty.

There is no fixture for `PLR2020-Credits_Destination_Nature.xls`: it is a binary workbook and
cannot be cut to a few lines. The helpers read text files only.
