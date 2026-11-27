"""Publish tables to the Hugging Face dataset of their project.

Each table is uploaded as Parquet with a dataset card generated from the manifest. A content
hash of the data and the card, stored in the dataset, lets a second publish of the same
content do nothing, so it creates no commit.

A publish never deletes a file. If the dataset holds a table file that the publish does not
hold, the publish stops before any upload, so a run that builds one table fewer cannot remove
a table that the app reads. Other files that the publish does not hold stay as they are.

A dry run makes no network call: it prints the files and the card that a publish would send.
It does not read the dataset, so it shows neither a refusal nor an unchanged hash.

The token is read by `huggingface_hub` from the `HF_TOKEN` environment variable. This module
never receives it as an argument and never logs it. A network or Hub error is not caught: it
ends the command with the library's own error.
"""

import hashlib
import io
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Protocol

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import CommitOperationAdd, HfApi

from core.fetch.lockfile import Lockfile
from core.publish.card import build_card
from core.publish.freshness import check_last_update
from core.publish.hf_check import CARD_PATH, DATASET_NAMES, NAMESPACE
from core.sources.manifest import Source
from core.tables.writer import read_metadata

logger = logging.getLogger(__name__)

HASH_PATH = "content.sha256"
TABLE_DIR = "data"


class PublishError(ValueError):
    """The files to publish cannot go in the dataset."""


class HubApi(Protocol):
    """The part of `huggingface_hub.HfApi` that the publisher uses."""

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object: ...

    def list_repo_files(self, repo_id: str, *, repo_type: str) -> list[str]: ...

    def hf_hub_download(self, repo_id: str, filename: str, *, repo_type: str) -> str: ...

    def create_commit(
        self,
        repo_id: str,
        operations: Sequence[CommitOperationAdd],
        *,
        commit_message: str,
        repo_type: str,
    ) -> object: ...


@dataclass(frozen=True)
class Upload:
    """What a publish sends to one dataset."""

    repo_id: str
    #: Bytes of each file, by path in the dataset.
    files: Mapping[str, bytes]
    content_hash: str
    tables: int
    #: Ids of the sources that the tables use.
    source_ids: tuple[str, ...]


def repo_id_of(dataset: str) -> str:
    """Return the repository identifier of a dataset.

    Args:
        dataset: One of the dataset names: core, finance, security or election.

    Returns:
        For example `sam-bot/public-money-core`.

    Raises:
        PublishError: If the name is not one of the four.
    """
    if dataset not in DATASET_NAMES:
        raise PublishError(f"unknown dataset {dataset!r}; known: {', '.join(DATASET_NAMES)}")
    return f"{NAMESPACE}/public-money-{dataset}"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _data_hash(path: Path) -> str:
    """Hash the rows and the schema of a Parquet file, not its metadata or its row groups."""
    table = pq.read_table(path).replace_schema_metadata(None).combine_chunks()
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return hashlib.sha256(sink.getvalue()).hexdigest()


def prepare(dataset: str, paths: Sequence[Path], manifest: Mapping[str, Source]) -> Upload:
    """Build the files of a publish: the Parquet tables, the card and the content hash.

    The content hash covers the rows of each table and the card without the build dates and
    commits, so a rebuild that changes nothing but those gives the same hash.

    Args:
        dataset: Name of the dataset.
        paths: Parquet files written by `write_table`.
        manifest: The sources by id.

    Returns:
        The upload.

    Raises:
        PublishError: If the dataset is unknown, no file is given, a file does not exist, or
            two files hold the same table.
        TableError: If a file has no table metadata.
        CardError: If the card cannot state what the licences of the inputs ask for.
    """
    repo_id = repo_id_of(dataset)
    if not paths:
        raise PublishError("no table to publish")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise PublishError(f"no such file: {', '.join(missing)}")
    metadata = [read_metadata(path) for path in paths]
    names = sorted(item.table for item in metadata)
    if len(set(names)) != len(names):
        raise PublishError(f"two files hold the same table: {', '.join(names)}")
    name = repo_id.split("/", 1)[1]
    digest = hashlib.sha256()
    stable = [replace(item, build_date="", commit="") for item in metadata]
    digest.update(build_card(name, stable, manifest).encode())
    for item, path in sorted(zip(metadata, paths, strict=True), key=lambda pair: pair[0].table):
        digest.update(f"{item.table}:{_data_hash(path)}\n".encode())
    content_hash = digest.hexdigest()
    files = {
        f"{TABLE_DIR}/{item.table}.parquet": path.read_bytes()
        for item, path in zip(metadata, paths, strict=True)
    }
    files[CARD_PATH] = build_card(name, metadata, manifest).encode()
    files[HASH_PATH] = (content_hash + "\n").encode()
    source_ids = tuple(sorted({i for item in metadata for i in item.source_ids}))
    return Upload(
        repo_id=repo_id,
        files=files,
        content_hash=content_hash,
        tables=len(paths),
        source_ids=source_ids,
    )


