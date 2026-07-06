"""Does block-aware table extraction actually beat naively parsing every
line the same way?

Real regulatory documents interleave prose paragraphs with data tables --
adverse-event counts, dosage schedules, demographic breakdowns -- with no
explicit markup separating the two. A naive extractor that treats the whole
document as one table gets corrupted the moment it hits a paragraph: prose
lines become garbage "rows," and worse, every row after that is misaligned
against a header. We measure cell-level extraction accuracy against a hand-
labeled ground truth on a synthetic document built to look like this.

    python -m app.eval
"""
from __future__ import annotations

from .extractor import NaiveExtractor, TextTableExtractor
from .schema import Table

# A document mixing narrative text with two data tables, the way an actual
# FDA submission or IND safety report reads -- not a clean CSV-in-disguise.
DOCUMENT = """\
Section 4: Adverse Event Summary

The following table summarizes treatment-emergent adverse events observed
across all study cohorts during the current reporting period. Grade 3 and
above events were reviewed by the DSMB and none were assessed as related to
study drug.

Cohort      Grade1  Grade2  Grade3
Cohort A    12      4       1
Cohort B    9       3       0
Cohort C    15      6       2

No grade 4 or grade 5 events occurred in any cohort during this period, and
enrollment continues per protocol.

Section 5: Dosing Schedule

The table below lists the dosing schedule by cohort, unchanged from protocol
amendment v2 for cohorts A and B, and updated per amendment v3 for cohort C.

Cohort      Dose_mg  Frequency
Cohort A    50       Daily
Cohort B    100      Daily
Cohort C    150      Weekly

Site coordinators should reference the site manual for administration
guidance and adverse event reporting timelines.
"""

# ground truth: (table_index, row_label, column, expected_value)
GROUND_TRUTH = [
    (0, "Cohort A", "Grade1", "12"),
    (0, "Cohort A", "Grade3", "1"),
    (0, "Cohort B", "Grade2", "3"),
    (0, "Cohort C", "Grade3", "2"),
    (1, "Cohort A", "Dose_mg", "50"),
    (1, "Cohort B", "Frequency", "Daily"),
    (1, "Cohort C", "Dose_mg", "150"),
    (1, "Cohort C", "Frequency", "Weekly"),
]


def _cell_accuracy(tables: list[Table]) -> tuple[int, int]:
    correct = 0
    for table_idx, row_label, column, expected in GROUND_TRUTH:
        if table_idx >= len(tables):
            continue
        actual = tables[table_idx].find_cell(row_label, column)
        if actual == expected:
            correct += 1
    return correct, len(GROUND_TRUTH)


def run() -> dict:
    naive_tables = NaiveExtractor().extract(DOCUMENT, source="synthetic_report")
    smart_tables = TextTableExtractor().extract(DOCUMENT, source="synthetic_report")

    naive_correct, total = _cell_accuracy(naive_tables)
    smart_correct, _ = _cell_accuracy(smart_tables)

    return {
        "total_cells": total,
        "naive_tables_found": len(naive_tables),
        "naive_correct": naive_correct,
        "naive_accuracy": round(naive_correct / total, 4),
        "smart_tables_found": len(smart_tables),
        "smart_correct": smart_correct,
        "smart_accuracy": round(smart_correct / total, 4),
    }


def main() -> None:
    r = run()
    print("document: mixed prose + 2 data tables (adverse events, dosing schedule)\n")
    print(f"{'extractor':<12}{'tables found':>14}{'cells correct':>16}{'accuracy':>12}")
    print(f"{'naive':<12}{r['naive_tables_found']:>14}{r['naive_correct']:>13}/{r['total_cells']:<3}"
          f"{r['naive_accuracy']:>11.0%}")
    print(f"{'tablextract':<12}{r['smart_tables_found']:>14}{r['smart_correct']:>13}/{r['total_cells']:<3}"
          f"{r['smart_accuracy']:>11.0%}")


if __name__ == "__main__":
    main()
