import dataclasses
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest

from core.fetch.adapters import DATA_GOUV, file_keys, manual_name
from core.fetch.fetcher import Fetcher
from core.fetch.http import FetchError, HttpClient, OfflineError, RefusalError
from core.fetch.lockfile import sha256_of
from core.sources.manifest import MANIFEST_DIR, Source, load_manifest
from tests.fake_server import FakeServer, body, running_server

PORTAL = "data.economie.gouv.fr"
MANUAL_ID = "stability-programme-france-2016"


@pytest.fixture
def server() -> Iterator[FakeServer]:
    with running_server() as fake:
        yield fake


def make_zip(member: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, data)
    return buffer.getvalue()


def serve_manifest(
    server: FakeServer, sources: dict[str, Source], manual_dir: Path
) -> dict[str, Source]:
    """Serve the five manifest entries on the fake server and point them at it."""
    ods = "/api/explore/v2.1/catalog/datasets"
    patched: dict[str, Source] = {}
    for source_id, source in sources.items():
        access = dict(source.access)
        kind = access["kind"]
        if kind == "records":
            server.serve(
                f"{ods}/{access['dataset_id']}/exports/json",
                body(b'[{"a": 1}]', "application/json"),
            )
        elif kind == "attachments":
            listing = [
                {"href": f"{server.url}/att/{quote(title)}", "metas": {"title": title}}
                for title in access["files"]
            ]
            server.serve(
                f"{ods}/{access['dataset_id']}/attachments",
                body(json.dumps({"attachments": listing}).encode(), "application/json"),
            )
            for title in access["files"]:
                server.serve(f"/att/{quote(title)}", body(f"content of {title}".encode()))
        elif kind == "data_gouv":
            resources = [
                {"title": title, "url": f"{server.url}/res/{i}/file{i}.csv"}
                for i, title in enumerate(access["files"])
            ]
            server.serve(
                f"/api/1/datasets/{access['dataset_id']}/",
                body(json.dumps({"resources": resources}).encode(), "application/json"),
            )
            for i, title in enumerate(access["files"]):
                server.serve(f"/res/{i}/file{i}.csv", body(f"content of {title}".encode()))
        elif kind == "archive":
            server.serve(
                "/ameco.zip", body(make_zip(access["member"], b"FRA;1;2\n"), "application/zip")
            )
            access["download_url"] = f"{server.url}/ameco.zip"
        else:
            name = manual_name(source)
            (manual_dir / "docs").mkdir(parents=True, exist_ok=True)
            (manual_dir / "docs" / name).write_bytes(b"%PDF hand placed")
            access["sha256"] = sha256_of(b"%PDF hand placed")
        patched[source_id] = dataclasses.replace(source, access=access)
    return patched


def fetcher(server: FakeServer, tmp_path: Path, **options: object) -> Fetcher:
    return Fetcher(
        raw_dir=tmp_path / "raw",
        manual_dir=tmp_path / "manual",
        lock_path=tmp_path / "sources.lock.json",
        client=HttpClient(max_attempts=3, backoff=0, sleep=lambda _: None),
        base_urls={PORTAL: server.url, DATA_GOUV: server.url},
        **options,  # type: ignore[arg-type]
    )


