"""Publish tables to the Hugging Face dataset of their project.

Each table is uploaded as Parquet with a dataset card generated from the manifest. A content
hash of the data and the card, stored in the dataset, lets a second publish of the same
content do nothing, so it creates no commit.

The commit also deletes every file of the dataset that the publish does not hold (except
`.gitattributes`), so each data file in the dataset is named on the card with its inputs and
their notices. A publish must therefore give every table of the dataset.

A dry run prints the files, the card and the files that a publish would delete. It reads the
file list of the public dataset without a token and writes nothing.

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
from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

from core.publish.card import build_card
from core.publish.hf_check import CARD_PATH, DATASET_NAMES, NAMESPACE
from core.sources.manifest import Source
from core.tables.writer import read_metadata

logger = logging.getLogger(__name__)

HASH_PATH = "content.sha256"
KEPT_PATHS = (".gitattributes",)


class PublishError(ValueError):
    """The files to publish cannot go in the dataset."""


class HubApi(Protocol):
    """The part of `huggingface_hub.HfApi` that the publisher uses."""

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object: ...

    def repo_exists(self, repo_id: str, *, repo_type: str) -> bool: ...

    def list_repo_files(self, repo_id: str, *, repo_type: str) -> list[str]: ...

    def hf_hub_download(self, repo_id: str, filename: str, *, repo_type: str) -> str: ...

    def create_commit(
        self,
        repo_id: str,
        operations: Sequence[CommitOperationAdd | CommitOperationDelete],
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
        f"data/{item.table}.parquet": path.read_bytes()
        for item, path in zip(metadata, paths, strict=True)
    }
    files[CARD_PATH] = build_card(name, metadata, manifest).encode()
    files[HASH_PATH] = (content_hash + "\n").encode()
    return Upload(repo_id=repo_id, files=files, content_hash=content_hash, tables=len(paths))


def stale_files(present: Sequence[str], upload: Upload) -> list[str]:
    """List the files of the dataset that a publish deletes.

    Args:
        present: The files that the dataset holds now.
        upload: What the publish sends.

    Returns:
        The files that the upload does not hold, except `.gitattributes`, sorted.
    """
    return sorted(set(present) - set(upload.files) - set(KEPT_PATHS))


def describe(upload: Upload, stale: Sequence[str]) -> str:
    """Describe an upload for a dry run.

    Args:
        upload: What a publish would send.
        stale: The files that it would delete.

    Returns:
        One line for the dataset, one line for each file with its size, one line for each file
        to delete, then the card.
    """
    lines = [f"dry run: would upload to {upload.repo_id} (content hash {upload.content_hash})"]
    lines.extend(f"  {path} ({len(data)} bytes)" for path, data in sorted(upload.files.items()))
    lines.append(f"would delete {_count(len(stale), 'file')}" + (":" if stale else ""))
    lines.extend(f"  {path}" for path in stale)
    lines.extend(["", f"{CARD_PATH}:", upload.files[CARD_PATH].decode()])
    return "\n".join(lines)


def publish(api: HubApi, upload: Upload) -> bool:
    """Upload the files and delete the stale ones in one commit, unless nothing changed.

    Args:
        api: Hub client.
        upload: What to send.

    Returns:
        True if a commit was created, False if the content hash had not changed and the
        dataset held no stale file.
    """
    api.create_repo(upload.repo_id, repo_type="dataset", exist_ok=True)
    present = api.list_repo_files(upload.repo_id, repo_type="dataset")
    stale = stale_files(present, upload)
    if not stale and HASH_PATH in present:
        stored = api.hf_hub_download(upload.repo_id, HASH_PATH, repo_type="dataset")
        if Path(stored).read_text(encoding="utf-8").strip() == upload.content_hash:
            logger.info("%s: content unchanged, nothing to commit", upload.repo_id)
            return False
    operations: list[CommitOperationAdd | CommitOperationDelete] = [
        CommitOperationAdd(path_in_repo=path, path_or_fileobj=data)
        for path, data in sorted(upload.files.items())
    ]
    operations.extend(CommitOperationDelete(path_in_repo=path) for path in stale)
    message = f"data: publish {_count(upload.tables, 'table')}"
    if stale:
        message += f", delete {_count(len(stale), 'stale file')}"
    api.create_commit(upload.repo_id, operations, commit_message=message, repo_type="dataset")
    logger.info("%s: committed %d files, deleted %d", upload.repo_id, len(upload.files), len(stale))
    return True


def run(
    dataset: str,
    paths: Sequence[Path],
    manifest: Mapping[str, Source],
    *,
    dry_run: bool,
) -> int:
    """Prepare a publish, then print it (dry run) or send it.

    Args:
        dataset: Name of the dataset.
        paths: Parquet files written by `write_table`; every table of the dataset, because
            the publish deletes the files that it does not hold.
        manifest: The sources by id.
        dry_run: Print what would be uploaded and deleted, and the card, then stop. It reads
            the file list of the public dataset without a token and writes nothing.

    Returns:
        0 on success, 1 if the token is missing for a real run.

    Raises:
        PublishError: If the dataset is unknown, a file is missing, or two files hold the
            same table.
        TableError: If a file has no table metadata.
        CardError: If the card cannot state what the licences of the inputs ask for.
    """
    upload = prepare(dataset, paths, manifest)
    if dry_run:
        reader = HfApi(token=False)
        present = (
            reader.list_repo_files(upload.repo_id, repo_type="dataset")
            if reader.repo_exists(upload.repo_id, repo_type="dataset")
            else []
        )
        print(describe(upload, stale_files(present, upload)))
        return 0
    if not os.environ.get("HF_TOKEN"):
        logger.error("HF_TOKEN is not set")
        return 1
    publish(HfApi(), upload)
    return 0
