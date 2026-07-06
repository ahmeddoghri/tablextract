from app.eval import DOCUMENT, GROUND_TRUTH, run
from app.extractor import NaiveExtractor, TextTableExtractor
from app.query import answer_query


def test_smart_extractor_finds_both_tables():
    tables = TextTableExtractor().extract(DOCUMENT)
    assert len(tables) == 2


def test_smart_extractor_skips_prose():
    tables = TextTableExtractor().extract(DOCUMENT)
    for table in tables:
        for row in table.rows:
            assert "Cohort" in row[0] or row[0]  # every row is an actual data row


def test_smart_extractor_gets_every_ground_truth_cell_right():
    tables = TextTableExtractor().extract(DOCUMENT)
    for table_idx, row_label, column, expected in GROUND_TRUTH:
        actual = tables[table_idx].find_cell(row_label, column)
        assert actual == expected, f"{row_label}/{column}: expected {expected}, got {actual}"


def test_naive_extractor_is_meaningfully_worse():
    result = run()
    assert result["smart_accuracy"] > result["naive_accuracy"]
    assert result["smart_accuracy"] == 1.0


def test_query_answers_from_extracted_table():
    tables = TextTableExtractor().extract(DOCUMENT)
    answer = answer_query("What is the Grade3 count for Cohort C?", tables)
    assert answer.found
    assert answer.value == "2"


def test_query_reports_no_answer_for_unrelated_question():
    tables = TextTableExtractor().extract(DOCUMENT)
    answer = answer_query("What is the capital of France?", tables)
    assert not answer.found


def test_extractor_handles_empty_input():
    assert TextTableExtractor().extract("") == []
    assert NaiveExtractor().extract("") == []


def test_extractor_ignores_short_blocks_below_min_rows():
    text = "Header1  Header2\nonly_one_row  value"
    tables = TextTableExtractor(min_rows=3).extract(text)
    assert tables == []