def test_five_manifest_entries_twice_download_once(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    assert {s.access["kind"] for s in sources.values()} == {
        "records",
        "attachments",
        "data_gouv",
        "archive",
        "manual",
    }
    first = fetcher(server, tmp_path).fetch_all(sources.values())
    hits_after_first = dict(server.hits)
    assert all(item.downloaded for item in first if item.source_id != MANUAL_ID)
    assert hits_after_first
    assert all(count == 1 for count in hits_after_first.values())

    second = fetcher(server, tmp_path).fetch_all(sources.values())
    assert dict(server.hits) == hits_after_first
    assert not any(item.downloaded for item in second)
    assert [(i.key, i.sha256) for i in second] == [(i.key, i.sha256) for i in first]


def test_lockfile_is_stable_between_two_runs(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    lock = tmp_path / "sources.lock.json"
    fetcher(server, tmp_path, today=lambda: "2026-01-01").fetch_all(sources.values())
    first = lock.read_bytes()
    fetcher(server, tmp_path, today=lambda: "2027-02-02").fetch_all(sources.values())
    assert lock.read_bytes() == first
    fetcher(server, tmp_path, today=lambda: "2027-03-03", force=True).fetch_all(sources.values())
    assert lock.read_bytes() == first


def test_lockfile_records_size_and_sha256(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    fetcher(server, tmp_path).fetch(sources["lfi-2019-voted"])
    entry = json.loads((tmp_path / "sources.lock.json").read_text())["sources"]["lfi-2019-voted"][
        "records"
    ]
    data = b'[{"a": 1}]'
    assert entry["size"] == len(data)
    assert entry["sha256"] == sha256_of(data)
    assert (tmp_path / "raw" / "lfi-2019-voted" / entry["path"]).read_bytes() == data


def test_offline_uses_the_cache_only(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    fetcher(server, tmp_path).fetch_all(sources.values())
    hits = dict(server.hits)
    again = fetcher(server, tmp_path, offline=True).fetch_all(sources.values())
    assert dict(server.hits) == hits
    assert len(again) == sum(len(file_keys(s)) for s in sources.values())


def test_offline_with_an_empty_cache_fails_without_a_request(
    server: FakeServer, tmp_path: Path
) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    with pytest.raises(OfflineError, match="lfi-2019-voted"):
        fetcher(server, tmp_path, offline=True).fetch(sources["lfi-2019-voted"])
    assert not server.hits


def test_a_changed_cache_file_is_fetched_again(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    source = sources["lfi-2019-voted"]
    result = fetcher(server, tmp_path).fetch(source)[0]
    result.path.write_bytes(b"corrupted")
    again = fetcher(server, tmp_path).fetch(source)[0]
    assert again.downloaded
    assert again.path.read_bytes() == b'[{"a": 1}]'


def test_attachment_by_title_must_exist(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    source = sources["plrg-2024-execution"]
    access = {**source.access, "files": ["No such title.csv"]}
    with pytest.raises(FetchError, match="No such title.csv"):
        fetcher(server, tmp_path).fetch(dataclasses.replace(source, access=access))


def test_refusal_names_the_host_and_stops(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    source = sources["ameco-net-lending"]
    server.serve("/ameco.zip", body(b"denied", "text/plain", 403))
    with pytest.raises(RefusalError, match="127.0.0.1"):
        fetcher(server, tmp_path).fetch(source)
    assert server.hits["/ameco.zip"] == 1
    assert not (tmp_path / "sources.lock.json").exists()


def test_archive_member_missing(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    source = sources["ameco-net-lending"]
    server.serve("/ameco.zip", body(make_zip("OTHER.TXT", b"x"), "application/zip"))
    with pytest.raises(FetchError, match="AMECO16.TXT"):
        fetcher(server, tmp_path).fetch(source)


def test_manual_file_is_copied_and_checked(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    source = sources["stability-programme-france-2016"]
    result = fetcher(server, tmp_path).fetch(source)[0]
    assert result.path == tmp_path / "raw" / source.id / manual_name(source)
    assert result.path.read_bytes() == b"%PDF hand placed"
    assert not server.hits


def test_manual_file_with_another_checksum_is_refused(server: FakeServer, tmp_path: Path) -> None:
    sources = serve_manifest(server, load_manifest(MANIFEST_DIR), tmp_path / "manual")
    source = sources["stability-programme-france-2016"]
    access = {**source.access, "sha256": "0" * 64}
    with pytest.raises(FetchError, match="manifest pins"):
        fetcher(server, tmp_path).fetch(dataclasses.replace(source, access=access))


def test_manual_file_missing_says_where_to_put_it(server: FakeServer, tmp_path: Path) -> None:
    source = load_manifest(MANIFEST_DIR)["stability-programme-france-2016"]
    with pytest.raises(FetchError, match="placed by hand is missing"):
        fetcher(server, tmp_path).fetch(source)


def test_skip_manual_names_the_source_and_keeps_the_lockfile(
    server: FakeServer, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = load_manifest(MANIFEST_DIR)[MANUAL_ID]
    skipping = fetcher(server, tmp_path, skip_manual=True)
    assert skipping.fetch(source) == []
    assert MANUAL_ID in caplog.text
    assert MANUAL_ID not in skipping.lock.entries
    assert not (tmp_path / "raw" / MANUAL_ID).exists()
