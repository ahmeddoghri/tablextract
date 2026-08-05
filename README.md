# tablextract

![tests](https://img.shields.io/badge/tests-58%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-black)

> **Pull data out of messy prose-plus-table documents and answer
> questions with a citation to the exact row and column.** Zero API keys
> to try it: `python -m app.eval`.
>
> Asked "What is Grade1 for the moon?", the first version answered **12**,
> cited to Cohort A. It could not say "I don't know", and a fabricated
> citation is worse than no answer because it looks verified.
> `python -m app.docbench_run` is the benchmark that found that, and the
> page banners and wrapped cells that were silently deleting rows at
> confidence 1.00.

PDFs are where structured data goes to die. Somewhere between the
spreadsheet someone built it in and the document someone pasted it into,
every table gets buried inside three paragraphs of narrative text with
zero markup telling you where the prose stops and the numbers start.
tablextract finds the table blocks, skips the prose, and answers
questions against the extracted data with a citation back to the exact
row and column it came from.

I spent real time on this exact problem building a table-extraction
pipeline for FDA regulatory submissions. The failure mode that actually
costs you is never "can't read a PDF." It's a naive parser choking on the
paragraph between two tables and misaligning every row downstream of it,
silently, so nobody notices until an audit. This is that lesson, rebuilt
as an open, runnable service instead of proprietary pipeline code.

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
sentences as "rows" too, and once the header assumption is wrong, every
downstream cell lookup is wrong right along with it. `tablextract` finds
contiguous, column-consistent blocks and treats everything else as prose
to skip.

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

Zero isn't a typo. The naive extractor merges the prose paragraph into
the table it's parsing, which shifts its header assumption and corrupts
every single ground-truth cell lookup after that point. This is the
actual, common failure mode in real documents, not a cherry-picked edge
case built to make the demo look good.

## Then I pointed it at documents that fight back

That 100% is on a document where the tables are separated by blank lines and
the prose never contains aligned whitespace. Real PDF text layers are not like
that, and what goes wrong is not "cannot read the file". It is worse:

```bash
python -m app.docbench_run
```

| extractor | document | cells | tables | min confidence |
| --- | --- | ---: | ---: | ---: |
| v1 block | clean | 3/3 | 2 | 1.00 |
| v1 block | page_furniture | **1/3** | 2 | **1.00** |
| v1 block | wrapped_cells | **1/3** | 2 | **1.00** |
| v1 block | page_break | 3/3 | 2 | 1.00 |
| v2 robust | *(all five)* | **14/14** | | |

Recall goes from **71% to 100%**, and look at the confidence column. The old
extractor lost two thirds of the rows in two documents and reported **1.00**
while doing it. That is precisely the audit failure this project's own README
warns about, sitting inside its own extractor.

Three things cause it, all of which a PDF does constantly:

- **`CONFIDENTIAL - Page 3 of 12` printed between two data rows.** A block extractor treats it as the end of the table and silently discards every row after it.
- **A cell too long for its column,** continuing on the next indented line. That continuation is not a row, and treating it as one truncates the table there.
- **A table continuing onto the next page** with its header repeated, becoming two tables, so a lookup for a row on page two fails against table one.

v2 gives every line a role (data, furniture, continuation, prose) rather than
assuming anything non-tabular ends the table, joins wrapped fragments back
into the column they overflowed from, merges page-break fragments that repeat
a header, and reports confidence that actually reflects how much of the block
parsed cleanly.

## The failure that matters more than any of them

A tool whose entire selling point is a citation to the exact row and column
must be able to say it does not know. This one could not:

```
Q: "What is Grade1 for the moon?"
A: 12   [cited to: Cohort A / Grade1]
```

Four of seven unanswerable questions got a confident, cited, wrong answer. A
wrong answer with no citation gets checked by whoever reads it. A wrong answer
*with a row and column reference* looks verified, and gets signed off.

The cause was arithmetic. The old scorer **added** a column-match score to a
row-match score and returned the best total, so a question naming any real
column cleared the bar on its own; the row match could be zero. v2 makes it a
conjunction: the question has to identify the row *and* the column, each above
its own threshold, and ties are a refusal too, because matching two rows
equally well means the question identified neither.

Refusals carry the reason and what the document does contain:

```json
{"found": false,
 "reason": "no column in the document matches the question",
 "near_misses": ["Dose_mg", "Frequency", "Grade1", "Grade2", "Grade3"]}
```

| pipeline | query accuracy | fabricated citations |
| --- | ---: | ---: |
| v1 block + v1 query | 57% | **4 of 7** |
| v2 robust + v2 query | **100%** | **0 of 7** |

### One bug caused two opposite symptoms

While building the abstention logic, v2 started *rejecting real answers*. The
cause turned out to be one line: the tokenizer stripped English stopwords from
row labels as well as from questions, and `"Cohort A"` contains the article
`"a"`. Stripped, the label became `{"cohort"}`, which matches a question about
Cohort B **or** Cohort Z at full coverage. That single mistake both created
ties that suppressed valid answers and let nonexistent rows score perfectly.

Labels have no stopwords. The distinguishing token of a row label is very
often a single letter or digit, and everything in a label is data.

### Held out, run once

Both v2 components were built against the corpus above, so those numbers are
in-sample. A separate document and question set was written afterwards with
the code frozen and evaluated a single time:

| | v1 | v2 |
| --- | ---: | ---: |
| cells recovered | 2/4 | **4/4** |
| questions correct | 3/7 | **7/7** |
| fabricated citations | 3 | **0** |

### Limits

- **Whitespace-aligned text only.** Tables drawn with ruling lines and no consistent spacing need the pdfplumber path, which uses the PDF's own geometry.
- **Matching is lexical.** It knows `Grade1` is absent; it does not know your `severity_grade_1` means the same thing.
- **The first column is assumed to be the row label**, which is the common regulatory-table shape and not a universal one.
- **A refusal is not proof the data is absent**, only that the question did not identify a row and column well enough to cite one.

`PIPELINE=v1` still selects the old path, so the comparison is reproducible
rather than a claim you have to take on faith.

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

The default path works on already-extracted text, which is exactly what
`pdfplumber` gives you from a real PDF's text layer, or what an OCR
engine outputs. For end-to-end PDF binaries:

```bash
pip install -r requirements-pdf.txt   # adds pdfplumber
```
```bash
curl -X POST localhost:8000/v1/extract/pdf \
  -H "Content-Type: application/json" \
  -d "{\"pdf_base64\": \"$(base64 -i document.pdf)\", \"source\": \"my-doc\"}"
```
The base64 payload goes in the JSON body, not the query string, which
has length limits and will silently truncate a real PDF. Returns `400`
for malformed base64 and `501` with a clear message if `pdfplumber`
isn't installed. Never a bare 500 that leaves you guessing.

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

The service exposes `GET /healthz` (liveness) and `GET /readyz`
(readiness). Every response carries an `X-Request-ID` header, requests
are logged with method, path, status, and latency, and unhandled errors
return a structured `500` without leaking stack traces.

## Tests

```bash
pip install -r requirements-dev.txt && pytest -q      # 17 passing
```

## More in this series

Nine small, dependency-light, benchmarked tools for LLM/ML infrastructure. Each one reproduces its headline number locally with no API keys:

[agentmem](https://github.com/ahmeddoghri/agentmem) · [rubricagent](https://github.com/ahmeddoghri/rubricagent) · [clarifyrag](https://github.com/ahmeddoghri/clarifyrag) · [churnfm](https://github.com/ahmeddoghri/churnfm) · [citebench](https://github.com/ahmeddoghri/citebench) · [guardrail-gate](https://github.com/ahmeddoghri/guardrail-gate) · [vllm-cost-router](https://github.com/ahmeddoghri/vllm-cost-router) · [taggate](https://github.com/ahmeddoghri/taggate)

## License

MIT © Ahmed Doghri
