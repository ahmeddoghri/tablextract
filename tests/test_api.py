from fastapi.testclient import TestClient

from app.eval import DOCUMENT
from app.main import app

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
    resp = client.post("/v1/extract/pdf", json={"pdf_base64": "aGVsbG8=", "source": "x"})
    assert resp.status_code in (200, 501)  # 200 if pdfplumber happens to be installed in this env


def test_pdf_endpoint_rejects_invalid_base64():
    resp = client.post("/v1/extract/pdf", json={"pdf_base64": "not valid base64!!!"})
    assert resp.status_code == 400


def test_readyz():
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_empty_text_rejected():
    resp = client.post("/v1/extract", json={"text": ""})
    assert resp.status_code == 422


def test_request_id_header_present():
    resp = client.get("/healthz")
    assert resp.headers.get("x-request-id")


def test_api_key_enforced_when_configured(monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    import importlib

    import app.config
    import app.main
    import app.security
    importlib.reload(app.config)
    importlib.reload(app.security)
    reloaded = importlib.reload(app.main)
    guarded = TestClient(reloaded.app)
    assert guarded.post("/v1/extract", json={"text": DOCUMENT}).status_code == 401
    ok = guarded.post("/v1/extract", json={"text": DOCUMENT},
                      headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 200
    monkeypatch.delenv("API_KEY", raising=False)
    importlib.reload(app.config)
    importlib.reload(app.security)
    importlib.reload(app.main)
