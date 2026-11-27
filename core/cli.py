"""Command line of the project: `uv run python -m core.cli fetch`."""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from core.fetch.fetcher import (
    DEFAULT_LOCK_PATH,
    DEFAULT_MANUAL_DIR,
    DEFAULT_RAW_DIR,
    Fetcher,
)
from core.fetch.http import FetchError
from core.fetch.lockfile import Lockfile
from core.publish.card import CardError
from core.publish.freshness import StaleDateError
from core.publish.hf_check import DATASET_NAMES
from core.publish.publisher import PublishError, run
from core.sources.manifest import MANIFEST_DIR, ManifestError, load_manifest
from core.tables.writer import TableError

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the command line."""
    parser = argparse.ArgumentParser(prog="core.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="fetch sources into the raw cache")
    fetch.add_argument("source_ids", nargs="*", help="manifest ids; all sources if omitted")
    fetch.add_argument("--offline", action="store_true", help="use the cache only")
    fetch.add_argument("--force", action="store_true", help="fetch files the cache already has")
    fetch.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    fetch.add_argument("--manual-dir", type=Path, default=DEFAULT_MANUAL_DIR)
    fetch.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    fetch.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    publish = commands.add_parser(
        "publish", help="publish Parquet tables to a Hugging Face dataset"
    )
    publish.add_argument("dataset", choices=DATASET_NAMES)
    publish.add_argument("tables", nargs="+", type=Path, help="Parquet files from write_table")
    publish.add_argument(
        "--dry-run",
        action="store_true",
        help="print the files and the card that would be uploaded; makes no network call, so it "
        "shows neither a refusal nor an unchanged hash",
    )
    publish.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    publish.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: The arguments; the process arguments if omitted.

    Returns:
        0 on success, 1 if a source could not be fetched, 2 on a bad argument
        or an invalid manifest.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest_dir)
    except ManifestError as error:
        logger.error("%s", error)
        return 2
    if args.command == "publish":
        if not args.lock.is_file():
            logger.error("no lockfile at %s; run the fetch first or give --lock", args.lock)
            return 2
        try:
            lock = Lockfile.load(args.lock)
            return run(args.dataset, args.tables, manifest, lock, dry_run=args.dry_run)
        except (PublishError, TableError, CardError, StaleDateError) as error:
            logger.error("%s", error)
            return 2
    unknown = [source_id for source_id in args.source_ids if source_id not in manifest]
    if unknown:
        logger.error("unknown source id: %s", ", ".join(unknown))
        return 2
    sources = [manifest[source_id] for source_id in args.source_ids] or list(manifest.values())
    fetcher = Fetcher(
        raw_dir=args.raw_dir,
        manual_dir=args.manual_dir,
        lock_path=args.lock,
        offline=args.offline,
        force=args.force,
    )
    try:
        files = fetcher.fetch_all(sources)
    except FetchError as error:
        logger.error("%s", error)
        return 1
    stored = sum(item.downloaded for item in files)
    print(f"{len(files)} files, {stored} stored, {len(files) - stored} from the cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
