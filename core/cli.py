"""Command line of the project: `uv run python -m core fetch`."""

import argparse
import logging
import sys
from collections.abc import Mapping, Sequence
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
from core.sources.manifest import MANIFEST_DIR, ManifestError, Source, load_manifest
from core.tables.build import (
    DEFAULT_BUILD_DIR,
    Builder,
    BuildError,
    build_tables,
    check_builders,
    load_builders,
    select_builders,
    validate_build,
)
from core.tables.manual import DEFAULT_ROWS_DIR, ManualRowsError, extract_rows
from core.tables.writer import TableError

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the command line."""
    parser = argparse.ArgumentParser(prog="core")
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
    build = commands.add_parser(
        "build", help="run the table builders and write their Parquet files"
    )
    build.add_argument("targets", nargs="*", help="table or dataset names; all builders if omitted")
    build.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    build.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    build.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    build.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    build.add_argument("--rows-dir", type=Path, default=DEFAULT_ROWS_DIR)
    extract = commands.add_parser(
        "extract",
        help="write the committed rows of manual sources from their raw files",
    )
    extract.add_argument("targets", nargs="*", help="table names; all manual tables if omitted")
    extract.add_argument("--manual-dir", type=Path, default=DEFAULT_MANUAL_DIR)
    extract.add_argument("--rows-dir", type=Path, default=DEFAULT_ROWS_DIR)
    extract.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    validate = commands.add_parser(
        "validate", help="check the Parquet files of the build folders before a publish"
    )
    validate.add_argument("datasets", nargs="*", help="dataset names; all four if omitted")
    validate.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    validate.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    return parser


def _build(
    args: argparse.Namespace, builders: Sequence[Builder], manifest: Mapping[str, Source]
) -> int:
    """Run the `build` command."""
    try:
        chosen = select_builders(builders, args.targets)
    except BuildError as error:
        logger.error("%s", error)
        return 2
    if not chosen:
        print("no builder registered, nothing built")
        return 0
    try:
        written = build_tables(
            chosen, Lockfile.load(args.lock), args.raw_dir, args.build_dir, manifest, args.rows_dir
        )
    except BuildError as error:
        logger.error("%s", error)
        return 1
    for path in written:
        print(f"built {path}")
    return 0


def _extract(
    args: argparse.Namespace, builders: Sequence[Builder], manifest: Mapping[str, Source]
) -> int:
    """Run the `extract` command."""
    chosen = [
        b for b in builders if b.manual_parsers and (not args.targets or b.table in args.targets)
    ]
    unknown = set(args.targets) - {b.table for b in chosen}
    if unknown:
        logger.error("no manual source to extract for: %s", ", ".join(sorted(unknown)))
        return 2
    try:
        for builder in chosen:
            for source_id, parse in builder.manual_parsers.items():
                path = extract_rows(
                    parse,
                    manifest[source_id],
                    builder.table,
                    args.rows_dir,
                    args.manual_dir,
                    schema=builder.schema,
                    key=builder.key,
                )
                print(f"extracted {path}")
    except (ManualRowsError, TableError) as error:
        logger.error("%s", error)
        return 1
    return 0


def _validate(
    args: argparse.Namespace, builders: Sequence[Builder], manifest: Mapping[str, Source]
) -> int:
    """Run the `validate` command."""
    try:
        problems = validate_build(builders, args.datasets, manifest, args.build_dir)
    except BuildError as error:
        logger.error("%s", error)
        return 2
    for problem in problems:
        logger.error("%s", problem)
    if not problems:
        print("all table files are valid")
    return 2 if problems else 0


def main(argv: Sequence[str] | None = None, builders: Sequence[Builder] | None = None) -> int:
    """Run the command line.

    Args:
        argv: The arguments; the process arguments if omitted.
        builders: The table builders; those that installed packages declare if omitted.

    Returns:
        0 on success, 1 if a source could not be fetched or a builder failed, 2 on a bad
        argument, an invalid manifest or a table file that `validate` refuses.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest_dir)
    except ManifestError as error:
        logger.error("%s", error)
        return 2
    if args.command in ("build", "validate", "extract"):
        try:
            registered = load_builders() if builders is None else list(builders)
            check_builders(registered)
        except BuildError as error:
            logger.error("%s", error)
            return 2
        if args.command == "build":
            return _build(args, registered, manifest)
        if args.command == "extract":
            return _extract(args, registered, manifest)
        return _validate(args, registered, manifest)
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
