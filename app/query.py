"""Answer a question against extracted tables, with a citation back to the
exact table/row/column it came from -- the same discipline as citation-
grounded RAG, applied to structured data instead of prose passages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .schema import Table

_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class QueryAnswer:
    value: Optional[str]
    table_source: Optional[str]
    row_label: Optional[str]
    column: Optional[str]
    found: bool


def answer_query(question: str, tables: list[Table]) -> QueryAnswer:
    """Very small heuristic: find the header (column) whose name shares the
    most tokens with the question, then find the row whose label shares the
    most tokens with whatever's left. Good enough for well-labeled regulatory
    tables (rows keyed by cohort/visit/entity, columns keyed by metric name).
    """
    q_tokens = set(_WORD.findall(question.lower()))
    best: tuple[float, Table, str, str, str] | None = None  # score, table, row_label, column, value

    for table in tables:
        # the first column is the row label/index (e.g. "Cohort"), not a
        # queryable value field -- matching it as an "answer column" would
        # return the row label itself instead of an actual metric
        for col in table.headers[1:]:
            col_tokens = set(_WORD.findall(col.lower()))
            col_score = len(col_tokens & q_tokens)
            if col_score == 0:
                continue
            for row in table.rows:
                if not row:
                    continue
                row_label = row[0]
                row_tokens = set(_WORD.findall(row_label.lower()))
                row_score = len(row_tokens & q_tokens)
                total = col_score + row_score
                col_idx = table.headers.index(col)
                value = row[col_idx] if col_idx < len(row) else None
                if value is None:
                    continue
                if best is None or total > best[0]:
                    best = (total, table, row_label, col, value)

    if best is None or best[0] == 0:
        return QueryAnswer(None, None, None, None, found=False)

    _, table, row_label, col, value = best
    return QueryAnswer(value=value, table_source=table.source, row_label=row_label,
                       column=col, found=True)
