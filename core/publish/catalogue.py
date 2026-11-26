"""Write the data catalogue pages of the documentation from the source manifest.

One Markdown page per manifest entry and one index table. The pages are build output: the
Sphinx build writes them before it reads the sources, so a new YAML file in
`core/sources/` adds a page with no edit of the documentation. The manifest loader refuses
an entry with a missing field, so a bad entry stops the build.
"""

import logging
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from core.sources.manifest import MANIFEST_DIR, Source, load_manifest

logger = logging.getLogger(__name__)

TABLE_FILE = "table.md"

_SPECIAL = re.compile(r"([\\`*_{}\[\]<>|#])")


def _escape(text: str) -> str:
    """Escape the characters that Markdown reads as markup, and join the lines."""
    return _SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _years(source: Source) -> str:
    if source.first_year == source.last_year:
        return str(source.first_year)
    return f"{source.first_year} to {source.last_year}"


def _access_lines(access: dict[str, object]) -> list[str]:
    lines = []
    for key, value in access.items():
        if isinstance(value, list):
            lines.append(f"- {_escape(key)}:")
            lines.extend(f"  - {_escape(str(item))}" for item in value)
        else:
            lines.append(f"- {_escape(key)}: {_escape(str(value))}")
    return lines


def render_page(source: Source) -> str:
    """Render the page of one source.

    Args:
        source: The manifest entry.

    Returns:
        The Markdown text of the page. Each trap is a warning block.
    """
    licence = source.licence
    lines = [
        f"# {_escape(source.id)}",
        "",
        _escape(source.title),
        "",
        "## Traps",
        "",
    ]
    for trap in source.traps:
        lines.extend(["```{warning}", _escape(trap), "```", ""])
    lines.extend(
        [
            "## Description",
            "",
            f"- Producer: {_escape(source.producer)}",
            f"- Years: {_years(source)}",
            f"- Grain: {_escape(source.grain)}",
            f"- Format: {_escape(source.format)}",
            f"- Encoding: {_escape(source.encoding)}",
            f"- Format generation: {_escape(source.generation)}",
            f"- Status: {source.status}",
            f"- Verified on: {source.verified_on.isoformat()}",
            "",
            "## Licence",
            "",
            f"- Name: {_escape(licence.name)}",
            f"- Stated at: <{licence.url}>",
            f"- Read on: {licence.read_on.isoformat()}",
        ]
    )
    if licence.basis is not None:
        lines.append(f"- Basis of reuse: {_escape(licence.basis)}")
    if licence.decision is not None:
        lines.append(f"- Decision: {_escape(licence.decision)}")
    lines.extend(["", "## Access", ""])
    lines.extend(_access_lines(source.access))
    lines.append("")
    return "\n".join(lines)


def render_table(sources: Iterable[Source], link_prefix: str = "") -> str:
    """Render the index table of the sources.

    Args:
        sources: The manifest entries.
        link_prefix: Text put before each page name in the links.

    Returns:
        The Markdown table, one row per source, each id linking to its page.
    """
    lines = [
        "| Source | Producer | Years | Grain | Licence | Status | Traps |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for source in sources:
        cells = [
            f"[{_escape(source.id)}]({link_prefix}{source.id}.md)",
            _escape(source.producer),
            _years(source),
            _escape(source.grain),
            _escape(source.licence.name),
            source.status,
            str(len(source.traps)),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def write_catalogue(
    output_dir: Path, manifest_dir: Path = MANIFEST_DIR, link_prefix: str = ""
) -> list[Path]:
    """Write the catalogue pages, replacing what the folder held.

    Args:
        output_dir: The folder of the pages. It is emptied first, so the page of a removed
            entry does not stay.
        manifest_dir: The folder of the manifest files.
        link_prefix: Text put before each page name in the links of the index table, for a
            table that a page of another folder includes.

    Returns:
        The paths of the written files, one page per source, then the index table.

    Raises:
        ManifestError: If an entry is not valid. Nothing is written then.
    """
    sources = load_manifest(manifest_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    written = []
    for source in sources.values():
        page = output_dir / f"{source.id}.md"
        page.write_text(render_page(source), encoding="utf-8")
        written.append(page)
    table = output_dir / TABLE_FILE
    table.write_text(render_table(sources.values(), link_prefix), encoding="utf-8")
    written.append(table)
    logger.info("Wrote %d catalogue pages to %s", len(sources), output_dir)
    return written
