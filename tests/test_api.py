from fastapi.testclient import TestClient

from app.main import app
from app.eval import DOCUMENT

client = TestClient(app)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_extract_endpoint_returns_tables():
    resp = client.post("/v1/extract", json={"text": DOCUMENT, "source": "test-doc"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tables"]) == 2
    assert body["tables"][0]["source"] == "test-doc"


def test_query_endpoint_answers_from_document():
    resp = client.post("/v1/query", json={
        "text": DOCUMENT,
        "question": "What is the Grade3 count for Cohort C?",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["value"] == "2"


def test_pdf_endpoint_returns_501_without_pdfplumber_installed():
    # in the default (non-[pdf]) install, pdfplumber isn't present, so the
    # endpoint should degrade gracefully instead of 500ing
    resp = client.post("/v1/extract/pdf", params={"pdf_base64": "aGVsbG8=", "source": "x"})
    assert resp.status_code in (200, 501)  # 200 if pdfplumber happens to be installed in this env
