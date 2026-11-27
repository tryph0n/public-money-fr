"""Run the command line with `uv run python -m core`."""

import sys

from core.cli import main

if __name__ == "__main__":
    sys.exit(main())
