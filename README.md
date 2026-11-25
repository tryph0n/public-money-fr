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

This repository is a skeleton. It has no data and no application yet.

## Develop

Install: `uv sync`

Test: `uv run pytest`

Check: `uv run ruff check .` and `uv run mypy core`

## Licence

Apache-2.0. See `LICENSE`.
