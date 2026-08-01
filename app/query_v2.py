"""Answering a question against extracted tables, including "I cannot".

The original scorer added a column-match score to a row-match score and
returned the best total. Any question mentioning a real column name therefore
produced an answer, because a column match alone clears the zero bar. Asked
"What is Grade1 for the moon?", it returned 12, cited to Cohort A, Grade1.

For a tool whose entire value is a citation to the exact row and column, that
is the worst available failure. A wrong answer with no citation gets checked.
A wrong answer *with* a citation looks verified, and a reviewer signs it off.

So the scoring here is a conjunction, not a sum. A cell is only an answer when
the question identifies both the row and the column, each above its own
threshold. Failing either one produces an explicit "not found" carrying the
reason, and the near-misses that were rejected, so the caller can see what the
document does contain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .schema import Table

_WORD = re.compile(r"[a-z0-9_]+")

# Question scaffolding that matches everything and identifies nothing. Left in,
# a question like "what is the value for" would score against every row.
_QUESTION_STOP = {
    "what", "which", "who", "when", "where", "how", "is", "was", "are", "were",
    "the", "a", "an", "of", "for", "in", "on", "at", "to", "and", "or", "do",
    "does", "did", "value", "number", "count", "many", "much", "me", "tell",
    "show", "give", "report", "please", "s",
}

#: A row label has to be more than incidentally present in the question.
#: Below this, the question is not about any row in the table.
DEFAULT_MIN_ROW_SCORE = 0.5
#: A column needs at least one distinctive token in common.
DEFAULT_MIN_COLUMN_SCORE = 0.5


def tokenize(text: str) -> set:
    """Tokenize a question, dropping scaffolding that identifies nothing."""
    return {t for t in _WORD.findall(text.lower()) if t not in _QUESTION_STOP}


def tokenize_label(text: str) -> set:
    """Tokenize a row or column label, keeping every token.

    Deliberately does not apply the question stopwords. "Cohort A" contains
    the article "a", and stripping it leaves {"cohort"}, which then matches a
    question about Cohort B or Cohort Z at full coverage. The distinguishing
    token of a row label is frequently a single letter or digit, so a label
    has no stopwords: everything in it is data.
    """
    return set(_WORD.findall(text.lower()))


def _coverage(label: str, question_tokens: set) -> float:
    """Share of a label's own tokens that the question mentions.

    Coverage of the *label*, not of the question, is what matters: "Cohort Z"
    and "Cohort A" both share "cohort" with the question, so the deciding
    token is the one that distinguishes them.
    """
    label_tokens = tokenize_label(label)
    if not label_tokens:
        return 0.0
    return len(label_tokens & question_tokens) / len(label_tokens)


@dataclass
class Candidate:
    table: Table
    row_label: str
    column: str
    value: str
    row_score: float
    column_score: float

    @property
    def score(self) -> float:
        return (self.row_score + self.column_score) / 2


@dataclass
class QueryAnswer:
    value: Optional[str]
    table_source: Optional[str]
    row_label: Optional[str]
    column: Optional[str]
    found: bool
    #: Why nothing was returned, when nothing was.
    reason: str = ""
    row_score: float = 0.0
    column_score: float = 0.0
    #: Rejected near-misses, so a caller can see what the document does have.
    near_misses: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "table_source": self.table_source,
            "row_label": self.row_label,
            "column": self.column,
            "found": self.found,
            "reason": self.reason,
            "row_score": round(self.row_score, 4),
            "column_score": round(self.column_score, 4),
            "near_misses": self.near_misses,
        }


def _candidates(question_tokens: set, tables: List[Table]) -> List[Candidate]:
    found: List[Candidate] = []
    for table in tables:
        # The first column holds row labels, not answerable values; matching it
        # as an answer column returns the label back to the caller.
        for column_index, column in enumerate(table.headers):
            if column_index == 0:
                continue
            column_score = _coverage(column, question_tokens)
            if column_score == 0.0:
                continue
            for row in table.rows:
                if not row or column_index >= len(row):
                    continue
                found.append(
                    Candidate(
                        table=table,
                        row_label=row[0],
                        column=column,
                        value=row[column_index],
                        row_score=_coverage(row[0], question_tokens),
                        column_score=column_score,
                    )
                )
    return found


def answer_query(
    question: str,
    tables: List[Table],
    min_row_score: float = DEFAULT_MIN_ROW_SCORE,
    min_column_score: float = DEFAULT_MIN_COLUMN_SCORE,
) -> QueryAnswer:
    """Answer from the tables, or decline and say why."""
    # The question keeps its identifiers: "cohort b" must retain the "b".
    question_tokens = tokenize(question) | set(_WORD.findall(question.lower()))
    if not question_tokens:
        return QueryAnswer(None, None, None, None, False, "the question has no content words")

    if not tables:
        return QueryAnswer(None, None, None, None, False, "no tables were extracted")

    candidates = _candidates(question_tokens, tables)
    if not candidates:
        columns = sorted(
            {c for t in tables for c in t.headers[1:]}
        )
        return QueryAnswer(
            None, None, None, None, False,
            "no column in the document matches the question",
            near_misses=columns[:8],
        )

    candidates.sort(key=lambda c: (c.score, c.row_score), reverse=True)
    best = candidates[0]

    # Both halves must independently clear their bar. Summing them is what let
    # a column match alone carry an answer for a row that does not exist.
    if best.column_score < min_column_score:
        return QueryAnswer(
            None, None, None, None, False,
            f"no column matched well enough (best {best.column_score:.2f})",
            row_score=best.row_score, column_score=best.column_score,
            near_misses=sorted({c.column for c in candidates})[:8],
        )

    row_best = max(candidates, key=lambda c: c.row_score)
    if row_best.row_score < min_row_score:
        return QueryAnswer(
            None, None, None, None, False,
            f"no row matched well enough (best {row_best.row_score:.2f})",
            row_score=row_best.row_score, column_score=best.column_score,
            near_misses=sorted({c.row_label for c in candidates})[:8],
        )

    # Ambiguity is also a reason to decline: two rows matching equally well
    # means the question did not identify one of them.
    qualified = [
        c for c in candidates
        if c.row_score >= min_row_score and c.column_score >= min_column_score
    ]
    top = max(qualified, key=lambda c: c.score)
    tied = [c for c in qualified if abs(c.score - top.score) < 1e-9]
    if len({(c.row_label, c.column) for c in tied}) > 1:
        return QueryAnswer(
            None, None, None, None, False,
            "the question matches more than one cell equally well",
            row_score=top.row_score, column_score=top.column_score,
            near_misses=[f"{c.row_label} / {c.column}" for c in tied][:8],
        )

    return QueryAnswer(
        value=top.value,
        table_source=top.table.source,
        row_label=top.row_label,
        column=top.column,
        found=True,
        row_score=top.row_score,
        column_score=top.column_score,
    )
