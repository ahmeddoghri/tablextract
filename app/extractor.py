"""Table extraction from document text.

Real regulatory PDFs, once you've pulled a text layer out of them (via
pdfplumber, an OCR engine, whatever), give you a mix of prose paragraphs and
table blocks with no explicit markup -- you have to figure out which lines
are actually tabular and how they're column-aligned. That's what this module
does. ``PdfplumberExtractor`` is the real-PDF path (lazy-imported, optional
dependency); the default ``TextTableExtractor`` operates on already-extracted
text, which is exactly pdfplumber's own output shape, so the same downstream
logic applies to both.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .schema import Table

_MULTISPACE = re.compile(r"\s{2,}")


def _split_row(line: str) -> list[str]:
    if "|" in line:
        return [c.strip() for c in line.strip().strip("|").split("|")]
    return [c.strip() for c in _MULTISPACE.split(line.strip()) if c.strip()]


class TableExtractor(Protocol):
    def extract(self, text: str, source: str = "") -> list[Table]:
        ...


class NaiveExtractor:
    """Baseline: treat the whole input as one table, split every line the
    same way, first line is always the header. Fast, and wrong whenever the
    document mixes prose with tables or has inconsistent column counts --
    which real regulatory documents always do.
    """

    def extract(self, text: str, source: str = "") -> list[Table]:
        lines = [l for l in text.splitlines() if l.strip()]
        if not lines:
            return []
        rows = [_split_row(l) for l in lines]
        return [Table(headers=rows[0], rows=rows[1:], source=source, confidence=0.5)]


class TextTableExtractor:
    """Finds contiguous blocks of consistently-column-aligned lines and treats
    each block as a separate table, skipping prose in between. This is the
    actual mechanism that matters: regulatory PDFs interleave narrative text
    and tables constantly, and naively parsing "everything" produces garbage
    rows out of paragraph text.
    """

    def __init__(self, min_columns: int = 2, min_rows: int = 2) -> None:
        self.min_columns = min_columns
        self.min_rows = min_rows

    def extract(self, text: str, source: str = "") -> list[Table]:
        lines = text.splitlines()
        blocks: list[list[str]] = []
        current: list[str] = []

        for line in lines:
            if not line.strip():
                if current:
                    blocks.append(current)
                    current = []
                continue
            cells = _split_row(line)
            if len(cells) >= self.min_columns:
                current.append(line)
            else:
                if current:
                    blocks.append(current)
                    current = []
        if current:
            blocks.append(current)

        tables = []
        for block in blocks:
            rows = [_split_row(l) for l in block]
            col_count = len(rows[0])
            consistent = [r for r in rows if len(r) == col_count]
            if len(consistent) < self.min_rows:
                continue
            confidence = len(consistent) / len(rows)
            tables.append(Table(headers=consistent[0], rows=consistent[1:],
                                source=source, confidence=round(confidence, 4)))
        return tables


class PdfplumberExtractor:
    """Real PDF extraction via pdfplumber. Optional dependency, lazily
    imported so the service and its tests never require it unless you're
    actually processing PDF binaries.
    """

    def extract(self, pdf_bytes: bytes, source: str = "") -> list[Table]:
        import io

        import pdfplumber

        tables = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                for raw_table in page.extract_tables():
                    if not raw_table or len(raw_table) < 2:
                        continue
                    headers = [c or "" for c in raw_table[0]]
                    rows = [[c or "" for c in r] for r in raw_table[1:]]
                    tables.append(Table(headers=headers, rows=rows,
                                        source=f"{source}#page={page_num}"))
        return tables
