"""Publish tables to the Hugging Face dataset of their project.

Each table is uploaded as Parquet with a dataset card generated from the manifest. A content
hash of the data and the card, stored in the dataset, lets a second publish of the same
content do nothing, so it creates no commit. A dry run prints what would be uploaded and
reaches no network.

The token is read by `huggingface_hub` from the `HF_TOKEN` environment variable. This module
never receives it as an argument and never logs it.
"""

import hashlib
import io
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import CommitOperationAdd, HfApi

from core.fetch.lockfile import Lockfile
from core.publish.card import build_card
from core.publish.hf_check import DATASET_NAMES, NAMESPACE
from core.sources.manifest import Source
from core.tables.writer import read_metadata

logger = logging.getLogger(__name__)

CARD_PATH = "README.md"
HASH_PATH = "content.sha256"


class PublishError(ValueError):
    """The files to publish cannot go in the dataset."""


class HubApi(Protocol):
    """The part of `huggingface_hub.HfApi` that the publisher uses."""

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object: ...

    def file_exists(self, repo_id: str, filename: str, *, repo_type: str) -> bool: ...

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


def _data_hash(path: Path) -> str:
    """Hash the rows and the schema of a Parquet file, not its metadata."""
    table = pq.read_table(path).replace_schema_metadata(None)
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return hashlib.sha256(sink.getvalue()).hexdigest()


def prepare(
    dataset: str,
    paths: Sequence[Path],
    manifest: Mapping[str, Source],
    lockfile: Lockfile,
) -> Upload:
    """Build the files of a publish: the Parquet tables, the card and the content hash.

    The content hash covers the rows of each table and the card without the build dates, so a
    rebuild that changes nothing but those gives the same hash.

    Args:
        dataset: Name of the dataset.
        paths: Parquet files written by `write_table`.
        manifest: The sources by id.
        lockfile: The lockfile of the raw files.

    Returns:
        The upload.

    Raises:
        PublishError: If the dataset is unknown, no file is given, or two files hold the same
            table.
        TableError: If a file has no table metadata.
        CardError: If a table names a source id that the manifest does not have.
    """
    repo_id = repo_id_of(dataset)
    if not paths:
        raise PublishError("no table to publish")
    metadata = [read_metadata(path) for path in paths]
    names = sorted(item.table for item in metadata)
    if len(set(names)) != len(names):
        raise PublishError(f"two files hold the same table: {', '.join(names)}")
    name = repo_id.split("/", 1)[1]
    digest = hashlib.sha256()
    stable = [replace(item, build_date="", commit="") for item in metadata]
    digest.update(build_card(name, stable, manifest, lockfile).encode())
    for item, path in sorted(zip(metadata, paths, strict=True), key=lambda pair: pair[0].table):
        digest.update(f"{item.table}:{_data_hash(path)}\n".encode())
    content_hash = digest.hexdigest()
    files = {
        f"data/{item.table}.parquet": path.read_bytes()
        for item, path in zip(metadata, paths, strict=True)
    }
    files[CARD_PATH] = build_card(name, metadata, manifest, lockfile).encode()
    files[HASH_PATH] = (content_hash + "\n").encode()
    return Upload(repo_id=repo_id, files=files, content_hash=content_hash, tables=len(paths))


def describe(upload: Upload) -> str:
    """Describe an upload for a dry run.

    Args:
        upload: What a publish would send.

    Returns:
        One line for the dataset and one line for each file, with its size.
    """
    lines = [f"dry run: would upload to {upload.repo_id} (content hash {upload.content_hash})"]
    lines.extend(f"  {path} ({len(data)} bytes)" for path, data in sorted(upload.files.items()))
    return "\n".join(lines)


def publish(api: HubApi, upload: Upload) -> bool:
    """Upload the files in one commit, unless the dataset already holds this content.

    Args:
        api: Hub client.
        upload: What to send.

    Returns:
        True if a commit was created, False if the content hash had not changed.
    """
    api.create_repo(upload.repo_id, repo_type="dataset", exist_ok=True)
    if api.file_exists(upload.repo_id, HASH_PATH, repo_type="dataset"):
        stored = api.hf_hub_download(upload.repo_id, HASH_PATH, repo_type="dataset")
        if Path(stored).read_text(encoding="utf-8").strip() == upload.content_hash:
            logger.info("%s: content unchanged, nothing to commit", upload.repo_id)
            return False
    operations = [
        CommitOperationAdd(path_in_repo=path, path_or_fileobj=data)
        for path, data in sorted(upload.files.items())
    ]
    api.create_commit(
        upload.repo_id,
        operations,
        commit_message=f"data: publish {upload.tables} tables",
        repo_type="dataset",
    )
    logger.info("%s: committed %d files", upload.repo_id, len(operations))
    return True


def run(
    dataset: str,
    paths: Sequence[Path],
    manifest: Mapping[str, Source],
    lockfile: Lockfile,
    *,
    dry_run: bool,
) -> int:
    """Prepare a publish, then print it (dry run) or send it.

    Args:
        dataset: Name of the dataset.
        paths: Parquet files written by `write_table`.
        manifest: The sources by id.
        lockfile: The lockfile of the raw files.
        dry_run: Print what would be uploaded and stop; no token and no network are used.

    Returns:
        0 on success, 1 if the token is missing for a real run.
    """
    upload = prepare(dataset, paths, manifest, lockfile)
    if dry_run:
        print(describe(upload))
        return 0
    if not os.environ.get("HF_TOKEN"):
        logger.error("HF_TOKEN is not set")
        return 1
    publish(HfApi(), upload)
    return 0
