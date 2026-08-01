"""FastAPI table-extraction service. Run locally with
`uvicorn app.main:app --reload`.
"""
from __future__ import annotations

import base64
import binascii
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import security
from .config import settings
from .extractor import TextTableExtractor
from .extractor_v2 import RobustTableExtractor
from .query import answer_query as answer_query_v1
from .query_v2 import answer_query as answer_query_v2
from .security import require_api_key

app = FastAPI(title="tablextract", version="0.1.0")
security.install(app)
_extractor = (
    TextTableExtractor() if settings.pipeline == "v1" else RobustTableExtractor()
)
answer_query = answer_query_v1 if settings.pipeline == "v1" else answer_query_v2


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1, max_length=settings.max_text_chars)
    source: str = ""


class TableOut(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    source: str
    confidence: float


class ExtractResponse(BaseModel):
    tables: list[TableOut]


class QueryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=settings.max_text_chars)
    question: str = Field(min_length=1, max_length=settings.max_question_chars)
    source: str = ""


class PdfExtractRequest(BaseModel):
    pdf_base64: str = Field(min_length=1, max_length=settings.max_pdf_b64_chars)
    source: str = ""


class QueryResponse(BaseModel):
    value: Optional[str]
    table_source: Optional[str]
    row_label: Optional[str]
    column: Optional[str]
    found: bool
    # When nothing is returned, why. A refusal without a reason is
    # indistinguishable from a failure, and the caller cannot act on it.
    reason: str = ""
    row_score: float = 0.0
    column_score: float = 0.0
    # What was rejected, so the caller can see what the document does contain.
    near_misses: list[str] = []


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict:
    """Readiness probe: the extractor is wired and the service can serve."""
    return {"status": "ready"}


@app.post("/v1/extract", response_model=ExtractResponse,
          dependencies=[Depends(require_api_key)])
def extract(req: ExtractRequest) -> ExtractResponse:
    tables = _extractor.extract(req.text, source=req.source)
    return ExtractResponse(tables=[TableOut(**t.to_dict()) for t in tables])


@app.post("/v1/query", response_model=QueryResponse,
          dependencies=[Depends(require_api_key)])
def query(req: QueryRequest) -> QueryResponse:
    tables = _extractor.extract(req.text, source=req.source)
    result = answer_query(req.question, tables)
    extra = {
        "reason": getattr(result, "reason", ""),
        "row_score": getattr(result, "row_score", 0.0),
        "column_score": getattr(result, "column_score", 0.0),
        "near_misses": getattr(result, "near_misses", []),
    }
    return QueryResponse(value=result.value, table_source=result.table_source,
                         row_label=result.row_label, column=result.column,
                         found=result.found, **extra)


@app.post("/v1/extract/pdf", response_model=ExtractResponse,
          dependencies=[Depends(require_api_key)])
def extract_pdf(req: PdfExtractRequest) -> ExtractResponse:
    """Real-PDF path: POST base64-encoded PDF bytes in the request body.
    Requires the optional `pdfplumber` dependency (pip install tablextract[pdf])."""
    from .extractor import (
        PdfplumberExtractor,  # the class itself has no hard dependency
    )

    try:
        pdf_bytes = base64.b64decode(req.pdf_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=400, detail="pdf_base64 is not valid base64") from e

    try:
        tables = PdfplumberExtractor().extract(pdf_bytes, source=req.source)
    except ModuleNotFoundError as e:
        # pdfplumber's import is lazy, inside .extract() -- that's where the
        # missing-dependency error actually surfaces, not at class import time
        raise HTTPException(status_code=501,
                           detail="pdfplumber not installed; pip install tablextract[pdf]") from e
    return ExtractResponse(tables=[TableOut(**t.to_dict()) for t in tables])
