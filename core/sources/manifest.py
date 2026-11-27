"""Load and validate the source manifest.

The manifest is one YAML file per source in this folder. It is the only place where a
dataset id, a URL and a licence are written: code and tickets refer to a manifest id. A
file that breaks a rule stops the load with an error that names the file and the field.

The field `last_update` holds the date of the last update that the producer states, and where
it was read; the dataset card prints it. It is empty (null) when the producer states no usable
date, and a card then refuses the source. The files are pinned by checksum, so the date must be
read again each time a pin changes: a new SHA-256 in `sources.lock.json` or in the manifest.
`last_update.files` records the SHA-256 of the files the date was read for; a publish stops when
a pinned file no longer matches it (`core/publish/freshness.py`).
"""

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MANIFEST_DIR = Path(__file__).parent

#: Licence name that a portal reports for a dataset with no declared licence. The loader
#: compares it after it removes the case and the extra spaces.
NOT_DECLARED = "notspecified"

STATUSES = ("verified", "reported")

#: For each kind of access, the keys it needs.
ACCESS_KINDS: dict[str, tuple[str, ...]] = {
    "records": ("portal", "dataset_id"),
    "attachments": ("portal", "dataset_id", "files"),
    "data_gouv": ("dataset_id", "files"),
    "archive": ("download_url", "member", "series"),
    "manual": ("page_url", "download_url", "sha256"),
}

