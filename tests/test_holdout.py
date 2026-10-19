import json
from pathlib import Path

from app.holdout import build_report


def test_committed_holdout_result_matches_the_code():
    committed = json.loads((Path(__file__).parent.parent / "holdout_benchmark.json").read_text())
    assert build_report() == committed


def test_v2_never_fabricates_a_citation_on_the_holdout():
    assert build_report()["v2"]["questions"]["fabricated_citations"] == 0
