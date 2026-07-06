"""Shared data model for extracted tables."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    source: str = ""          # document/page identifier
    confidence: float = 1.0   # extractor's confidence this is a real table, not prose

    def to_dict(self) -> dict:
        return {"headers": self.headers, "rows": self.rows,
                "source": self.source, "confidence": self.confidence}

    def find_cell(self, row_key: str, column: str) -> str | None:
        """Look up a cell by matching the first column's value (row label)
        and a header name -- the common regulatory-table access pattern
        ("what's the Grade 3 count for Cohort B")."""
        if column not in self.headers:
            return None
        col_idx = self.headers.index(column)
        for row in self.rows:
            if row and row_key.lower() in row[0].lower():
                return row[col_idx] if col_idx < len(row) else None
        return None
