# Data catalogue

The catalogue lists the sources of the datasets that the projects publish: producer, years, grain,
licence, status and traps. The Sphinx build writes it from the source manifest
(`core/sources/*.yaml`): one page per source and the table below. A new manifest file adds a page.

The data is also available as Hugging Face datasets and through the application:

- Application: <https://public-money-fr.onrender.com>.
- Source code: <https://github.com/tryph0n/public-money-fr>.
- Datasets, in the `sam-bot` namespace:
  [public-money-core](https://huggingface.co/datasets/sam-bot/public-money-core),
  [public-money-finance](https://huggingface.co/datasets/sam-bot/public-money-finance),
  [public-money-security](https://huggingface.co/datasets/sam-bot/public-money-security) and
  [public-money-election](https://huggingface.co/datasets/sam-bot/public-money-election).
  They hold no table yet.

## Sources

```{include} _generated/catalogue/table.md
```

```{toctree}
:glob:
:hidden:

_generated/catalogue/*
```
