<!--
The web form and an interactive `gh pr create` offer this template. A body given with --body,
--body-file or to the REST API does not get it. From a terminal or the REST API, copy this file to a body file,
answer each line, then run: gh pr create --title "..." --body-file <file>
-->

<!-- Write "Part of #<issue number>" instead when this pull request does not finish the issue. -->
Closes #

## Why

## What changed

## Acceptance

<!-- Each box of the issue, ticked, with how it was checked. -->

## Claims and proofs

<!-- One line for each behaviour claim: the test or run that fails if the claim is false. -->

## Defaults taken

## Side effects

<!-- Answer each line. Tick it when it is answered. -->

- [ ] README (`README.md`): updated in this pull request (say what), or no update needed (say why):
- [ ] Docs (`docs/`, the Read the Docs site): updated in this pull request (say what), or no update needed (say why):
- [ ] CI (`.github/workflows/`): updated in this pull request (say what), or no update needed (say why):
- [ ] Data pipeline (refresh workflow, source manifest, data catalogue): updated in this pull request (say what), or no update needed (say why):
- [ ] Other shared files (for example `pyproject.toml`, `uv.lock`, `render.yaml`, `.readthedocs.yaml`, this template): updated in this pull request (say what), or no update needed (say why):
- [ ] Parser of a manual source (kind `manual`): this pull request does not change it, or it gives here the output of `uv run pytest tests/test_manual_rows.py` run on a machine that has the raw file in `data/manual/` (CI never has the raw file), and the committed rows of the source are extracted again:
