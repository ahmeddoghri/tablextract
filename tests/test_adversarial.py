"""Tests for documents that break extractors, and questions with no answer."""

from __future__ import annotations

import pytest

from app.docbench import (
    CELL_EXPECTATIONS,
    DOCUMENTS,
    JUSTIFIED_PROSE,
    PAGE_BREAK,
    PAGE_FURNITURE,
    QUERY_CASES,
    WRAPPED_CELLS,
)
from app.docbench_run import build_report, score_extraction, score_queries
from app.extractor import TextTableExtractor
from app.extractor_v2 import (
    LineRole,
    RobustTableExtractor,
    classify_line,
)
from app.query import answer_query as query_v1
from app.query_v2 import answer_query as query_v2, tokenize, tokenize_label


def cell(tables, row_label, column):
    for table in tables:
        value = table.find_cell(row_label, column)
        if value is not None:
            return value
    return None


@pytest.fixture
def v2():
    return RobustTableExtractor()


# --- the extraction failures ------------------------------------------------

def test_v1_drops_rows_after_a_page_banner():
    """The silent failure: rows vanish and confidence stays at 1.0."""
    tables = TextTableExtractor().extract(PAGE_FURNITURE)
    assert cell(tables, "Cohort B", "Grade2") is None
    assert max(t.confidence for t in tables) == 1.0


def test_v2_keeps_rows_after_a_page_banner(v2):
    tables = v2.extract(PAGE_FURNITURE)
    assert cell(tables, "Cohort B", "Grade2") == "3"
    assert cell(tables, "Cohort C", "Grade3") == "2"


def test_v1_truncates_at_a_wrapped_cell():
    tables = TextTableExtractor().extract(WRAPPED_CELLS)
    assert cell(tables, "Cohort B", "Dose_mg") is None


def test_v2_survives_a_wrapped_cell(v2):
    tables = v2.extract(WRAPPED_CELLS)
    assert cell(tables, "Cohort B", "Dose_mg") == "100"
    assert cell(tables, "Cohort C", "Dose_mg") == "150"


def test_wrapped_text_joins_the_right_column(v2):
    """Appending to the last non-empty cell corrupts the dose column."""
    tables = v2.extract(WRAPPED_CELLS)
    assert cell(tables, "Cohort A", "Dose_mg") == "50"
    description = cell(tables, "Cohort A", "Description")
    assert "regimen per amendment v2" in description


def test_v1_fragments_a_table_across_a_page_break():
    assert len(TextTableExtractor().extract(PAGE_BREAK)) == 2


def test_v2_merges_a_table_across_a_page_break(v2):
    tables = v2.extract(PAGE_BREAK)
    assert len(tables) == 1
    assert len(tables[0].rows) == 4
    assert cell(tables, "Cohort D", "Grade3") == "0"


def test_justified_prose_does_not_become_a_table(v2):
    """PDF justification pads prose, so every word looks like a cell."""
    tables = v2.extract(JUSTIFIED_PROSE)
    assert len(tables) == 1
    assert tables[0].headers[0] == "Cohort"


def test_v2_recovers_every_expected_cell(v2):
    result = score_extraction(v2)
    assert result["recall"] == 1.0, result["documents"]


def test_v2_beats_v1_on_recall():
    assert (
        score_extraction(RobustTableExtractor())["recall"]
        > score_extraction(TextTableExtractor())["recall"]
    )


def test_clean_documents_do_not_regress(v2):
    for expectation in [e for e in CELL_EXPECTATIONS if e.document == "clean"]:
        tables = v2.extract(DOCUMENTS["clean"], source="clean")
        assert cell(tables, expectation.row_label, expectation.column) == expectation.value


# --- line classification ----------------------------------------------------

def test_page_banner_is_furniture():
    assert classify_line("CONFIDENTIAL - Page 3 of 12", 4, 0).role is LineRole.FURNITURE
    assert classify_line("Page 2 of 7", 4, 0).role is LineRole.FURNITURE


def test_indented_fragment_is_a_continuation():
    assert classify_line("            regimen per v2", 3, 0).role is LineRole.CONTINUATION


def test_data_row_is_data():
    assert classify_line("Cohort A    12      4", None, 0).role is LineRole.DATA


def test_justified_sentence_is_prose():
    line = "The  following  table  summarizes  treatment-emergent  adverse  events"
    assert classify_line(line, None, 0).role is LineRole.PROSE


def test_a_data_row_is_not_mistaken_for_furniture():
    """A row whose label contains a furniture word is still data."""
    line = "Revision 3    12      4      1"
    assert classify_line(line, 4, 0).role is LineRole.DATA


def test_trace_reports_what_was_skipped(v2):
    _, trace = v2.extract_with_trace(PAGE_FURNITURE)
    assert trace.furniture_skipped >= 1


def test_trace_reports_joined_continuations(v2):
    _, trace = v2.extract_with_trace(WRAPPED_CELLS)
    assert trace.continuations_joined == 2


def test_trace_reports_merged_fragments(v2):
    _, trace = v2.extract_with_trace(PAGE_BREAK)
    assert trace.fragments_merged == 1


# --- the fabricated citation ------------------------------------------------

def test_v1_answers_a_question_about_a_nonexistent_row():
    """The headline failure: a citation to a row nobody asked about."""
    tables = TextTableExtractor().extract(DOCUMENTS["clean"], source="clean")
    answer = query_v1("What is Grade1 for the moon?", tables)
    assert answer.found
    assert answer.value == "12"
    assert answer.row_label == "Cohort A"


def test_v2_declines_a_question_about_a_nonexistent_row(v2):
    tables = v2.extract(DOCUMENTS["clean"], source="clean")
    answer = query_v2("What is Grade1 for the moon?", tables)
    assert not answer.found
    assert answer.value is None
    assert "row" in answer.reason


@pytest.mark.parametrize("question", [
    "What is Grade1 for Cohort Z?",
    "What is the Dose_mg for Cohort Q?",
    "What is Grade1 for the placebo arm?",
    "How many patients enrolled in Antarctica?",
])
def test_v2_declines_every_unanswerable_question(v2, question):
    tables = v2.extract(DOCUMENTS["clean"], source="clean")
    assert not query_v2(question, tables).found


def test_v2_declines_an_unknown_column(v2):
    tables = v2.extract(DOCUMENTS["clean"], source="clean")
    answer = query_v2("What is the mortality rate for Cohort A?", tables)
    assert not answer.found
    assert "column" in answer.reason


def test_refusals_list_what_the_document_does_contain(v2):
    """A refusal without a hint is a dead end for the caller."""
    tables = v2.extract(DOCUMENTS["clean"], source="clean")
    answer = query_v2("What is the mortality rate for Cohort A?", tables)
    assert "Grade1" in answer.near_misses


def test_v2_still_answers_answerable_questions(v2):
    tables = v2.extract(DOCUMENTS["clean"], source="clean")
    answer = query_v2("What is Grade2 for Cohort B?", tables)
    assert answer.found
    assert answer.value == "3"
    assert answer.row_label == "Cohort B"
    assert answer.column == "Grade2"


def test_v2_answers_a_row_hidden_behind_a_page_banner(v2):
    tables = v2.extract(PAGE_FURNITURE, source="pf")
    answer = query_v2("What is Grade2 for Cohort B?", tables)
    assert answer.found and answer.value == "3"


def test_v2_answers_a_row_on_a_continuation_page(v2):
    tables = v2.extract(PAGE_BREAK, source="pb")
    answer = query_v2("What is Grade1 for Cohort C?", tables)
    assert answer.found and answer.value == "15"


def test_no_tables_is_a_reason_not_a_crash():
    answer = query_v2("What is Grade1 for Cohort A?", [])
    assert not answer.found
    assert "no tables" in answer.reason


# --- the tokenizer bug that caused both symptoms ----------------------------

def test_labels_keep_their_distinguishing_token():
    """'Cohort A' stripped to {'cohort'} matches a question about Cohort B."""
    assert "a" in tokenize_label("Cohort A")
    assert "a" not in tokenize("What is a value?")


def test_row_labels_are_distinguishable():
    tokens = tokenize("What is Grade1 for Cohort B?") | {"b"}
    from app.query_v2 import _coverage

    assert _coverage("Cohort B", tokens) > _coverage("Cohort A", tokens)


def test_query_scores_are_reported(v2):
    tables = v2.extract(DOCUMENTS["clean"], source="clean")
    answer = query_v2("What is Grade2 for Cohort B?", tables)
    assert answer.row_score > 0 and answer.column_score > 0


# --- the benchmark ----------------------------------------------------------

def test_benchmark_shows_no_fabricated_citations():
    result = score_queries(RobustTableExtractor(), query_v2)
    assert result["fabricated_citations"] == 0, result["fabricated"]


def test_benchmark_shows_v1_fabricating():
    result = score_queries(TextTableExtractor(), query_v1)
    assert result["fabricated_citations"] > 0


def test_benchmark_is_reproducible():
    assert build_report() == build_report()


def test_corpus_includes_unanswerable_questions():
    assert [c for c in QUERY_CASES if not c.answerable]


def test_every_document_has_expectations():
    for name in DOCUMENTS:
        assert [e for e in CELL_EXPECTATIONS if e.document == name]


# --- API --------------------------------------------------------------------

def test_api_declines_and_says_why():
    from fastapi.testclient import TestClient

    from app.main import app

    payload = TestClient(app).post(
        "/v1/query",
        json={"text": DOCUMENTS["clean"], "question": "What is Grade1 for the moon?"},
    ).json()
    assert payload["found"] is False
    assert payload["reason"]
    assert payload["near_misses"]


def test_api_recovers_rows_behind_a_page_banner():
    from fastapi.testclient import TestClient

    from app.main import app

    payload = TestClient(app).post(
        "/v1/extract", json={"text": PAGE_FURNITURE, "source": "pf"}
    ).json()
    assert len(payload["tables"]) == 1
    assert len(payload["tables"][0]["rows"]) == 3
