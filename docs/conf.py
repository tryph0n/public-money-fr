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
}

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
templates_path = ["_templates"]
exclude_patterns = ["_build"]

html_theme = "furo"