_FIELDS = (
    "id",
    "title",
    "producer",
    "access",
    "licence",
    "last_update",
    "grain",
    "years",
    "format",
    "encoding",
    "generation",
    "traps",
    "status",
    "verified_on",
)
_LICENCE_REQUIRED = ("name", "url", "read_on")
_LICENCE_BASIS = ("basis", "decision")
_LAST_UPDATE = ("date", "url", "where", "read_on", "files")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ManifestError(ValueError):
    """A manifest file breaks a rule; the message names the file and the field."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader that refuses a key written twice in the same mapping."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.YAMLError(f"line {key_node.start_mark.line + 1}: duplicate key {key!r}")
            seen.add(key)
        return super().construct_mapping(node, deep)


def is_not_declared(name: str) -> bool:
    """Tell whether a licence name is the one a portal reports for no declared licence.

    Args:
        name: The licence name of a manifest entry.

    Returns:
        True if the name is `notspecified`, ignoring the case and the extra spaces.
    """
    return " ".join(name.split()).casefold() == NOT_DECLARED


@dataclass(frozen=True)
class Licence:
    """The licence of a source and where and when it was read."""

    name: str
    #: The producer's page that states the licence.
    url: str
    read_on: datetime.date
    #: The legal basis of reuse, for a source with no declared licence.
    basis: str | None = None
    #: The decision that allows the reuse, for a source with no declared licence.
    decision: str | None = None


@dataclass(frozen=True)
class LastUpdate:
    """The date of the last update that the producer states, and where it was read."""

    date: datetime.date
    #: The page, API answer or document that states the date.
    url: str
    #: Where the date is on that page or in that document, for example the field name.
    where: str
    read_on: datetime.date
    #: SHA-256 of each file of the source (by file key) that the date was read for. A publish
    #: stops when a pinned file differs from this record.
    files: dict[str, str]


@dataclass(frozen=True)
class Source:
    """One entry of the manifest."""

    id: str
    title: str
    producer: str
    access: dict[str, Any]
    licence: Licence
    #: None when the producer states no usable date; a dataset card then refuses the source.
    last_update: LastUpdate | None
    grain: str
    first_year: int
    last_year: int
    format: str
    encoding: str
    generation: str
    traps: tuple[str, ...]
    status: str
    verified_on: datetime.date


def _text(value: Any, where: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{path.name}: {where}: must be a non-empty text")
    return value


def _date(value: Any, where: str, path: Path) -> datetime.date:
    if not isinstance(value, datetime.date) or isinstance(value, datetime.datetime):
        raise ManifestError(f"{path.name}: {where}: must be a date written YYYY-MM-DD")
    if value > datetime.date.today():
        raise ManifestError(f"{path.name}: {where}: must not be in the future")
    return value


def _mapping(value: Any, where: str, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path.name}: {where}: must be a mapping")
    return value


def _check_keys(
    data: dict[str, Any],
    required: tuple[str, ...],
    optional: tuple[str, ...],
    where: str,
    path: Path,
) -> None:
    prefix = f"{where}." if where else ""
    for key in required:
        if key not in data:
            raise ManifestError(f"{path.name}: {prefix}{key}: missing")
    for key in data:
        if key not in required and key not in optional:
            raise ManifestError(f"{path.name}: {prefix}{key}: unknown field")


def _text_list(value: Any, where: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{path.name}: {where}: must be a non-empty list of texts")
    return tuple(_text(item, f"{where}[{i}]", path) for i, item in enumerate(value))


def _access(value: Any, path: Path) -> dict[str, Any]:
    access = _mapping(value, "access", path)
    kind = access.get("kind")
    if kind not in ACCESS_KINDS:
        raise ManifestError(
            f"{path.name}: access.kind: must be one of {', '.join(ACCESS_KINDS)}, got {kind!r}"
        )
    required = ACCESS_KINDS[kind]
    _check_keys(
        {key: item for key, item in access.items() if key != "kind"},
        required,
        (),
        "access",
        path,
    )
    for key in required:
        if key in ("files", "series"):
            _text_list(access[key], f"access.{key}", path)
        else:
            _text(access[key], f"access.{key}", path)
    return access


def _licence(value: Any, path: Path) -> Licence:
    data = _mapping(value, "licence", path)
    _check_keys(data, _LICENCE_REQUIRED, _LICENCE_BASIS, "licence", path)
    name = _text(data["name"], "licence.name", path)
    basis = data.get("basis")
    decision = data.get("decision")
    if is_not_declared(name):
        for key in _LICENCE_BASIS:
            if key not in data:
                raise ManifestError(
                    f"{path.name}: licence.{key}: missing; a source with no declared licence "
                    "needs the basis of reuse and the decision that allows it"
                )
    return Licence(
        name=name,
        url=_text(data["url"], "licence.url", path),
        read_on=_date(data["read_on"], "licence.read_on", path),
        basis=None if basis is None else _text(basis, "licence.basis", path),
        decision=None if decision is None else _text(decision, "licence.decision", path),
    )


def _last_update(value: Any, path: Path) -> LastUpdate | None:
    if value is None:
        return None
    data = _mapping(value, "last_update", path)
    _check_keys(data, _LAST_UPDATE, (), "last_update", path)
    date = _date(data["date"], "last_update.date", path)
    read_on = _date(data["read_on"], "last_update.read_on", path)
    if date > read_on:
        raise ManifestError(f"{path.name}: last_update.date: must not be after its read_on date")
    files = _mapping(data["files"], "last_update.files", path)
    if not files:
        raise ManifestError(f"{path.name}: last_update.files: must not be empty")
    for key, digest in files.items():
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ManifestError(
                f"{path.name}: last_update.files.{key}: must be a SHA-256 in lowercase hexadecimal"
            )
    return LastUpdate(
        date=date,
        url=_text(data["url"], "last_update.url", path),
        where=_text(data["where"], "last_update.where", path),
        read_on=read_on,
        files=dict(files),
    )


def _years(value: Any, path: Path) -> tuple[int, int]:
    data = _mapping(value, "years", path)
    _check_keys(data, ("first", "last"), (), "years", path)
    for key in ("first", "last"):
        if not isinstance(data[key], int) or isinstance(data[key], bool):
            raise ManifestError(f"{path.name}: years.{key}: must be a whole year")
    if data["first"] > data["last"]:
        raise ManifestError(f"{path.name}: years.last: must not be before years.first")
    return data["first"], data["last"]


def load_source(path: Path) -> Source:
    """Read and validate one manifest file.

    Args:
        path: The YAML file. Its name without the extension must equal the `id` field.

    Returns:
        The validated source.

    Raises:
        ManifestError: If the file is not valid YAML or breaks a rule. The message starts
            with the file name and names the field.
    """
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise ManifestError(f"{path.name}: not valid YAML: {error}") from error
    data = _mapping(data, "file", path)
    _check_keys(data, _FIELDS, (), "", path)
    source_id = _text(data["id"], "id", path)
    if source_id != path.stem:
        raise ManifestError(f"{path.name}: id: {source_id!r} must equal the file name")
    status = _text(data["status"], "status", path)
    if status not in STATUSES:
        raise ManifestError(f"{path.name}: status: must be one of {', '.join(STATUSES)}")
    first_year, last_year = _years(data["years"], path)
    return Source(
        id=source_id,
        title=_text(data["title"], "title", path),
        producer=_text(data["producer"], "producer", path),
        access=_access(data["access"], path),
        licence=_licence(data["licence"], path),
        last_update=_last_update(data["last_update"], path),
        grain=_text(data["grain"], "grain", path),
        first_year=first_year,
        last_year=last_year,
        format=_text(data["format"], "format", path),
        encoding=_text(data["encoding"], "encoding", path),
        generation=_text(data["generation"], "generation", path),
        traps=_text_list(data["traps"], "traps", path),
        status=status,
        verified_on=_date(data["verified_on"], "verified_on", path),
    )


def load_manifest(directory: Path = MANIFEST_DIR) -> dict[str, Source]:
    """Read and validate every `*.yaml` file of a folder.

    Args:
        directory: The folder of the manifest files.

    Returns:
        The sources by id, in the order of the file names.

    Raises:
        ManifestError: If a file is not valid, with the file name and the field.
    """
    return {source.id: source for source in map(load_source, sorted(directory.glob("*.yaml")))}
