"""Stop a publish whose date of last update may be stale.

The card prints, for each input, the date of last update that the producer states, read from
the manifest field `last_update`. A person reads that date at `last_update.url` for the files
that were pinned at the time, and records the SHA-256 of those files in `last_update.files`.
When a pinned file changes afterwards (a new checksum in the lockfile, or a new `sha256` in
the manifest for a manual file), the producer may have changed the date with it, so the
publish stops until the date is read again.

The check compares checksums, never dates: `retrieved_on` of the lockfile is the day of the
first fetch too, and a date that a portal gives can be false. A source with no lockfile entry
is skipped with a warning, because nothing is pinned for it yet.
"""

import logging
from collections.abc import Iterable, Mapping

from core.fetch.adapters import file_keys
from core.fetch.lockfile import Lockfile
from core.sources.manifest import Source

logger = logging.getLogger(__name__)


class StaleDateError(ValueError):
    """A pinned file changed after the date of last update was read."""


def current_checksums(source: Source, lock: Lockfile) -> dict[str, str] | None:
    """Return the SHA-256 that each file of a source has now.

    Args:
        source: The source.
        lock: The lockfile.

    Returns:
        The checksum by file key: the manifest `sha256` for a manual file, the lockfile entry
        for any other file. None if the lockfile has no entry for the source.
    """
    if source.access["kind"] == "manual":
        return {key: source.access["sha256"] for key in file_keys(source)}
    entries = lock.entries.get(source.id)
    if entries is None:
        return None
    return {key: entry.sha256 for key, entry in entries.items()}


def check_last_update(
    source_ids: Iterable[str], manifest: Mapping[str, Source], lock: Lockfile
) -> None:
    """Refuse a source whose pinned files changed since its date of last update was read.

    Args:
        source_ids: The sources that the publish uses.
        manifest: The sources by id.
        lock: The lockfile.

    Raises:
        StaleDateError: If a file differs from `last_update.files`, is new, or is gone. The
            message names the source, the files and `last_update.url`.
    """
    problems = []
    for source_id in source_ids:
        source = manifest[source_id]
        if source.last_update is None:
            continue
        now = current_checksums(source, lock)
        if now is None:
            logger.warning("%s: not in the lockfile, its last update is not checked", source_id)
            continue
        pinned = source.last_update.files
        details = [
            f"changed: {key}" for key in sorted(now) if key in pinned and pinned[key] != now[key]
        ]
        details += [f"new: {key}" for key in sorted(now) if key not in pinned]
        details += [f"gone: {key}" for key in sorted(pinned) if key not in now]
        if details:
            problems.append(
                f"{source_id}: the pinned files changed after the date of last update was read "
                f"on {source.last_update.read_on.isoformat()} ({'; '.join(details)}). Read the "
                f"date again at {source.last_update.url}, update last_update in the manifest "
                "(date, where, read_on, files) and commit it with the new lockfile in one pull "
                "request. Nothing was uploaded."
            )
    if problems:
        raise StaleDateError("\n".join(problems))
