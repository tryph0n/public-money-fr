"""One adapter per access kind of the source manifest.

An adapter turns the `access` block of a source into downloads. Dataset ids, portal names and
file URLs come from the manifest; this module knows only the shape of each portal API.
"""

import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from core.fetch.http import EmptyBodyError, FetchError, HttpClient, host_of
from core.sources.manifest import Source

#: Name of the data.gouv.fr API in `base_urls`; the manifest gives no portal for this kind.
DATA_GOUV = "data.gouv.fr"

#: Where a portal API lives when the caller gives no other base URL. An Opendatasoft portal
#: is `https://<portal>`, with the portal name taken from the manifest.
DEFAULT_BASE_URLS = {DATA_GOUV: "https://www.data.gouv.fr"}

#: Key and file name of the records export, which has no name in the manifest.
RECORDS_KEY = "records"
RECORDS_FILE = "records.json"


def manual_name(source: Source) -> str:
    """Return the file name of a file placed by hand.

    Args:
        source: A source of kind `manual`.

    Returns:
        The `filename` parameter of the download URL, else the last part of its path.
    """
    parts = urlsplit(source.access["download_url"])
    names = parse_qs(parts.query).get("filename")
    return names[0] if names else unquote(PurePosixPath(parts.path).name)


def file_keys(source: Source) -> tuple[str, ...]:
    """Return the keys of the files of a source, without any network call.

    A key is the name that the manifest gives the file: the title for an attachment or a
    data.gouv.fr resource, the member for an archive, the file name for a manual file.

    Args:
        source: Any source.

    Returns:
        The keys, in the order of the manifest.
    """
    kind = source.access["kind"]
    if kind == "records":
        return (RECORDS_KEY,)
    if kind in ("attachments", "data_gouv"):
        return tuple(source.access["files"])
    if kind == "archive":
        return (source.access["member"],)
    return (manual_name(source),)


def _base(portal: str, base_urls: dict[str, str]) -> str:
    return base_urls.get(portal, f"https://{portal}").rstrip("/")


def _json(client: HttpClient, url: str) -> Any:
    try:
        return json.loads(client.get(url))
    except json.JSONDecodeError as error:
        raise FetchError(f"{host_of(url)}: the answer is not JSON: {url}") from error


def _safe_name(name: str, url: str) -> str:
    if not name or PurePosixPath(name).name != name or name in (".", ".."):
        raise FetchError(f"{host_of(url)}: unsafe file name {name!r} from {url}")
    return name


def _records(
    source: Source, client: HttpClient, base_urls: dict[str, str]
) -> dict[str, tuple[str, bytes]]:
    base = _base(source.access["portal"], base_urls)
    dataset = quote(source.access["dataset_id"])
    url = f"{base}/api/explore/v2.1/catalog/datasets/{dataset}/exports/json"
    return {RECORDS_KEY: (RECORDS_FILE, client.get(url))}


def _attachments(
    source: Source, keys: list[str], client: HttpClient, base_urls: dict[str, str]
) -> dict[str, tuple[str, bytes]]:
    base = _base(source.access["portal"], base_urls)
    listing_url = (
        f"{base}/api/explore/v2.1/catalog/datasets/{quote(source.access['dataset_id'])}/attachments"
    )
    listed = _json(client, listing_url).get("attachments", [])
    by_title = {item["metas"]["title"]: item["href"] for item in listed}
    found: dict[str, tuple[str, bytes]] = {}
    for title in keys:
        if title not in by_title:
            raise FetchError(f"{host_of(listing_url)}: no attachment titled {title!r}")
        found[title] = (_safe_name(title, listing_url), client.get(by_title[title]))
    return found


def _data_gouv(
    source: Source, keys: list[str], client: HttpClient, base_urls: dict[str, str]
) -> dict[str, tuple[str, bytes]]:
    base = _base(DATA_GOUV, base_urls)
    dataset_url = f"{base}/api/1/datasets/{quote(source.access['dataset_id'])}/"
    resources = _json(client, dataset_url).get("resources", [])
    by_title: dict[str, list[str]] = {}
    for resource in resources:
        by_title.setdefault(resource["title"], []).append(resource["url"])
    found: dict[str, tuple[str, bytes]] = {}
    for title in keys:
        urls = by_title.get(title, [])
        if len(urls) != 1:
            raise FetchError(
                f"{host_of(dataset_url)}: {len(urls)} resources titled {title!r}, expected one"
            )
        name = unquote(PurePosixPath(urlsplit(urls[0]).path).name)
        found[title] = (_safe_name(name, urls[0]), client.get(urls[0]))
    return found


def _archive(source: Source, client: HttpClient) -> dict[str, tuple[str, bytes]]:
    url = source.access["download_url"]
    member = source.access["member"]
    try:
        with zipfile.ZipFile(io.BytesIO(client.get(url))) as archive:
            data = archive.read(member)
    except zipfile.BadZipFile as error:
        raise FetchError(f"{host_of(url)}: not a zip file: {url}") from error
    except KeyError as error:
        raise FetchError(f"{host_of(url)}: no member {member!r} in the archive {url}") from error
    if not data:
        raise EmptyBodyError(f"{host_of(url)}: zero-byte member {member!r} in {url}")
    return {member: (_safe_name(member, url), data)}


def download(
    source: Source,
    keys: list[str],
    client: HttpClient,
    base_urls: dict[str, str] = DEFAULT_BASE_URLS,
) -> dict[str, tuple[str, bytes]]:
    """Download some files of a source.

    Args:
        source: A source of kind `records`, `attachments`, `data_gouv` or `archive`.
        keys: The keys to download, taken from `file_keys`.
        client: The HTTP client.
        base_urls: Base URL of a portal by portal name (and of data.gouv.fr by `DATA_GOUV`).
            A portal that is not listed is `https://<portal>`.

    Returns:
        For each key, the file name to store and the bytes.

    Raises:
        FetchError: If a file cannot be found or is not what the manifest says.
        RefusalError: If a host refuses.
    """
    kind = source.access["kind"]
    if kind == "records":
        return _records(source, client, base_urls)
    if kind == "attachments":
        return _attachments(source, keys, client, base_urls)
    if kind == "data_gouv":
        return _data_gouv(source, keys, client, base_urls)
    if kind == "archive":
        return _archive(source, client)
    raise FetchError(f"{source.id}: kind {kind!r} cannot be downloaded")
