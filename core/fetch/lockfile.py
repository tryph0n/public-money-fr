"""The lockfile: size and SHA-256 of every raw file, committed to the repository.

The file is written the same way every time (sorted keys, no run-time stamp), so two runs on
the same cache give the same bytes. The retrieval date is the day a file was first stored or
last changed; a run that finds the same bytes keeps it.
"""

import datetime
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

LOCK_VERSION = 1


@dataclass(frozen=True)
class LockedFile:
    """What the lockfile records about one raw file."""

    #: File name under `data/raw/<source id>/`.
    path: str
    size: int
    sha256: str
    #: Day the bytes were stored (ISO date).
    retrieved_on: str


def sha256_of(data: bytes) -> str:
    """Return the SHA-256 of some bytes as lowercase hexadecimal."""
    return hashlib.sha256(data).hexdigest()


def today_iso() -> str:
    """Return today's date as `YYYY-MM-DD`."""
    return datetime.date.today().isoformat()


class Lockfile:
    """The entries of `sources.lock.json`, by source id and by file key."""

    def __init__(self, entries: dict[str, dict[str, LockedFile]] | None = None) -> None:
        """Hold the entries.

        Args:
            entries: Source id, then file key (the name the manifest gives the file), then
                the entry.
        """
        self.entries = entries if entries is not None else {}

    @classmethod
    def load(cls, path: Path) -> "Lockfile":
        """Read a lockfile; a missing file gives an empty one.

        Args:
            path: The lockfile.

        Returns:
            The entries.

        Raises:
            ValueError: If the file has another version.
        """
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != LOCK_VERSION:
            raise ValueError(f"{path.name}: unsupported version {data.get('version')!r}")
        return cls(
            {
                source_id: {key: LockedFile(**item) for key, item in files.items()}
                for source_id, files in data["sources"].items()
            }
        )

    def dumps(self) -> str:
        """Return the text of the file: JSON with sorted keys and a final line feed."""
        data = {
            "version": LOCK_VERSION,
            "sources": {
                source_id: {key: asdict(item) for key, item in files.items()}
                for source_id, files in self.entries.items()
            },
        }
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def save(self, path: Path) -> None:
        """Write the file, only if its text changes.

        Args:
            path: The lockfile.
        """
        text = self.dumps()
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return
        path.write_text(text, encoding="utf-8")
