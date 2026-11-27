import argparse
import os
from pathlib import Path

from sphinx.application import Sphinx
from sphinx.errors import ExtensionError

from core.cli import build_parser
from core.publish.catalogue import TABLE_FILE, write_catalogue
from core.sources.manifest import ManifestError

project = "public-money-fr"
author = "tryph0n"
copyright = "2026, tryph0n"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
]

autosummary_generate = True
autodoc_member_order = "bysource"
nitpicky = True

# nitpicky fails the build on a type it cannot link. When a library type appears in a core
# signature, add one line for that library here (name: (docs URL, None)).
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
}

# The publisher protocol names a huggingface_hub class under its private module path, which
# the library's documentation inventory does not list. The table writer names two pandera types
# in its signatures; pandera has no inventory in the mapping.
nitpick_ignore = [
    ("py:class", "huggingface_hub._commit_api.CommitOperationAdd"),
    ("py:class", "pandera.api.checks.Check"),
    ("py:class", "pandera.api.pandas.container.DataFrameSchema"),
]

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
templates_path = ["_templates"]
exclude_patterns = ["_build", f"_generated/catalogue/{TABLE_FILE}"]

html_theme = "furo"

CATALOGUE_DIR = Path(__file__).parent / "_generated" / "catalogue"
CLI_PAGE = Path(__file__).parent / "_generated" / "cli.md"


def write_catalogue_pages(app: Sphinx) -> None:
    """Write the catalogue pages from the manifest before Sphinx reads the sources."""
    try:
        write_catalogue(CATALOGUE_DIR, link_prefix="_generated/catalogue/")
    except ManifestError as error:
        raise ExtensionError(f"source manifest: {error}") from error


def write_cli_page(app: Sphinx) -> None:
    """Write the page with the help of each command from the parser of the command line."""
    parser = build_parser()
    commands = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    # argparse wraps its help at the terminal width; fix it so that the page does not vary.
    os.environ["COLUMNS"] = "100"
    parts = [
        "# Commands\n",
        "Generated from the parser of the command line (`core/cli.py`) when the docs are built. "
        "Run a command with `uv run python -m core COMMAND`.\n",
        f"## core\n\n```text\n{parser.format_help()}```\n",
    ]
    for name, command in commands.choices.items():
        parts.append(f"## core {name}\n\n```text\n{command.format_help()}```\n")
    CLI_PAGE.parent.mkdir(parents=True, exist_ok=True)
    CLI_PAGE.write_text("\n".join(parts), encoding="utf-8")


def setup(app: Sphinx) -> None:
    app.connect("builder-inited", write_catalogue_pages)
    app.connect("builder-inited", write_cli_page)
