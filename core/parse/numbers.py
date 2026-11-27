"""Parse amounts and codes of the State budget files.

An amount is read as an exact `Decimal`, never as a float. A text that is not an amount is an
error that names the text, so that a parser cannot turn it into a zero by accident.
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from core.parse.decoding import detect_delimiter, normalise_line_ends, read_text

SPACES = "   "

_PLAIN_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_SCIENTIFIC = re.compile(r"^-?\d+([.,]\d+)?E[+-]?\d+$", re.IGNORECASE)
_FLOAT_CODE = re.compile(r"^(\d+)\.0+$")


class AmountError(ValueError):
    """A text is not an amount that can be read exactly."""


@dataclass(frozen=True)
class ScientificCell:
    """A cell written in scientific notation, which holds an approximate amount."""

    #: The line of the cell, counting LF bytes from the first line of the file.
    line: int
    #: The position of the column, counting from 0.
    column_index: int
    #: The name of the column, from the header; empty if the header does not name it.
    column: str
    #: The text of the cell, for example `1,07584E+11`.
    text: str


def is_scientific(text: str) -> bool:
    """Tell whether a text is an amount in scientific notation, such as `1,07584E+11`."""
    return bool(_SCIENTIFIC.match(text.strip()))


def parse_amount(text: str) -> Decimal | None:
    """Parse an amount as written in the budget files.

    Spaces and non-breaking spaces (thousands separators) are removed, then a decimal comma
    becomes a point. `42 355 399` gives 42355399, `3397166072,6` gives 3397166072.6.

    Args:
        text: The text of one cell.

    Returns:
        The exact amount, or None if the cell is empty. An empty cell is not a zero, and the
        caller decides what it means.

    Raises:
        AmountError: If the text is not an exact amount. This covers a lone `-` (padded with
            spaces or not), which is neither an empty cell nor a number, and an amount in
            scientific notation, which has lost digits.
    """
    cleaned = text.translate(str.maketrans("", "", SPACES))
    if cleaned == "":
        return None
    if is_scientific(cleaned):
        raise AmountError(f"Amount in scientific notation, not exact: {text!r}")
    cleaned = cleaned.replace(",", ".")
    if not _PLAIN_NUMBER.match(cleaned):
        raise AmountError(f"Not an amount: {text!r}")
    return Decimal(cleaned)


def normalise_code(text: str) -> str:
    """Return a code as text, undoing the float form of a spreadsheet.

    `7.0` becomes `7` and `2020.0` becomes `2020`. Any other code is returned as it is, after
    its surrounding spaces are removed: `07` keeps its zero, `348-11` and `#N/A` stay text.

    Args:
        text: The text of one code cell.

    Returns:
        The code as text.
    """
    stripped = text.strip(SPACES)
    match = _FLOAT_CODE.match(stripped)
    return match.group(1) if match else stripped


def _records(text: str, header_line: int) -> Iterator[tuple[int, list[str]]]:
    """Yield (first line, cells) for each record, counting LF bytes from 1.

    The delimiter is detected on the header line, as `read_table` does.
    """
    lines = list(io.StringIO(text, newline="\n"))
    reader = csv.reader(lines, delimiter=detect_delimiter(lines[header_line - 1]))
    previous = 0
    for cells in reader:
        yield previous + 1, cells
        previous = reader.line_num


def find_scientific_cells(source: bytes | Path, *, header_line: int = 1) -> list[ScientificCell]:
    """List every cell of a file that is in scientific notation.

    The 2023 files write an amount in at most 11 characters, so a large amount is rounded to
    six significant digits in scientific notation, without an error. The list gives the
    totals checks every cell that cannot be read exactly.

    Args:
        source: The bytes of the file, or the path to read them from.
        header_line: The line that holds the column names, counting from 1, as in
            `read_table`. The lines before it (the preamble) hold no amount and are not
            scanned.

    Returns:
        One entry per cell, in file order. The line counts LF bytes from the first line of
        the file, so a bare CR in a label does not shift it and the line points to the same
        line in the raw file whatever the header line is. A cell in a column that the header
        does not name has an empty column name.
    """
    text = normalise_line_ends(read_text(source))
    header: list[str] = []
    found: list[ScientificCell] = []
    for line, cells in _records(text, header_line):
        if line < header_line:
            continue
        if line == header_line:
            header = cells
            continue
        found.extend(
            ScientificCell(line, index, header[index] if index < len(header) else "", cell)
            for index, cell in enumerate(cells)
            if is_scientific(cell)
        )
    return found
