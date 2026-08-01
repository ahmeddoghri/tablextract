"""Documents built to break a table extractor the way real PDFs do.

The bundled evaluation document has two tables separated by blank lines, with
prose that never contains aligned whitespace. Real PDF text layers are not
like that, and the failures they cause are silent: rows vanish, and the
extractor still reports confidence 1.0.

Four things go wrong in practice, all represented here:

``page_furniture``
    "CONFIDENTIAL - Page 3" printed between two data rows. A block-based
    extractor treats it as the end of the table and drops everything after it.

``wrapped_cells``
    A cell too long for its column continues on the next line, indented. That
    continuation is not a row, and treating it as one truncates the table.

``page_break``
    A long table continues on the next page with its header repeated. Two
    fragments instead of one table means a lookup for a row on page two fails
    against table zero.

``justified_prose``
    PDF justification inserts multiple spaces between words, so prose lines
    split into several "columns" and can be mistaken for table rows.

The question set matters as much as the documents. Half of it is
**unanswerable on purpose**: rows and columns that do not exist anywhere. A
tool whose entire selling point is a citation to the exact row and column has
to be able to say it does not know, because a fabricated citation is worse
than no answer. It looks verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

# --- documents --------------------------------------------------------------

CLEAN = """\
Section 4: Adverse Event Summary

The following table summarizes treatment-emergent adverse events observed
across all study cohorts during the current reporting period.

Cohort      Grade1  Grade2  Grade3
Cohort A    12      4       1
Cohort B    9       3       0
Cohort C    15      6       2

Section 5: Dosing Schedule

Cohort      Dose_mg  Frequency
Cohort A    50       Daily
Cohort B    100      Daily
Cohort C    150      Weekly
"""

PAGE_FURNITURE = """\
Section 4: Adverse Event Summary

Cohort      Grade1  Grade2  Grade3
Cohort A    12      4       1
CONFIDENTIAL - Page 3 of 12
Cohort B    9       3       0
Cohort C    15      6       2

Study Protocol XYZ-2024               Revision 3
"""

WRAPPED_CELLS = """\
Cohort      Description              Dose_mg
Cohort A    Standard dosing          50
            regimen per amendment v2
Cohort B    Weekly titration         100
Cohort C    Loading dose followed    150
            by maintenance
"""

PAGE_BREAK = """\
Cohort      Grade1  Grade2  Grade3
Cohort A    12      4       1
Cohort B    9       3       0

Page 2 of 7

Cohort      Grade1  Grade2  Grade3
Cohort C    15      6       2
Cohort D    7       2       0
"""

JUSTIFIED_PROSE = """\
The  following  table  summarizes  treatment-emergent  adverse  events
observed  across  all  study  cohorts  during  the  reporting  period.
Grade  3  events  were  reviewed  by  the  DSMB  and  none  were  found
to  be  related  to  study  drug  administration.

Cohort      Grade1  Grade2  Grade3
Cohort A    12      4       1
Cohort B    9       3       0
"""

DOCUMENTS: Dict[str, str] = {
    "clean": CLEAN,
    "page_furniture": PAGE_FURNITURE,
    "wrapped_cells": WRAPPED_CELLS,
    "page_break": PAGE_BREAK,
    "justified_prose": JUSTIFIED_PROSE,
}


# --- expected cell contents -------------------------------------------------

@dataclass(frozen=True)
class CellExpectation:
    """One cell that must survive extraction, wherever it ends up."""

    document: str
    row_label: str
    column: str
    value: str
    note: str = ""


CELL_EXPECTATIONS: List[CellExpectation] = [
    # clean: the baseline everything already handles
    CellExpectation("clean", "Cohort A", "Grade1", "12"),
    CellExpectation("clean", "Cohort C", "Grade3", "2"),
    CellExpectation("clean", "Cohort C", "Frequency", "Weekly"),

    # page furniture: rows after the banner are the ones that disappear
    CellExpectation("page_furniture", "Cohort A", "Grade1", "12"),
    CellExpectation("page_furniture", "Cohort B", "Grade2", "3",
                    "immediately after the page banner"),
    CellExpectation("page_furniture", "Cohort C", "Grade3", "2",
                    "two rows after the banner"),

    # wrapped cells: the row after each continuation line
    CellExpectation("wrapped_cells", "Cohort A", "Dose_mg", "50"),
    CellExpectation("wrapped_cells", "Cohort B", "Dose_mg", "100",
                    "follows a wrapped continuation line"),
    CellExpectation("wrapped_cells", "Cohort C", "Dose_mg", "150"),

    # page break: rows from the continuation page
    CellExpectation("page_break", "Cohort A", "Grade1", "12"),
    CellExpectation("page_break", "Cohort C", "Grade1", "15",
                    "first row on the continuation page"),
    CellExpectation("page_break", "Cohort D", "Grade3", "0",
                    "last row on the continuation page"),

    # justified prose: nothing from the paragraph may become a row
    CellExpectation("justified_prose", "Cohort A", "Grade1", "12"),
    CellExpectation("justified_prose", "Cohort B", "Grade3", "0"),
]


# --- questions, including ones with no answer -------------------------------

@dataclass(frozen=True)
class QueryCase:
    document: str
    question: str
    #: ``None`` means the honest answer is "I cannot find that".
    expected: Optional[str]
    kind: Literal["answerable", "missing_row", "missing_column", "nonsense"]
    note: str = ""

    @property
    def answerable(self) -> bool:
        return self.expected is not None


QUERY_CASES: List[QueryCase] = [
    # --- answerable --------------------------------------------------------
    QueryCase("clean", "What is Grade1 for Cohort A?", "12", "answerable"),
    QueryCase("clean", "What is the Grade3 count for Cohort C?", "2", "answerable"),
    QueryCase("clean", "What is the Dose_mg for Cohort B?", "100", "answerable"),
    QueryCase("clean", "What is the Frequency for Cohort C?", "Weekly", "answerable"),
    QueryCase("page_furniture", "What is Grade2 for Cohort B?", "3", "answerable",
              "the row the page banner hides"),
    QueryCase("page_break", "What is Grade1 for Cohort C?", "15", "answerable",
              "on the continuation page"),
    QueryCase("wrapped_cells", "What is the Dose_mg for Cohort B?", "100", "answerable"),

    # --- rows that do not exist -------------------------------------------
    QueryCase("clean", "What is Grade1 for Cohort Z?", None, "missing_row",
              "returns Cohort A's 12 with a citation"),
    QueryCase("clean", "What is the Dose_mg for Cohort Q?", None, "missing_row"),
    QueryCase("clean", "What is Grade1 for the placebo arm?", None, "missing_row",
              "no placebo arm appears anywhere in the document"),

    # --- columns that do not exist ----------------------------------------
    QueryCase("clean", "What is the mortality rate for Cohort A?", None, "missing_column"),
    QueryCase("clean", "What is the median age for Cohort B?", None, "missing_column"),

    # --- not a question about this document -------------------------------
    QueryCase("clean", "What is Grade1 for the moon?", None, "nonsense",
              "the original answered 12, cited to Cohort A"),
    QueryCase("clean", "How many patients enrolled in Antarctica?", None, "nonsense"),
]


def documents_for(kind: str) -> List[QueryCase]:
    return [case for case in QUERY_CASES if case.kind == kind]
