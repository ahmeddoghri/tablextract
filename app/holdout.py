"""A held-out document and question set, committed so the number can be rerun.

The README used to quote a held-out result (cells 4/4, questions 7/7, zero
fabricated citations) from a set that was evaluated once and never committed.
A number nobody can rerun is a claim, not a measurement, so this replaces it.

Written on 2026-10-19 with the v1 and v2 code frozen, in a domain the tuning
corpus never used (lab assay results), and evaluated once. The result lives in
``holdout_benchmark.json`` and is diffed in CI. Do not tune against this file:
a case that drives a code change belongs in ``docbench.py`` instead.

    python -m app.holdout
"""

from __future__ import annotations

import argparse
import json
from typing import Dict, List

from .docbench import CellExpectation, QueryCase
from .docbench_run import _lookup
from .extractor import TextTableExtractor
from .extractor_v2 import RobustTableExtractor
from .query import answer_query as query_v1
from .query_v2 import answer_query as query_v2

ASSAY_REPORT = """\
Appendix B: Assay Results by Site

Samples were analysed in duplicate. Values below the limit of quantitation
are reported as BLQ and were excluded from the summary statistics.

Site        Analyte       Mean_ng  CV_pct
Site 1      Creatinine    84       6.2
Site 2      Creatinine    91       7.9
DRAFT - NOT FOR DISTRIBUTION - Page 14 of 40
Site 3      Bilirubin     BLQ      n/a
Site 4      Albumin and   4100     3.1
            total protein
Site 5      Creatinine    77       5.4

Page 15 of 40

Site        Analyte       Mean_ng  CV_pct
Site 6      Bilirubin     12       11.0
Site 7      Albumin       3950     2.8
"""

DOCUMENTS: Dict[str, str] = {"assay_report": ASSAY_REPORT}

CELLS: List[CellExpectation] = [
    CellExpectation("assay_report", "Site 1", "Mean_ng", "84"),
    CellExpectation("assay_report", "Site 3", "Mean_ng", "BLQ", "after the draft banner"),
    CellExpectation("assay_report", "Site 4", "CV_pct", "3.1", "row with a wrapped cell"),
    CellExpectation("assay_report", "Site 5", "Mean_ng", "77", "after the wrapped cell"),
    CellExpectation("assay_report", "Site 6", "CV_pct", "11.0", "continuation page"),
    CellExpectation("assay_report", "Site 7", "Mean_ng", "3950", "continuation page"),
]

QUESTIONS: List[QueryCase] = [
    QueryCase("assay_report", "What is the Mean_ng for Site 2?", "91", "answerable"),
    QueryCase("assay_report", "What is the CV_pct for Site 5?", "5.4", "answerable"),
    QueryCase("assay_report", "What is the Mean_ng for Site 7?", "3950", "answerable"),
    QueryCase("assay_report", "What is the Mean_ng for Site 9?", None, "missing_row"),
    QueryCase("assay_report", "What is the CV_pct for the reference lab?", None, "missing_row"),
    QueryCase("assay_report", "What is the median_ng for Site 1?", None, "missing_column"),
    QueryCase("assay_report", "What is the Mean_ng for Jupiter?", None, "nonsense"),
]


def score_cells(extractor) -> Dict:
    found, missing = 0, []
    for e in CELLS:
        tables = extractor.extract(DOCUMENTS[e.document], source=e.document)
        if _lookup(tables, e.row_label, e.column) == e.value:
            found += 1
        else:
            missing.append(f"{e.row_label}/{e.column}")
    return {"cells_found": found, "cells_expected": len(CELLS), "missing": missing}


def score_questions(extractor, answerer) -> Dict:
    correct, fabricated, missed = 0, [], []
    for case in QUESTIONS:
        tables = extractor.extract(DOCUMENTS[case.document], source=case.document)
        answer = answerer(case.question, tables)
        if case.answerable:
            if answer.found and answer.value == case.expected:
                correct += 1
            else:
                missed.append(f"{case.question} -> {answer.value!r}")
        elif answer.found:
            fabricated.append(
                f"{case.question} -> {answer.value!r} cited to {answer.row_label}/{answer.column}"
            )
        else:
            correct += 1
    return {
        "correct": correct,
        "total": len(QUESTIONS),
        "fabricated_citations": len(fabricated),
        "fabricated": fabricated,
        "missed": missed,
    }


def build_report() -> Dict:
    return {
        "v1": {
            "cells": score_cells(TextTableExtractor()),
            "questions": score_questions(TextTableExtractor(), query_v1),
        },
        "v2": {
            "cells": score_cells(RobustTableExtractor()),
            "questions": score_questions(RobustTableExtractor(), query_v2),
        },
    }


def format_report(report: Dict) -> str:
    lines = [f"Held-out set: 1 document, {len(CELLS)} cells, {len(QUESTIONS)} questions", ""]
    for name, row in report.items():
        cells, questions = row["cells"], row["questions"]
        lines.append(
            f"{name}  cells {cells['cells_found']}/{cells['cells_expected']}  "
            f"questions {questions['correct']}/{questions['total']}  "
            f"fabricated citations {questions['fabricated_citations']}"
        )
        for item in cells["missing"]:
            lines.append(f"    missing cell: {item}")
        for item in questions["missed"]:
            lines.append(f"    missed: {item}")
        for item in questions["fabricated"]:
            lines.append(f"    fabricated: {item}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    report = build_report()
    print(format_report(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")


if __name__ == "__main__":
    main()
