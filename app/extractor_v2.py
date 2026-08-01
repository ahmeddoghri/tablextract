"""Table extraction that survives what PDF text layers actually contain.

The block-based extractor treats any line that does not split into columns as
the end of a table. That is the right instinct for prose, and wrong for
everything else a PDF puts between two data rows:

* A page banner ("CONFIDENTIAL - Page 3 of 12") ends the block, and every row
  after it is silently discarded.
* A wrapped cell continuing onto an indented line ends the block, truncating
  the table at that point.
* A table continuing on the next page becomes a second, separate table, so a
  lookup for a row on page two fails against table one.

Each of those loses data while the extractor reports confidence 1.0, which is
the specific failure this project exists to warn about: not "cannot read the
PDF" but "read it wrong and said nothing".

This module keeps the block idea and adds the classifications that make it
survive real documents. Every line gets a role, and confidence reflects how
much of the block actually looked tabular, so a partially-recovered table
reports a number below 1.0 rather than pretending.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from .schema import Table

_MULTISPACE = re.compile(r"\s{2,}")

# Page furniture: banners, page numbers, confidentiality notices, footers.
# These appear mid-table constantly and are never data.
_PAGE_FURNITURE = re.compile(
    r"^\s*(?:"
    r"page\s+\d+(?:\s+of\s+\d+)?"
    r"|\d+\s*/\s*\d+"
    r"|confidential[^\n]*"
    r"|proprietary[^\n]*"
    r"|draft[^\n]*"
    r"|[-–—_=*]{3,}"
    r"|\[?\s*continued\s*\]?"
    r"|\(continued\)"
    r")\s*$",
    re.IGNORECASE,
)

# A line carrying a page marker plus other boilerplate, e.g.
# "Study Protocol XYZ-2024        Revision 3".
_FURNITURE_TOKENS = re.compile(
    r"\b(confidential|proprietary|page \d+|revision \d+|version \d+\.\d+|"
    r"do not distribute|internal use only)\b",
    re.IGNORECASE,
)

_PROSE_HINT = re.compile(
    r"\b(the|this|these|following|summarizes|observed|during|were|was|and|"
    r"that|which|per|study|patients?|reported)\b",
    re.IGNORECASE,
)


class LineRole(Enum):
    """What a line is, which decides whether it can end a table."""

    DATA = "data"
    FURNITURE = "furniture"       # skip, but do not end the table
    CONTINUATION = "continuation"  # a wrapped cell from the row above
    PROSE = "prose"               # ends the table
    BLANK = "blank"               # ends the table, unless a page break follows


@dataclass
class ClassifiedLine:
    text: str
    role: LineRole
    cells: List[str]
    indent: int


def split_row(line: str) -> List[str]:
    if "|" in line:
        return [c.strip() for c in line.strip().strip("|").split("|")]
    return [c.strip() for c in _MULTISPACE.split(line.strip()) if c.strip()]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _looks_like_prose(line: str, cells: List[str]) -> bool:
    """Distinguish a justified paragraph from a data row.

    PDF justification pads prose with multiple spaces, so word count alone
    cannot separate the two. What does: table cells are short and mostly
    non-words, while a prose line is long, full of function words, and ends
    in sentence punctuation.
    """
    stripped = line.strip()
    if not stripped:
        return False

    prose_words = len(_PROSE_HINT.findall(stripped))
    words = stripped.split()
    long_cells = sum(1 for c in cells if len(c.split()) >= 4)

    # Several function words alongside a multi-word cell is a sentence,
    # however it was spaced.
    if prose_words >= 3 and long_cells >= 1:
        return True
    if prose_words >= 2 and len(cells) <= 2 and len(words) >= 8:
        return True
    if stripped.endswith((".", ";")) and prose_words >= 2 and long_cells >= 1:
        return True

    # Justified text is the hard case: PDF padding puts multiple spaces
    # between every word, so each word becomes its own "cell" and the
    # multi-word-cell test above never fires. What still separates it from a
    # data row is that a table row carries numbers and short labels, while a
    # justified sentence is a long run of single function words.
    if len(cells) >= 4 and prose_words >= 3:
        numeric_cells = sum(1 for c in cells if any(ch.isdigit() for ch in c))
        single_word_cells = sum(1 for c in cells if len(c.split()) == 1)
        if numeric_cells == 0 and single_word_cells >= len(cells) - 1:
            return True
    return False


def classify_line(line: str, expected_columns: Optional[int], body_indent: int) -> ClassifiedLine:
    """Assign a role to one line, given the shape of the table so far."""
    cells = split_row(line)
    indent = _indent(line)

    if not line.strip():
        return ClassifiedLine(line, LineRole.BLANK, [], indent)

    if _PAGE_FURNITURE.match(line.strip()) or _FURNITURE_TOKENS.search(line.strip()):
        # Furniture only counts as furniture when it is not also plausible
        # data; a row whose label happens to contain "Revision 3" is data.
        if expected_columns is None or len(cells) < expected_columns:
            return ClassifiedLine(line, LineRole.FURNITURE, cells, indent)

    if _looks_like_prose(line, cells):
        return ClassifiedLine(line, LineRole.PROSE, cells, indent)

    # A short, deeply indented line inside a table is a wrapped cell, not a
    # new row: the first column is empty because the label is on the line above.
    if (
        expected_columns is not None
        and indent > body_indent
        and len(cells) < expected_columns
    ):
        return ClassifiedLine(line, LineRole.CONTINUATION, cells, indent)

    if len(cells) >= 2:
        return ClassifiedLine(line, LineRole.DATA, cells, indent)

    return ClassifiedLine(line, LineRole.PROSE, cells, indent)


@dataclass
class ExtractionTrace:
    """What the extractor did, so a dropped row can be explained."""

    furniture_skipped: int = 0
    continuations_joined: int = 0
    prose_lines_skipped: int = 0
    fragments_merged: int = 0
    rows_dropped: int = 0


class RobustTableExtractor:
    """Block extraction that tolerates furniture, wrapping, and page breaks."""

    def __init__(
        self,
        min_columns: int = 2,
        min_rows: int = 2,
        merge_page_breaks: bool = True,
    ) -> None:
        self.min_columns = min_columns
        self.min_rows = min_rows
        self.merge_page_breaks = merge_page_breaks
        self.trace = ExtractionTrace()

    # --- block assembly -----------------------------------------------------

    def _blocks(self, text: str) -> List[List[ClassifiedLine]]:
        """Group lines into candidate table blocks.

        Furniture and continuations are kept inside the block rather than
        ending it, which is the whole difference from the original.
        """
        blocks: List[List[ClassifiedLine]] = []
        current: List[ClassifiedLine] = []
        expected_columns: Optional[int] = None
        body_indent = 0

        def flush() -> None:
            nonlocal current, expected_columns
            if current:
                blocks.append(current)
            current = []
            expected_columns = None

        for raw in text.splitlines():
            classified = classify_line(raw, expected_columns, body_indent)

            if classified.role is LineRole.BLANK:
                flush()
                continue

            if classified.role is LineRole.PROSE:
                self.trace.prose_lines_skipped += 1
                flush()
                continue

            if classified.role is LineRole.FURNITURE:
                # Deliberately does not flush: the table continues underneath.
                self.trace.furniture_skipped += 1
                continue

            if classified.role is LineRole.CONTINUATION:
                if current:
                    self.trace.continuations_joined += 1
                    current.append(classified)
                continue

            if not current:
                expected_columns = len(classified.cells)
                body_indent = classified.indent
            current.append(classified)

        flush()
        return blocks

    # --- row assembly -------------------------------------------------------

    @staticmethod
    def _column_offsets(line: str) -> List[int]:
        """Character offset where each cell starts, from the raw line."""
        offsets = []
        position = 0
        for cell in _MULTISPACE.split(line.rstrip()):
            if not cell.strip():
                position += len(cell) + 2
                continue
            offsets.append(line.index(cell.strip(), position))
            position = offsets[-1] + len(cell.strip())
        return offsets

    @classmethod
    def _join_continuations(cls, lines: List[ClassifiedLine]) -> List[List[str]]:
        """Fold continuation lines into the row above, in the right column.

        Which column a wrapped fragment belongs to is decided by where it
        starts on the line, not by which cell happens to be last. Appending to
        the last non-empty cell puts "regimen per amendment v2" onto the dose
        column, turning "50" into "50 regimen per amendment v2" -- a corrupted
        value that still looks like a successful extraction.
        """
        rows: List[List[str]] = []
        header_offsets: List[int] = []

        for line in lines:
            if line.role is LineRole.CONTINUATION and rows:
                extra = " ".join(line.cells).strip()
                if not extra:
                    continue
                target = rows[-1]
                # Match the fragment's start column against the header's.
                start = line.indent
                index = 0
                for column, offset in enumerate(header_offsets):
                    if start >= offset - 1:
                        index = column
                if index >= len(target):
                    index = len(target) - 1
                target[index] = f"{target[index]} {extra}".strip()
                continue

            if not header_offsets:
                header_offsets = cls._column_offsets(line.text)
            rows.append(list(line.cells))
        return rows

    def _table_from_block(self, lines: List[ClassifiedLine], source: str) -> Optional[Table]:
        rows = self._join_continuations(lines)
        if len(rows) < self.min_rows:
            return None

        column_count = len(rows[0])
        if column_count < self.min_columns:
            return None

        consistent = [r for r in rows if len(r) == column_count]
        dropped = len(rows) - len(consistent)
        self.trace.rows_dropped += dropped
        if len(consistent) < self.min_rows:
            return None

        # Confidence is the share of lines that fit the table's own shape. A
        # block where a third of the rows had to be discarded should not claim
        # the same certainty as one that parsed cleanly.
        confidence = len(consistent) / len(rows)
        return Table(
            headers=consistent[0],
            rows=consistent[1:],
            source=source,
            confidence=round(confidence, 4),
        )

    # --- page-break merging -------------------------------------------------

    @staticmethod
    def _same_shape(a: Table, b: Table) -> bool:
        """Whether ``b`` is a continuation of ``a`` rather than a new table."""
        if len(a.headers) != len(b.headers):
            return False
        return [h.strip().lower() for h in a.headers] == [
            h.strip().lower() for h in b.headers
        ]

    def _merge_fragments(self, tables: List[Table]) -> List[Table]:
        """Join consecutive tables that repeat the same header."""
        if not tables:
            return tables
        merged = [tables[0]]
        for table in tables[1:]:
            previous = merged[-1]
            if self._same_shape(previous, table):
                previous.rows.extend(table.rows)
                # Confidence of a merged table is the weaker of its parts.
                previous.confidence = round(
                    min(previous.confidence, table.confidence), 4
                )
                self.trace.fragments_merged += 1
            else:
                merged.append(table)
        return merged

    # --- entry point --------------------------------------------------------

    def extract(self, text: str, source: str = "") -> List[Table]:
        self.trace = ExtractionTrace()
        tables: List[Table] = []
        for block in self._blocks(text):
            table = self._table_from_block(block, source)
            if table is not None:
                tables.append(table)
        if self.merge_page_breaks:
            tables = self._merge_fragments(tables)
        return tables

    def extract_with_trace(
        self, text: str, source: str = ""
    ) -> Tuple[List[Table], ExtractionTrace]:
        """Extract, and report what was skipped, joined, or dropped."""
        tables = self.extract(text, source)
        return tables, self.trace
