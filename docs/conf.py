from pathlib import Path

from sphinx.application import Sphinx
from sphinx.errors import ExtensionError

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

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
templates_path = ["_templates"]
exclude_patterns = ["_build", f"_generated/catalogue/{TABLE_FILE}"]

html_theme = "furo"

CATALOGUE_DIR = Path(__file__).parent / "_generated" / "catalogue"


def write_catalogue_pages(app: Sphinx) -> None:
    """Write the catalogue pages from the manifest before Sphinx reads the sources."""
    try:
        write_catalogue(CATALOGUE_DIR, link_prefix="_generated/catalogue/")
    except ManifestError as error:
        raise ExtensionError(f"source manifest: {error}") from error


def setup(app: Sphinx) -> None:
    app.connect("builder-inited", write_catalogue_pages)
