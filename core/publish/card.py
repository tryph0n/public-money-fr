"""Generate the dataset card of a Hugging Face dataset from the source manifest.

The card lists the tables, the inputs they come from with their producers, licences and the
date of their last update that the producer states, and the build date. It also carries the
notices that the licences ask for: for an input under CC BY 4.0, a link to the material and
what the project changed in its data, from the change notes that the code that builds each
table stores in the table; for an input with no declared licence, the basis of its reuse from
the manifest, the source and the date of its last update.
"""

import re
from collections.abc import Mapping, Sequence

import yaml

from core.fetch.adapters import DATA_GOUV, DEFAULT_BASE_URLS
from core.sources.manifest import LastUpdate, Source, is_not_declared
from core.tables.writer import TableMetadata

REPOSITORY_URL = "https://github.com/tryph0n/public-money-fr"
CARD_LICENCE = "etalab-2.0"
CC_BY_4 = "CC BY 4.0"
CC_BY_4_URL = "https://creativecommons.org/licenses/by/4.0/"
NO_LICENCE = "No licence declared"

_MARKUP = re.compile(r"([\\|\[\]])")


class CardError(ValueError):
    """The tables or the manifest lack what the card must state."""


def card_header(pretty_name: str, tables: Sequence[str] = ()) -> str:
    """Return the YAML metadata block of a dataset card.

    Args:
        pretty_name: Name of the dataset, for example `public-money-core`.
        tables: Table names; each gets a viewer configuration that reads
            `data/<table>.parquet`, so tables with different columns are shown apart.

    Returns:
        The YAML between two `---` lines, each line ending with a newline.
    """
    metadata: dict[str, object] = {
        "license": CARD_LICENCE,
        "language": ["fr"],
        "pretty_name": pretty_name,
    }
    if tables:
        metadata["configs"] = [
            {"config_name": table, "data_files": f"data/{table}.parquet"} for table in tables
        ]
    return "---\n" + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True) + "---\n"


def is_cc_by(source: Source) -> bool:
    """Tell whether an input is under CC BY 4.0.

    Args:
        source: The manifest entry.

    Returns:
        True if the licence name says CC BY 4.0.
    """
    return CC_BY_4 in source.licence.name


def source_page(source: Source) -> str:
    """Give the page that the files of an input come from.

    Args:
        source: The manifest entry.

    Returns:
        The page of the dataset on its portal, the page of a manual file, or the download
        URL of an archive.
    """
    access = source.access
    if access["kind"] == "manual":
        return str(access["page_url"])
    if access["kind"] == "archive":
        return str(access["download_url"])
    if access["kind"] == "data_gouv":
        return f"{DEFAULT_BASE_URLS[DATA_GOUV]}/datasets/{access['dataset_id']}/"
    return f"https://{access['portal']}/explore/dataset/{access['dataset_id']}/"


def licence_label(source: Source) -> str:
    """Give the licence of an input as a reader would name it.

    Args:
        source: The manifest entry.

    Returns:
        The licence name, or a plain statement when the producer declares none.
    """
    return NO_LICENCE if is_not_declared(source.licence.name) else source.licence.name


def _cell(text: str) -> str:
    return _MARKUP.sub(r"\\\1", " ".join(text.split()))


def _years(source: Source) -> str:
    if source.first_year == source.last_year:
        return str(source.first_year)
    return f"{source.first_year} to {source.last_year}"


def _notice(source: Source, last_update: LastUpdate, tables: Sequence[TableMetadata]) -> list[str]:
    users = [item for item in tables if source.id in item.source_ids]
    notes = [(item.table, item.changes[source.id]) for item in users if source.id in item.changes]
    paragraphs = []
    if is_cc_by(source):
        missing = [item.table for item in users if source.id not in item.changes]
        if missing:
            raise CardError(
                f"{source.id} is under {CC_BY_4}, which asks that changes be indicated, but "
                f"these tables give no change note for it: {', '.join(missing)}"
            )
        paragraphs.append(
            f"Credit: {source.producer}. Material: {source.title}, {source_page(source)}. "
            f"Licence: {CC_BY_4}, {CC_BY_4_URL}; stated at {source.licence.url}."
        )
    if is_not_declared(source.licence.name):
        paragraphs.append(f"{NO_LICENCE} by the producer.")
        if source.licence.basis:
            paragraphs.append(f"Basis of the reuse: {' '.join(source.licence.basis.split())}")
        paragraphs.append(f"Source: {source.title}, {source.producer}; {source_page(source)}")
        paragraphs.append(
            f"Date of its last update: {last_update.date.isoformat()}, as stated at "
            f"{last_update.url} ({last_update.where})."
        )
    if notes:
        changes = "\n".join(f"- {table}: {' '.join(note.split())}" for table, note in notes)
        paragraphs.append(f"Changes made by this project:\n\n{changes}")
    if not paragraphs:
        return []
    return [f"### {source.id}", "", "\n\n".join(paragraphs), ""]


def build_card(
    repo_name: str,
    tables: Sequence[TableMetadata],
    manifest: Mapping[str, Source],
) -> str:
    """Build the dataset card.

    Args:
        repo_name: Name of the dataset, for example `public-money-core`.
        tables: What each published table says about itself.
        manifest: The sources by id.

    Returns:
        The text of `README.md`: YAML metadata, the tables, the inputs with their licences and
        the date of their last update, and the notices that these licences ask for.

    Raises:
        CardError: If a table names a source id that the manifest does not have, an input has
            no date of last update stated by its producer, or a table that uses an input under
            CC BY 4.0 gives no change note for it.
    """
    ordered = sorted(tables, key=lambda item: item.table)
    ids = sorted({source_id for item in ordered for source_id in item.source_ids})
    unknown = [source_id for source_id in ids if source_id not in manifest]
    if unknown:
        raise CardError(f"source ids not in the manifest: {', '.join(unknown)}")
    sources = [manifest[source_id] for source_id in ids]
    dated = [(source, source.last_update) for source in sources if source.last_update]
    undated = [source.id for source in sources if source.last_update is None]
    if undated:
        raise CardError(
            "inputs with no date of last update stated by their producer (manifest field "
            f"last_update): {', '.join(undated)}"
        )
    lines = [
        card_header(repo_name, [item.table for item in ordered]),
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
            "The date of the last update is the one that the producer states, with a link to "
            "where it is stated.",
            "",
            "| Input | Producer | Years | Licence | Last update |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for source, last_update in dated:
        lines.append(
            f"| [{_cell(source.title)}]({source_page(source)}) ({source.id}) | "
            f"{_cell(source.producer)} | {_years(source)} | "
            f"[{_cell(licence_label(source))}]({source.licence.url}) | "
            f"[{last_update.date.isoformat()}]({last_update.url}) |"
        )
    notices = [line for source, last in dated for line in _notice(source, last, ordered)]
    if notices:
        lines.extend(["", "## Notices on the inputs", ""])
        lines.extend(notices)
    return "\n".join(lines).rstrip("\n") + "\n"
