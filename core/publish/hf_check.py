"""Check that CI can publish to the four Hugging Face datasets.

For each dataset the check creates the repository if it is missing, writes a minimal dataset card
if there is none, uploads a tiny Parquet file, confirms that it is there, and removes it. It can
run again at any time: existing repositories and cards are left as they are, and the test file is
removed even when a step fails.

The token is read by `huggingface_hub` from the `HF_TOKEN` environment variable. This module
never receives it as an argument and never logs it.

Run it with `uv run python -m core.publish.hf_check`.
"""

import io
import logging
import os
import sys
from typing import Protocol

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import HfApi

from core.publish.card import REPOSITORY_URL, card_header

logger = logging.getLogger(__name__)

NAMESPACE = "sam-bot"
DATASET_NAMES = ("core", "finance", "security", "election")
CARD_PATH = "README.md"
TEST_FILE_PATH = "_ci_check/test.parquet"


class HubApi(Protocol):
    """The part of `huggingface_hub.HfApi` that this check uses."""

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object: ...

    def file_exists(self, repo_id: str, filename: str, *, repo_type: str) -> bool: ...

    def upload_file(
        self,
        *,
        path_or_fileobj: bytes,
        path_in_repo: str,
        repo_id: str,
        repo_type: str,
        commit_message: str,
    ) -> object: ...

    def delete_file(
        self, path_in_repo: str, repo_id: str, *, repo_type: str, commit_message: str
    ) -> object: ...


def repo_id(dataset: str) -> str:
    """Returns the repository identifier of a dataset, for example `sam-bot/public-money-core`."""
    return f"{NAMESPACE}/public-money-{dataset}"


def repo_ids() -> list[str]:
    """Returns the repository identifiers of the four datasets."""
    return [repo_id(name) for name in DATASET_NAMES]


def build_card(repo_id: str) -> str:
    """Builds the minimal dataset card of a repository.

    Args:
        repo_id: Repository identifier, for example `sam-bot/public-money-core`.

    Returns:
        The text of `README.md`: YAML metadata followed by a short description.
    """
    title = repo_id.split("/", 1)[1]
    return (
        card_header(title) + "\n"
        f"# {title}\n"
        "\n"
        "Open data on French public money, processed and published by the public-money-fr "
        "project. This card is a placeholder; the generated card will list the inputs, their "
        "producers and licences, and the build date.\n"
        "\n"
        f"Source code and documentation: {REPOSITORY_URL}\n"
    )


def build_test_parquet() -> bytes:
    """Builds a tiny Parquet file in memory.

    Returns:
        The bytes of a Parquet file with two rows.
    """
    table = pa.table({"id": [1, 2], "label": ["a", "b"]})
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def check_repo(api: HubApi, repo_id: str) -> None:
    """Runs the publish check on one dataset.

    Args:
        api: Hub client.
        repo_id: Repository identifier.

    Raises:
        RuntimeError: If the test file is missing after the upload or still present after the
            removal.
    """
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
    if not api.file_exists(repo_id, CARD_PATH, repo_type="dataset"):
        api.upload_file(
            path_or_fileobj=build_card(repo_id).encode(),
            path_in_repo=CARD_PATH,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message="docs: add the minimal dataset card",
        )
        logger.info("%s: card written", repo_id)
    api.upload_file(
        path_or_fileobj=build_test_parquet(),
        path_in_repo=TEST_FILE_PATH,
        repo_id=repo_id,
        repo_type="dataset",
        commit_message="chore: upload the publish check file",
    )
    try:
        if not api.file_exists(repo_id, TEST_FILE_PATH, repo_type="dataset"):
            raise RuntimeError(f"{repo_id}: test file missing after upload")
        logger.info("%s: test file uploaded and found", repo_id)
    finally:
        api.delete_file(
            TEST_FILE_PATH,
            repo_id,
            repo_type="dataset",
            commit_message="chore: remove the publish check file",
        )
    if api.file_exists(repo_id, TEST_FILE_PATH, repo_type="dataset"):
        raise RuntimeError(f"{repo_id}: test file still present after removal")
    logger.info("%s: test file removed", repo_id)


def main() -> int:
    """Runs the check on the four datasets.

    Returns:
        0 when every dataset passes, 1 otherwise.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not os.environ.get("HF_TOKEN"):
        logger.error("HF_TOKEN is not set")
        return 1
    api = HfApi()
    failed = 0
    for repo_id in repo_ids():
        try:
            check_repo(api, repo_id)
        except Exception as error:
            logger.error("%s: failed (%s)", repo_id, type(error).__name__)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
