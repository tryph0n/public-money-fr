"""Fetch the sources of the manifest into the raw cache and pin them in the lockfile.

Files go under `<raw_dir>/<source id>/`. A file that the lockfile lists, and whose bytes still
match, is never fetched again. The offline mode uses the cache only. A file that a host will
not serve (kind `manual`) is placed by hand and checked against the checksum of the manifest.
"""

import logging
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from core.fetch import adapters
from core.fetch.http import FetchError, HttpClient, OfflineError
from core.fetch.lockfile import LockedFile, Lockfile, sha256_of, today_iso
from core.sources.manifest import Source

logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_MANUAL_DIR = Path("data/manual")
DEFAULT_LOCK_PATH = Path("sources.lock.json")


@dataclass(frozen=True)
class FetchedFile:
    """One file of the raw cache."""

    source_id: str
    key: str
    path: Path
    size: int
    sha256: str
    #: True if this run stored the file; false if the cache already had it.
    downloaded: bool


class Fetcher:
    """Fill the raw cache and keep the lockfile."""

    def __init__(
        self,
        *,
        raw_dir: Path = DEFAULT_RAW_DIR,
        manual_dir: Path = DEFAULT_MANUAL_DIR,
        lock_path: Path = DEFAULT_LOCK_PATH,
        client: HttpClient | None = None,
        offline: bool = False,
        force: bool = False,
        skip_manual: bool = False,
        base_urls: dict[str, str] | None = None,
        today: Callable[[], str] | None = None,
    ) -> None:
        """Set the folders and the mode.

        Args:
            raw_dir: The raw cache, one folder per source id.
            manual_dir: Where files fetched by hand wait; searched for a `manual` source.
            lock_path: The lockfile.
            client: The HTTP client; a default one if omitted.
            offline: Use the cache only; a missing file is an error and nothing is fetched.
            force: Fetch again the files that the cache already has.
            skip_manual: Skip the sources of kind `manual` with a notice, for a machine that
                has no copy of such a file; their lockfile entries stay as they are.
            base_urls: Base URL of a portal by portal name; see `adapters.download`.
            today: Gives the retrieval date; tests replace it.
        """
        self.raw_dir = raw_dir
        self.manual_dir = manual_dir
        self.lock_path = lock_path
        self.client = client if client is not None else HttpClient()
        self.offline = offline
        self.force = force
        self.skip_manual = skip_manual
        self._base_urls = base_urls if base_urls is not None else adapters.DEFAULT_BASE_URLS
        self._today = today if today is not None else today_iso
        self.lock = Lockfile.load(lock_path)

    def fetch_all(self, sources: Iterable[Source]) -> list[FetchedFile]:
        """Fetch several sources and save the lockfile after each one.

        Args:
            sources: The sources.

        Returns:
            The files of all sources.

        Raises:
            FetchError: At the first source that fails; the lockfile keeps the sources
                that were done.
        """
        results: list[FetchedFile] = []
        for source in sources:
            results.extend(self.fetch(source))
        return results

    def fetch(self, source: Source) -> list[FetchedFile]:
        """Make sure every file of a source is in the cache and in the lockfile.

        Args:
            source: The source.

        Returns:
            One entry per file, in the order of the manifest; none for a skipped manual source.

        Raises:
            OfflineError: In offline mode, if a file is not in the cache.
            RefusalError: If a host refuses; the message names the host.
            FetchError: On any other failure, or if a manual file does not match its checksum.
        """
        if self.skip_manual and source.access["kind"] == "manual":
            logger.warning(
                "%s: manual source skipped, no copy of its file on this machine", source.id
            )
            return []
        keys = adapters.file_keys(source)
        locked = self.lock.entries.get(source.id, {})
        missing = [key for key in keys if self.force or not self._is_cached(source, key, locked)]
        fresh: dict[str, tuple[str, bytes]] = {}
        manual = source.access["kind"] == "manual"
        if missing and self.offline and not manual:
            names = ", ".join(missing)
            raise OfflineError(f"{source.id}: offline mode, not in the cache: {names}")
        if missing and not manual:
            fresh = adapters.download(source, missing, self.client, self._base_urls)
        entries: dict[str, LockedFile] = {}
        results: list[FetchedFile] = []
        for key in keys:
            if key in fresh:
                name, data = fresh[key]
                entry, path = self._store(source, key, name, data, locked.get(key))
                downloaded = True
            elif manual and key in missing:
                entry, path = self._register_manual(source, key, locked.get(key))
                downloaded = False
            else:
                entry = locked[key]
                path = self.raw_dir / source.id / entry.path
                downloaded = False
            entries[key] = entry
            results.append(FetchedFile(source.id, key, path, entry.size, entry.sha256, downloaded))
        self.lock.entries[source.id] = entries
        self.lock.save(self.lock_path)
        return results

    def _is_cached(self, source: Source, key: str, locked: dict[str, LockedFile]) -> bool:
        entry = locked.get(key)
        if entry is None:
            return False
        if source.access["kind"] == "manual" and entry.sha256 != source.access["sha256"]:
            return False
        path = self.raw_dir / source.id / entry.path
        if not path.is_file() or path.stat().st_size != entry.size:
            return False
        if sha256_of(path.read_bytes()) != entry.sha256:
            logger.warning("%s: %s does not match the lockfile", source.id, entry.path)
            return False
        return True

    def _store(
        self, source: Source, key: str, name: str, data: bytes, old: LockedFile | None
    ) -> tuple[LockedFile, Path]:
        path = self.raw_dir / source.id / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        temporary.write_bytes(data)
        temporary.replace(path)
        digest = sha256_of(data)
        if old is not None and old.sha256 != digest:
            logger.warning("%s: %s changed upstream since the lockfile", source.id, key)
        retrieved_on = (
            old.retrieved_on if old is not None and old.sha256 == digest else self._today()
        )
        logger.info("%s: stored %s (%d bytes)", source.id, name, len(data))
        return LockedFile(name, len(data), digest, retrieved_on), path

    def _register_manual(
        self, source: Source, key: str, old: LockedFile | None
    ) -> tuple[LockedFile, Path]:
        expected = source.access["sha256"]
        placed = self.raw_dir / source.id / key
        if not placed.is_file():
            found = sorted(self.manual_dir.rglob(key)) if self.manual_dir.is_dir() else []
            if not found:
                raise FetchError(
                    f"{source.id}: file placed by hand is missing: put {key} in {placed.parent} "
                    f"(download page: {source.access['page_url']})"
                )
            placed.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(found[0], placed)
        data = placed.read_bytes()
        if not data:
            raise FetchError(f"{source.id}: {placed} is a zero-byte file")
        if sha256_of(data) != expected:
            raise FetchError(
                f"{source.id}: {placed} has SHA-256 {sha256_of(data)}, the manifest pins {expected}"
            )
        return self._store(source, key, key, data, old)
