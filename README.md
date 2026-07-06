# tablextract

![CI](https://github.com/ahmeddoghri/tablextract/actions/workflows/ci.yml/badge.svg)
![tests](https://img.shields.io/badge/tests-17%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-black)

> **Pull data out of messy prose-plus-table documents and answer questions
> with a citation to the exact row and column.** Zero API keys to try it:
> `python -m app.eval`.

A structured-table extraction service for documents that mix narrative text
and data tables with no explicit markup between them — which is every
regulatory document I've ever had to parse. Finds the table blocks, skips the
prose, and answers questions against the extracted data with a citation back
to the exact row and column it came from.

I spent real time on this exact problem building a table-extraction pipeline
for FDA regulatory submissions — the failure mode that actually costs you is
never "can't read a PDF," it's a naive parser choking on the paragraph
between two tables and misaligning every row downstream of it. This is that
lesson, rebuilt as an open, runnable service instead of proprietary
pipeline code.

## The problem, concretely

```
Section 4: Adverse Event Summary

The following table summarizes treatment-emergent adverse events...
[ 3 sentences of prose ]

Cohort      Grade1  Grade2  Grade3
Cohort A    12      4       1
Cohort B    9       3       0
```

A naive extractor that treats every line the same way sees the prose
sentences as "rows" too — and once the header is wrong, every downstream cell
lookup is wrong with it. `tablextract` finds contiguous, column-consistent
blocks and treats everything else as prose to skip.

## The result, on a labeled synthetic document

```bash
python -m app.eval
```
```
document: mixed prose + 2 data tables (adverse events, dosing schedule)

extractor     tables found   cells correct    accuracy
naive                    1            0/8           0%
tablextract              2            8/8         100%
```

Zero isn't a typo: the naive extractor merges the prose paragraph into the
table it's parsing, which shifts its header assumption and corrupts every
single ground-truth cell lookup after that point. This is the actual, common
failure mode in real documents, not a cherry-picked edge case.

## Install & run

```bash
git clone https://github.com/ahmeddoghri/tablextract
cd tablextract
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Or with Docker:

```bash
docker build -t tablextract .
docker run -p 8000:8000 tablextract
```

## Extract tables from text

```bash
curl -X POST localhost:8000/v1/extract \
  -H "Content-Type: application/json" \
  -d '{"text": "Cohort   Grade1  Grade2\nCohort A  12  4\nCohort B  9  3"}'
```

## Ask a question, get a cited answer

```bash
curl -X POST localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"text": "...", "question": "What is the Grade2 count for Cohort B?"}'
```
```json
{"value": "3", "table_source": "", "row_label": "Cohort B", "column": "Grade2", "found": true}
```

## Real PDFs

The default path works on already-extracted text (which is exactly what
`pdfplumber` gives you from a real PDF's text layer, or what an OCR engine
outputs). For end-to-end PDF binaries:

```bash
pip install -r requirements-pdf.txt   # adds pdfplumber
```
```bash
curl -X POST localhost:8000/v1/extract/pdf \
  -H "Content-Type: application/json" \
  -d "{\"pdf_base64\": \"$(base64 -i document.pdf)\", \"source\": \"my-doc\"}"
```
The base64 payload goes in the JSON body (not the query string, which has
length limits). Returns `400` for malformed base64, and `501` with a clear
message if `pdfplumber` isn't installed — never a bare 500.

## How it decides what's a table

```
for each line:
  split on "|" or runs of 2+ spaces
  >= min_columns cells?  -> part of the current table block
  otherwise              -> ends the block (prose, blank line, etc.)

for each block:
  keep only rows matching the block's dominant column count
  confidence = (consistent rows) / (total rows in block)
  first consistent row -> headers, the rest -> data rows
```

## Production configuration

All settings have safe defaults; override via environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `API_KEY` | *(empty)* | When set, write endpoints require a matching `X-API-Key` header. Empty leaves the service open. |
| `MAX_TEXT_CHARS` | `1000000` | Rejects (422) documents larger than this. |
| `MAX_PDF_BYTES` | `20MiB` | Caps decoded PDF size on `/v1/extract/pdf`. |

The service exposes `GET /healthz` (liveness) and `GET /readyz` (readiness).
Every response carries an `X-Request-ID` header and requests are logged with
method, path, status, and latency. Unhandled errors return a structured `500`
without leaking stack traces.

## Tests

```bash
pip install -r requirements-dev.txt && pytest -q      # 17 passing
```

## License

MIT © Ahmed Doghri
