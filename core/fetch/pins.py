"""Check that a fetch left the pinned files as the committed lockfile has them.

A fetch rewrites the lockfile with the checksum of what a host served. Comparing that file with
itself finds nothing, so the check compares it with the lockfile committed to the repository.
`python -m core.fetch.pins COMMITTED CURRENT` exits 1 and names each source, file and the page
where its date of last update is read, when a pinned file changed or has no committed entry.
"""

import argparse
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from core.fetch.lockfile import Lockfile
from core.sources.manifest import MANIFEST_DIR, ManifestError, Source, load_manifest

logger = logging.getLogger(__name__)


def pin_problems(
    committed: Lockfile, current: Lockfile, manifest: Mapping[str, Source]
) -> list[str]:
    """List the pinned files that differ between two lockfiles.

    Args:
        committed: The lockfile on `main`.
        current: The lockfile after the fetch.
        manifest: The sources, for the page of the date of last update.

    Returns:
        One message for each changed file or file with no committed entry; empty if none.
    """
    problems: list[str] = []
    for source_id, files in sorted(current.entries.items()):
        source = manifest.get(source_id)
        update = source.last_update if source is not None else None
        page = update.url if update is not None else "no last_update in the manifest"
        for key, entry in sorted(files.items()):
            old = committed.entries.get(source_id, {}).get(key)
            if old is None:
                problems.append(
                    f"{source_id}: {key} has no entry in the committed lockfile; read the date of "
                    f"last update at {page}, then add the entry in a pull request"
                )
            elif old.sha256 != entry.sha256:
                problems.append(
                    f"{source_id}: {key} changed upstream (SHA-256 {old.sha256} became "
                    f"{entry.sha256}); read the date of last update again at {page}, then update "
                    "the manifest and the lockfile in a pull request"
                )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check.

    Args:
        argv: The arguments; the process arguments if omitted.

    Returns:
        0 if no pinned file changed, 1 if one did, 2 if the manifest is invalid.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="core.fetch.pins")
    parser.add_argument("committed", type=Path, help="lockfile from the repository")
    parser.add_argument("current", type=Path, help="lockfile after the fetch")
    parser.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest_dir)
    except ManifestError as error:
        logger.error("%s", error)
        return 2
    problems = pin_problems(Lockfile.load(args.committed), Lockfile.load(args.current), manifest)
    for problem in problems:
        logger.error("%s", problem)
    if not problems:
        print("no pinned file changed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
