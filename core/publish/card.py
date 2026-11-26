"""Generate the dataset card of a Hugging Face dataset from the source manifest.

The card lists the tables, the inputs they come from with their producers and licences, and
the build date. It also carries the notices that two kinds of licence ask for: for an input
under CC BY 4.0, what the project changed in the data; for an input reused under articles
L321-1 and L322-1 of the code des relations entre le public et l'administration, the source
and the date of its last update.
"""

import datetime
from collections.abc import Mapping, Sequence

from core.fetch.lockfile import Lockfile
from core.sources.manifest import NOT_DECLARED, Source
from core.tables.writer import TableMetadata

REPOSITORY_URL = "https://github.com/tryph0n/public-money-fr"
CC_BY_4 = "CC BY 4.0"
CC_BY_4_URL = "https://creativecommons.org/licenses/by/4.0/"

CC_BY_CHANGES = (
    "Changes made by this project: it kept only the series listed for this input, turned the "
    "table with one column per year into one row per year, typed the columns, flagged the "
    "years after the last closed year as forecasts, and converted amounts given in billions of "
    "euros to euros. No other value was changed."
)


class CardError(ValueError):
    """A table names a source that the manifest does not know."""


def is_cc_by(source: Source) -> bool:
    """Tell whether an input is under CC BY 4.0.

    Args:
        source: The manifest entry.

    Returns:
        True if the licence name says CC BY 4.0.
    """
    return CC_BY_4 in source.licence.name


def is_crpa(source: Source) -> bool:
    """Tell whether an input is reused under articles L321-1 and L322-1 of the CRPA.

    Args:
        source: The manifest entry.

    Returns:
        True if the source declares no licence; the manifest loader then requires the basis.
    """
    return " ".join(source.licence.name.split()).casefold() == NOT_DECLARED


def last_update(source: Source, lockfile: Lockfile) -> datetime.date:
    """Give the date of the last update of an input that the project knows.

    Args:
        source: The manifest entry.
        lockfile: The lockfile of the raw files.

    Returns:
        The latest day on which the project stored a changed copy of one of the files of the
        source; the day the manifest entry was verified if the lockfile has no file for it.
    """
    days = [
        datetime.date.fromisoformat(item.retrieved_on)
        for item in lockfile.entries.get(source.id, {}).values()
    ]
    return max(days) if days else source.verified_on


def _years(source: Source) -> str:
    if source.first_year == source.last_year:
        return str(source.first_year)
    return f"{source.first_year} to {source.last_year}"


def _notice(source: Source, lockfile: Lockfile) -> list[str]:
    lines = []
    if is_cc_by(source):
        series = source.access.get("series")
        lines.append(f"### {source.id}")
        lines.append("")
        lines.append(
            f"Credit: {source.producer}. Licence: {source.licence.name}, {CC_BY_4_URL}; "
            f"stated at {source.licence.url}."
        )
        if series:
            lines.append("")
            lines.append(f"Series kept: {', '.join(series)}.")
        lines.append("")
        lines.append(CC_BY_CHANGES)
        lines.append("")
    if is_crpa(source):
        lines.append(f"### {source.id}")
        lines.append("")
        lines.append(
            "Reused under articles L321-1 and L322-1 of the code des relations entre le public "
            "et l'administration. The meaning of the information is not distorted."
        )
        lines.append("")
        lines.append(f"Source: {source.title}, {source.producer}; {source.licence.url}.")
        lines.append("")
        lines.append(f"Date of its last update: {last_update(source, lockfile).isoformat()}.")
        lines.append("")
    return lines


def build_card(
    repo_name: str,
    tables: Sequence[TableMetadata],
    manifest: Mapping[str, Source],
    lockfile: Lockfile,
) -> str:
    """Build the dataset card.

    Args:
        repo_name: Name of the dataset, for example `public-money-core`.
        tables: What each published table says about itself.
        manifest: The sources by id.
        lockfile: The lockfile of the raw files, for the date of the last update of an input.

    Returns:
        The text of `README.md`: YAML metadata, the tables, the inputs with their licences,
        and the notices that these licences ask for.

    Raises:
        CardError: If a table names a source id that the manifest does not have.
    """
    ordered = sorted(tables, key=lambda item: item.table)
    ids = sorted({source_id for item in ordered for source_id in item.source_ids})
    unknown = [source_id for source_id in ids if source_id not in manifest]
    if unknown:
        raise CardError(f"source ids not in the manifest: {', '.join(unknown)}")
    sources = [manifest[source_id] for source_id in ids]
    lines = [
        "---",
        "license: etalab-2.0",
        "language:",
        "- fr",
        f"pretty_name: {repo_name}",
        "---",
        "",
        f"# {repo_name}",
        "",
        "Open data on French public money, processed and published by the public-money-fr "
        f"project. Source code and documentation: {REPOSITORY_URL}",
        "",
        "## Tables",
        "",
        "| Table | File | Built on | Inputs |",
        "| --- | --- | --- | --- |",
    ]
    for item in ordered:
        lines.append(
            f"| {item.table} | data/{item.table}.parquet | {item.build_date} | "
            f"{', '.join(item.source_ids)} |"
        )
    lines.extend(
        [
            "",
            "## Inputs",
            "",
            "| Input | Producer | Years | Licence | Licence stated at |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for source in sources:
        lines.append(
            f"| {source.title} ({source.id}) | {source.producer} | {_years(source)} | "
            f"{source.licence.name} | {source.licence.url} |"
        )
    notices = [line for source in sources for line in _notice(source, lockfile)]
    if notices:
        lines.extend(["", "## Notices on the inputs", ""])
        lines.extend(notices)
    return "\n".join(lines).rstrip("\n") + "\n"
