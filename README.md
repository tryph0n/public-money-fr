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

Publishing: `uv run python -m core publish [DATASET ...] [--dry-run]` uploads the built tables
of each named dataset (core, finance, security or election; all four if none is named), read
from `data/build/<dataset>/*.parquet` (`--build-dir`), in one commit for each dataset, with a card generated from the manifest (`core/publish/publisher.py`,
`core/publish/card.py`). A publish never deletes a file. If the dataset holds a table file
(`data/*.parquet`) that the publish does not hold, it stops before any upload with exit code 2
and names the file, so a publish gives every table of the dataset; other files, for example one
added by hand, stay and do not block. The card lists the tables, the inputs, producers,
licences, build date, and for each input the date of its last update that the producer states
(manifest field `last_update`); it refuses an input without that date. For a CC BY 4.0 input it
links the material and prints the change notes that the table builder stores with
`write_table(..., changes=...)`, and refuses the input without them. For an input with no
declared licence it gives the basis of reuse from the manifest, the source page and the date of
its last update. A second publish of the same content creates no commit, unless a file of the upload is missing
from the dataset (for example deleted by hand): that file is uploaded again, even when the content
did not change. A file changed by hand but still present is not detected. `--dry-run` prints the
files and the card and makes no network call; it does not read the dataset, so it shows neither
a refusal nor an unchanged hash. A network or Hub error ends the command with the error of the
library and a non-zero exit code. A real run reads the token from the `HF_TOKEN` environment
variable only; it is a GitHub Actions secret. A dataset with no registered builder is skipped
with a notice, so the command goes on. There is no filter by table: a publish gives every table
of the dataset.

A publish, the dry run included, also reads the lockfile (`--lock`, `sources.lock.json` by
default) and stops with exit code 2 when a pinned file of an input changed after its date of
last update was read: the manifest field `last_update.files` holds the SHA-256 of each file that
the date was read for, and the publish compares it with the lockfile (with the manifest
`sha256` for a manual file) in `core/publish/freshness.py`. Nothing is uploaded. The error names
the source, the files and `last_update.url`. After such a stop, read the date again at
`last_update.url`, update `last_update` in the manifest (`date`, `where`, `read_on`, `files`),
and commit it with the new lockfile in one pull request; the next run publishes.

## Develop

Install: `uv sync`

Test: `uv run pytest`

Check: `uv run ruff check .` and `uv run mypy core`

Run the application locally: `uv run streamlit run app/Home.py`, then open
<http://localhost:8501>.

### Fetch the sources

The command line is `uv run python -m core COMMAND` (`core/cli.py`); the page "Commands" of the
docs gives the help of each command, generated from the parser. Four commands, run in this
order:

- `fetch [source id ...]` fetches the sources of the manifest
  (`core/sources/`) into `data/raw/<source id>/` (git-ignored) and pins each file in
  `sources.lock.json` (size and SHA-256), which is committed. A file that the lockfile lists and
  whose bytes still match is not fetched again. `--offline` uses the cache only; `--force` fetches
  again. Resets and server errors are retried with backoff. A refusal (HTTP 401, 403 or 429, or a
  web page where data was asked for) stops the run with an error that names the host, with no
  retry. A source of kind `manual` is never downloaded: put the file in `data/manual/` (or in
  `data/raw/<source id>/`); it is copied and checked against the SHA-256 of the manifest.
- `build [table or dataset ...]` runs the registered table builders on the raw cache and writes
  `data/build/<dataset>/<table>.parquet` (`--build-dir`). A project registers builders through the
  entry point group `public_money_fr.builders`; with none registered, the command does nothing
  and exits 0.
- `validate [dataset ...]` reads the files of the build folders back and checks them against the
  schemas, the builders and the manifest; each problem is one line that names the file.
- `publish`: see Publishing above.

Exit codes: 0 on success (a command with nothing to do included); 1 when a source cannot be
fetched, a builder fails, or a real `publish` finds `HF_TOKEN` unset; 2 for a bad argument or an
unknown name, an invalid manifest, a missing lockfile, a table file that `validate` refuses, or a
publish that stops (a file that is not Parquet, two files for one table, a table that the dataset
holds and the publish does not, a stale date of last update).

### Write a shared table

`core.tables.schemas.SCHEMAS` holds one pandera schema for each shared table (column types,
allowed values, and the unit of each amount column in its description). `core.tables.writer.write_table`
checks a frame against the schema of its table and against the key of that table (a null counts as
one key value), then writes Parquet with the source ids, the build date and the git commit in the
file metadata. `read_metadata` reads them back. A frame that breaks a schema raises `TableError`,
which names the column, and no file is written.

A project writes its own table (a mart) with the same function: build a pandera schema
(rules of the whole frame come from `core.tables.schemas.frame_check`, which records the
columns that the error names) and pass it with the key of the table:
`write_table(frame, "my_mart", path, source_ids, schema=SCHEMA, key=("year", "code"))`.
The name must not be that of a shared table, and every column type must be one of int8,
Int8, int16, float64, bool, date or string; else `TableError` names the table, and the
column and the type. `core.publish` takes the file like a shared table and puts it in
`data/<table>.parquet` of the dataset of the project.

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
