# public-money-fr

Open data projects on French public money. Three projects share one package, `core`.
Each project answers one question.

## The three questions

1. **Public finance** (`projects/public_finance`): do successive governments do what they say
   they will do? Is what they vote, then what they do, consistent with the State's finances at
   that time?
2. **Security** (`projects/security_means`): does the State keep its own commitments on
   security means? What can be shown to reduce insecurity?
3. **Election 2027** (`projects/election_2027`): are the figures that the candidates put
   forward consistent with the real accounts of France?

## Status

This repository is a skeleton. It builds no table yet. The application is a walking skeleton:
its pages are in French and are empty.

Public URL: <https://public-money-fr.onrender.com>. It is a free Render instance: it
sleeps after 15 minutes without a visit and takes about a minute to wake. Render
redeploys it on each push to `main`.

Documentation: <https://public-money-fr.readthedocs.io/en/latest/>. Read the Docs builds it
from `main`. The section pages are empty for now; the API reference lists the `core` package.
The data catalogue is generated from the source manifest at each build (`core/publish/catalogue.py`,
called from `docs/conf.py`): one page per `core/sources/*.yaml` file, in `docs/_generated/`
(git-ignored). An entry that breaks a manifest rule, such as a missing licence, fails the build.

Continuous integration (`.github/workflows/ci.yml`) runs ruff (lint and format check), mypy,
pytest and the docs build on each pull request and on each push to `main`.

Datasets: four public datasets on Hugging Face, in the `sam-bot` namespace. Each one holds
only its card (`README.md`) and `.gitattributes`.

| Dataset | Holds a table |
| --- | --- |
| [`sam-bot/public-money-core`](https://huggingface.co/datasets/sam-bot/public-money-core) | No |
| [`sam-bot/public-money-finance`](https://huggingface.co/datasets/sam-bot/public-money-finance) | No |
| [`sam-bot/public-money-security`](https://huggingface.co/datasets/sam-bot/public-money-security) | No |
| [`sam-bot/public-money-election`](https://huggingface.co/datasets/sam-bot/public-money-election) | No |

## Develop

Install: `uv sync`

Test: `uv run pytest`

Check: `uv run ruff check .` and `uv run mypy core`

Run the application locally: `uv run streamlit run app/Home.py`, then open
<http://localhost:8501>.

### Fetch the sources

`uv run python -m core.cli fetch [source id ...]` fetches the sources of the manifest
(`core/sources/`) into `data/raw/<source id>/` (git-ignored) and pins each file in
`sources.lock.json` (size and SHA-256), which is committed. A file that the lockfile lists and
whose bytes still match is not fetched again. `--offline` uses the cache only; `--force` fetches
again. Resets and server errors are retried with backoff. A refusal (HTTP 401, 403 or 429, or a
web page where data was asked for) stops the run with an error that names the host, with no
retry. A source of kind `manual` is never downloaded: put the file in `data/manual/` (or in
`data/raw/<source id>/`); it is copied and checked against the SHA-256 of the manifest.

### Docstring style

Docstrings in `core` use the [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
Sphinx renders the `Args`, `Returns` and `Raises` sections as a parameter list on the API
reference page (`sphinx.ext.napoleon`). Ruff checks the style (`D` rules, Google convention);
it does not require a docstring on every object.

Write types in the function signature, not in the docstring. Mypy checks the annotations, a
copy in the docstring can drift from them, and a docstring type such as `int, optional`
breaks the docs build (`nitpicky` mode).

```python
def share(part: float, total: float) -> float:
    """Return a part as a share of a total.

    Args:
        part: Amount of the part, in euros.
        total: Amount of the total, in euros.

    Returns:
        The share, between 0 and 1.

    Raises:
        ValueError: If `total` is zero.
    """
```

Build the docs as CI does:
`uv run --locked --group docs sphinx-build -W --keep-going -b html docs docs/_build/html`.

### Pull requests

Each pull request answers the side-effects checklist of `.github/pull_request_template.md`:
for the README, the docs, the CI, the data pipeline and the other shared files, it updates each
one that the change affects in the same pull request, or says why no update is needed.

The web form and an interactive `gh pr create` offer the template. A body given with `--body`,
`--body-file` or to the REST API does not get it. So a pull request created from a terminal or with the REST API
takes a copy of the template as its body and answers each line: copy the file, answer each
line, then run `gh pr create --title "..." --body-file <file>`.

## Licence

Apache-2.0. See `LICENSE`.
