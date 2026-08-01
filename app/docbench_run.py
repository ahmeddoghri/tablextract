"""Scoring extraction and querying against documents built to break them.

Two numbers matter here, and only one of them is in the original benchmark.

**Cell recall** is whether the data survived extraction at all. The block
extractor loses rows to page banners and wrapped cells while reporting
confidence 1.0, which is the silent failure this project was written to warn
about.

**Fabricated citations** is whether the query layer invents an answer for a
row that does not exist. That number belongs on its own line because it is
categorically worse than a miss: an uncited wrong answer gets checked, and a
wrong answer carrying a row and column reference looks verified.

    python -m app.docbench_run
"""

from __future__ import annotations

import argparse
import json
from typing import Dict, List

from .docbench import CELL_EXPECTATIONS, DOCUMENTS, QUERY_CASES
from .extractor import NaiveExtractor, TextTableExtractor
from .extractor_v2 import RobustTableExtractor
from .query import answer_query as query_v1
from .query_v2 import answer_query as query_v2
from .schema import Table


def _lookup(tables: List[Table], row_label: str, column: str):
    """Find a cell in whichever extracted table happens to hold it."""
    for table in tables:
        value = table.find_cell(row_label, column)
        if value is not None:
            return value
    return None


def score_extraction(extractor) -> Dict:
    per_document: Dict[str, Dict] = {}
    found = 0

    for name, text in DOCUMENTS.items():
        tables = extractor.extract(text, source=name)
        expectations = [e for e in CELL_EXPECTATIONS if e.document == name]
        hits = [
            e for e in expectations
            if _lookup(tables, e.row_label, e.column) == e.value
        ]
        found += len(hits)
        per_document[name] = {
            "cells_found": len(hits),
            "cells_expected": len(expectations),
            "tables": len(tables),
            # A confidence of 1.0 on a document that lost rows is the specific
            # thing worth surfacing, so it is reported alongside recall.
            "min_confidence": round(min((t.confidence for t in tables), default=0.0), 4),
            "missing": [
                f"{e.row_label}/{e.column}" for e in expectations if e not in hits
            ],
        }

    return {
        "cells_found": found,
        "cells_expected": len(CELL_EXPECTATIONS),
        "recall": round(found / len(CELL_EXPECTATIONS), 4),
        "documents": per_document,
    }


def score_queries(extractor, answerer) -> Dict:
    correct = 0
    fabricated: List[str] = []
    missed: List[str] = []

    for case in QUERY_CASES:
        tables = extractor.extract(DOCUMENTS[case.document], source=case.document)
        answer = answerer(case.question, tables)

        if case.answerable:
            if answer.found and answer.value == case.expected:
                correct += 1
            else:
                missed.append(f"{case.question} -> {answer.value!r}")
        else:
            if answer.found:
                fabricated.append(
                    f"{case.question} -> {answer.value!r} "
                    f"cited to {answer.row_label}/{answer.column}"
                )
            else:
                correct += 1

    answerable = [c for c in QUERY_CASES if c.answerable]
    return {
        "correct": correct,
        "total": len(QUERY_CASES),
        "accuracy": round(correct / len(QUERY_CASES), 4),
        "answerable": len(answerable),
        "unanswerable": len(QUERY_CASES) - len(answerable),
        "fabricated_citations": len(fabricated),
        "fabricated": fabricated,
        "missed": missed,
    }


def build_report() -> Dict:
    return {
        "extraction": {
            "naive": score_extraction(NaiveExtractor()),
            "v1 block": score_extraction(TextTableExtractor()),
            "v2 robust": score_extraction(RobustTableExtractor()),
        },
        "query": {
            "v1 block + v1 query": score_queries(TextTableExtractor(), query_v1),
            "v2 robust + v2 query": score_queries(RobustTableExtractor(), query_v2),
        },
    }


def format_report(report: Dict) -> str:
    lines = [
        "Extraction: does the data survive?",
        "=" * 74,
        f"{'extractor':<14}{'document':<18}{'cells':>10}{'tables':>8}{'min conf':>10}",
        "-" * 74,
    ]
    for name, result in report["extraction"].items():
        for document, row in result["documents"].items():
            label = name if document == "clean" else ""
            lines.append(
                f"{label:<14}{document:<18}"
                f"{row['cells_found']:>5}/{row['cells_expected']:<4}"
                f"{row['tables']:>8}{row['min_confidence']:>10.2f}"
            )
        lines.append(f"{'':<14}{'RECALL':<18}{result['recall']:>10.0%}")
        lines.append("")

    lines += [
        "Querying: does it answer, and does it know when it cannot?",
        "=" * 74,
        f"{'pipeline':<26}{'accuracy':>10}{'fabricated citations':>24}",
        "-" * 74,
    ]
    for name, result in report["query"].items():
        lines.append(
            f"{name:<26}{result['accuracy']:>10.0%}"
            f"{result['fabricated_citations']:>16} of {result['unanswerable']}"
        )

    lines += [
        "",
        "A fabricated citation is an answer to a question about a row that does not",
        "exist, returned with a row and column reference. It is worse than a miss:",
        "the citation is what makes it look checked.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=None)
    parser.add_argument("--show-failures", action="store_true")
    args = parser.parse_args()

    report = build_report()
    print(format_report(report))

    if args.show_failures:
        for name, result in report["query"].items():
            if result["fabricated"]:
                print(f"\n{name} fabricated:")
                for item in result["fabricated"]:
                    print(f"  {item}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
