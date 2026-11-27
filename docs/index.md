# public-money-fr

Open data projects on French public money, built on a shared core package.

- Application: <https://public-money-fr.onrender.com>. Its pages are in French and show no data
  yet. It runs on a free instance: after 15 minutes without a visit, the first page takes
  about a minute to load.
- Source code: <https://github.com/tryph0n/public-money-fr>.
- Datasets, on Hugging Face in the `sam-bot` namespace:
  [public-money-core](https://huggingface.co/datasets/sam-bot/public-money-core),
  [public-money-finance](https://huggingface.co/datasets/sam-bot/public-money-finance),
  [public-money-security](https://huggingface.co/datasets/sam-bot/public-money-security) and
  [public-money-election](https://huggingface.co/datasets/sam-bot/public-money-election).
  They hold no table yet.

```{toctree}
:maxdepth: 2
:caption: Contents

catalogue
_generated/cli
methods
state_budget_model
public_finance
security_means
election_2027
api/index
```