def describe(upload: Upload) -> str:
    """Describe an upload for a dry run.

    Args:
        upload: What a publish would send.

    Returns:
        One line for the dataset, one line for each file with its size, then the card.
    """
    lines = [f"dry run: would upload to {upload.repo_id} (content hash {upload.content_hash})"]
    lines.extend(f"  {path} ({len(data)} bytes)" for path, data in sorted(upload.files.items()))
    lines.extend(["", f"{CARD_PATH}:", upload.files[CARD_PATH].decode()])
    return "\n".join(lines)


@dataclass(frozen=True)
class CommitPlan:
    """The commit of a publish."""

    operations: Sequence[CommitOperationAdd]
    message: str


def plan_commit(
    present_files: Sequence[str], stored_hash: str | None, upload: Upload
) -> CommitPlan | None:
    """Decide what a publish commits.

    Args:
        present_files: The files that the dataset holds now.
        stored_hash: The content hash stored in the dataset, or None if it holds none.
        upload: What the publish sends.

    Returns:
        The commit, or None if the stored hash equals the hash of the upload.

    Raises:
        PublishError: If the dataset holds a table file that the upload does not hold.
    """
    missing = sorted(
        path
        for path in present_files
        if path.endswith(".parquet")
        and PurePosixPath(path).parent == PurePosixPath(TABLE_DIR)
        and path not in upload.files
    )
    if missing:
        raise PublishError(
            f"{upload.repo_id} holds table files that this publish does not hold, so it would "
            f"drop them from the dataset: {', '.join(missing)}. Nothing was uploaded."
        )
    if stored_hash == upload.content_hash:
        return None
    operations = [
        CommitOperationAdd(path_in_repo=path, path_or_fileobj=data)
        for path, data in sorted(upload.files.items())
    ]
    return CommitPlan(operations, f"data: publish {_count(upload.tables, 'table')}")


def publish(api: HubApi, upload: Upload) -> bool:
    """Upload the files in one commit, unless nothing changed.

    Args:
        api: Hub client.
        upload: What to send.

    Returns:
        True if a commit was created, False if the content hash had not changed.

    Raises:
        PublishError: If the dataset holds a table file that the upload does not hold.
    """
    api.create_repo(upload.repo_id, repo_type="dataset", exist_ok=True)
    present = api.list_repo_files(upload.repo_id, repo_type="dataset")
    stored = None
    if HASH_PATH in present:
        path = api.hf_hub_download(upload.repo_id, HASH_PATH, repo_type="dataset")
        stored = Path(path).read_text(encoding="utf-8").strip()
    plan = plan_commit(present, stored, upload)
    if plan is None:
        logger.info("%s: content unchanged, nothing to commit", upload.repo_id)
        return False
    api.create_commit(
        upload.repo_id, plan.operations, commit_message=plan.message, repo_type="dataset"
    )
    logger.info("%s: committed %d files", upload.repo_id, len(upload.files))
    return True


def run(
    dataset: str,
    paths: Sequence[Path],
    manifest: Mapping[str, Source],
    lock: Lockfile,
    *,
    dry_run: bool,
) -> int:
    """Prepare a publish, then print it (dry run) or send it.

    Args:
        dataset: Name of the dataset.
        paths: Parquet files written by `write_table`; every table of the dataset, because
            a publish refuses to drop a table that the dataset holds.
        manifest: The sources by id.
        lock: The lockfile; a source whose pinned files changed after its date of last update
            was read stops the publish, the dry run included.
        dry_run: Print the files and the card that would be uploaded, then stop. It makes no
            network call and does not read the dataset.

    Returns:
        0 on success, 1 if the token is missing for a real run.

    Raises:
        PublishError: If the dataset is unknown, a file is missing, two files hold the
            same table, or the dataset holds a table that the files do not hold.
        TableError: If a file has no table metadata.
        CardError: If the card cannot state what the licences of the inputs ask for.
        StaleDateError: If a pinned file of an input changed after its date was read.
    """
    upload = prepare(dataset, paths, manifest)
    check_last_update(upload.source_ids, manifest, lock)
    if dry_run:
        print(describe(upload))
        return 0
    if not os.environ.get("HF_TOKEN"):
        logger.error("HF_TOKEN is not set")
        return 1
    publish(HfApi(), upload)
    return 0
