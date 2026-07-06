"""FastAPI table-extraction service. Run locally with
`uvicorn app.main:app --reload`.
"""
from __future__ import annotations

import base64
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .extractor import TextTableExtractor
from .query import answer_query
from .schema import Table

app = FastAPI(title="tablextract", version="0.1.0")
_extractor = TextTableExtractor()


class ExtractRequest(BaseModel):
    text: str
    source: str = ""


class TableOut(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    source: str
    confidence: float


class ExtractResponse(BaseModel):
    tables: list[TableOut]


class QueryRequest(BaseModel):
    text: str
    question: str
    source: str = ""


class QueryResponse(BaseModel):
    value: Optional[str]
    table_source: Optional[str]
    row_label: Optional[str]
    column: Optional[str]
    found: bool


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest) -> ExtractResponse:
    tables = _extractor.extract(req.text, source=req.source)
    return ExtractResponse(tables=[TableOut(**t.to_dict()) for t in tables])


@app.post("/v1/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    tables = _extractor.extract(req.text, source=req.source)
    result = answer_query(req.question, tables)
    return QueryResponse(value=result.value, table_source=result.table_source,
                         row_label=result.row_label, column=result.column, found=result.found)


@app.post("/v1/extract/pdf", response_model=ExtractResponse)
def extract_pdf(pdf_base64: str, source: str = "") -> ExtractResponse:
    """Real-PDF path: pass base64-encoded PDF bytes. Requires the optional
    `pdfplumber` dependency (pip install tablextract[pdf])."""
    from .extractor import PdfplumberExtractor  # the class itself has no hard dependency

    pdf_bytes = base64.b64decode(pdf_base64)
    try:
        tables = PdfplumberExtractor().extract(pdf_bytes, source=source)
    except ModuleNotFoundError as e:
        # pdfplumber's import is lazy, inside .extract() -- that's where the
        # missing-dependency error actually surfaces, not at class import time
        raise HTTPException(status_code=501,
                           detail="pdfplumber not installed; pip install tablextract[pdf]") from e
    return ExtractResponse(tables=[TableOut(**t.to_dict()) for t in tables])
