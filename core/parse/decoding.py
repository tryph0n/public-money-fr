"""Decode and read the delimited text files of the State budget.

The files come with different encodings (UTF-16, UTF-8, Windows-1252), delimiters, preamble
lines and line endings. These helpers hide that so that no parser repeats it. Every cell is
read as text: a code such as `07` or `348-11` is never turned into a number, and a parser
decides which texts mean a missing value.
"""

import gzip
import io
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

GZIP_MAGIC = b"\x1f\x8b"
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
DELIMITERS = (";", ",")

_GESTION = re.compile(r"^gestion$", re.IGNORECASE)
_BUDGET_TYPE = re.compile(r"^type budget$", re.IGNORECASE)


@dataclass(frozen=True)
class Preamble:
    """What the preamble lines of a pivot export say."""

    #: The year of the `Gestion` line.
    year: int
    #: The text of the `Type Budget` line, for example `Budget général`.
    budget_part: str


def decode(data: bytes) -> tuple[str, str]:
    """Decode the bytes of a file and return the text with the encoding name.

    A gzip stream is unpacked first: some attachments arrive compressed under a plain name.
    The first bytes then tell UTF-16 (byte-order mark), else UTF-8 (with or without a
    byte-order mark) is tried, else Windows-1252. The name is the Python codec name.

    Args:
        data: The bytes of the file.

    Returns:
        The decoded text and the name of the codec that was used.

    Raises:
        UnicodeDecodeError: If the bytes are neither UTF-16, UTF-8 nor Windows-1252.
    """
    if data.startswith(GZIP_MAGIC):
        return decode(gzip.decompress(data))
    if data.startswith(UTF16_BOMS):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252"), "cp1252"


def detect_delimiter(header_line: str) -> str:
    """Choose the delimiter of a file by counting `;` and `,` in its header line.

    Args:
        header_line: The line that holds the column names.

    Returns:
        The more frequent of `;` and `,`.

    Raises:
        ValueError: If the line holds neither, or both the same number of times.
    """
    counts = {delimiter: header_line.count(delimiter) for delimiter in DELIMITERS}
    best = max(counts, key=lambda delimiter: counts[delimiter])
    if counts[best] == 0 or list(counts.values()).count(counts[best]) > 1:
        raise ValueError(f"Cannot choose a delimiter for the header line: {header_line!r}")
    return best


def normalise_line_ends(text: str) -> str:
    """Make every record end with LF, so that a CSV reader sees the real records.

    CRLF becomes LF. A bare CR inside a label becomes a space: the pandas C parser would
    end a record at it and split the row in two.

    Args:
        text: The decoded text of the file.

    Returns:
        The text with LF as the only line end.
    """
    return text.replace("\r\n", "\n").replace("\r", " ")


def read_text(source: bytes | Path) -> str:
    """Return the decoded text of a file, given its bytes or its path.

    Args:
        source: The bytes of the file, or the path to read them from.

    Returns:
        The decoded text, with its line ends as they are in the file.
    """
    data = source.read_bytes() if isinstance(source, Path) else source
    return decode(data)[0]


def read_table(
    source: bytes | Path,
    *,
    header_line: int = 1,
    na_values: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Read a delimited file as a table of text.

    Args:
        source: The bytes of the file, or the path to read them from.
        header_line: The line that holds the column names, counting from 1. The lines before
            it (the preamble) are skipped.
        na_values: The texts that mean a missing value in this file. Nothing else is missing,
            and the default list of pandas is off: `#N/A` is a code in a budget file and
            `NA` is a missing value in another. An empty cell is missing only if `""` is
            listed.

    Returns:
        A table where every cell is text, and the missing values are NaN.
    """
    text = normalise_line_ends(read_text(source))
    lines = text.split("\n")
    delimiter = detect_delimiter(lines[header_line - 1])
    return pd.read_csv(
        io.StringIO(text),
        sep=delimiter,
        skiprows=header_line - 1,
        dtype=str,
        keep_default_na=False,
        na_values=list(na_values),
    )


def read_preamble(source: bytes | Path) -> Preamble:
    """Read the year and the budget part from the preamble of a pivot export.

    The preamble is made of lines such as `Gestion;2016` and `Type Budget;Budget général`,
    in any letter case. The two lines are searched in the first ten lines.

    Args:
        source: The bytes of the file, or the path to read them from.

    Returns:
        The year and the budget part.

    Raises:
        ValueError: If the first ten lines lack one of the two lines.
    """
    year: int | None = None
    budget_part: str | None = None
    for line in normalise_line_ends(read_text(source)).split("\n")[:10]:
        key, _, rest = line.partition(";")
        value = rest.split(";")[0].strip()
        if _GESTION.match(key.strip()):
            year = int(value)
        elif _BUDGET_TYPE.match(key.strip()):
            budget_part = value
    if year is None or budget_part is None:
        raise ValueError("The first lines hold no `Gestion` line or no `Type Budget` line")
    return Preamble(year=year, budget_part=budget_part)
