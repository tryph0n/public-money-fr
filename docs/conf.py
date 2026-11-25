project = "public-money-fr"
author = "tryph0n"
copyright = "2026, tryph0n"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
]

autosummary_generate = True
autodoc_member_order = "bysource"
nitpicky = True

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
templates_path = ["_templates"]
exclude_patterns = ["_build"]

html_theme = "furo"
