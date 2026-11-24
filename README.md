# Underwriting Copilot (dev): Orchestrator Agent + Anomaly Detection Agent

Built to the ShellKode Code Development Framework: SK folder layout, Jinja2 prompts with YAML
configs, Pydantic settings, JSON logs with correlation IDs, rate and request-size limits, and the
SK pre-commit gate (ruff, ruff-format, bandit, gitleaks, mypy --strict, file checks, prompt validator).

## Modes (backend configuration only)

Set `mode` in `backend/src/config/anomaly_config.yaml` (or `ANOMALY_MODE` in `.env`). The UI reads
the mode from `GET /v1/info` and offers the matching uploads.

| Mode | Upload | Reads the documents | Compares | Model |
|---|---|---|---|---|
| `vision_llm` | PDF / images | vision LLM | the same LLM call (one per person) | Qwen3 VL 235B |
| `structured` | key-value JSON | code, `structured_mapping.yaml` | `cross_verify` | none |
| `ocr_llm` | raw OCR JSON / text | LLM | the same LLM call (one per person) | Qwen3 32B |
| `ocr_hybrid` | raw OCR JSON / text | LLM per document (grounded) | `cross_verify` | Qwen3 32B |

Every mode builds the same checks, the same report, the same truth table and the same JSON. The
full-LLM modes get the `cross_verify` reason codes and rules in their prompt.

```
UI 1. Upload the application form -> POST /v1/lead/autofill   -> lead fields for review
                                      (file + its JSON stored under the case)
   2. Review / edit                -> POST /v1/cases/{id}/lead -> saved lead = BASE TRUTH
   3. Upload every document        -> POST /v1/cases/{id}/trigger (multipart, one shot)
        -> Orchestrator Agent (Strands, LLM)               src/ai/agents/orchestrator.py
             -> tool anomaly_detection_agent               src/ai/tools/anomaly_detection_tool.py
                  read documents (per mode)                .../anomaly_detection/{structured_input, extraction, llm_verification}.py
                  compare: applicant, father, mother, others (groups.py)
                  third-party checks (mock)                .../anomaly_detection/third_party.py
                  checklist + truth table + JSON           .../anomaly_detection/{report, truth_table}.py
        <- report stored, every document's JSON stored next to its file, short summary for the CM
```

## Run

Backend (Python 3.12), from `dev/backend`:
```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env                # set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN
.venv\Scripts\python -m uvicorn src.main:app --port 8000
```

Frontend, from `dev/frontend`:
```powershell
npm install
copy .env.example .env.local          # set VITE_DEV_PROXY_TARGET to the backend address uvicorn prints
npm run dev
```

Other scripts, from `dev/backend`:
```powershell
.venv\Scripts\python -m scripts.export_openapi                   # writes contracts/openapi.json
.venv\Scripts\python -m scripts.cross_verify_cli -i checks.json  # cross_verify demo
.venv\Scripts\python scripts/convert_batch_ocr.py ...            # batch OCR export -> payload JSON
```

## Input formats

- **vision_llm**: the application form and documents as PDF, PNG, JPG or WEBP. PDF pages are
  rendered to images (`vision.pdf_input: images`), or sent as a PDF (`document`).
- **structured**: key-value JSON. The application form layout is `app_form_structured.json`
  (`Applicant`, `Co-Applicant 1`, ...); names are joined into the full name. Documents come as one
  JSON per document, or one case file laid out like `case1_structured.json` (each person section
  with its `Documents` list; each document has `File`, `Document Type` and `Fields`). In a case
  file the person comes from the section, and every document is read and stored on its own.
  All key paths: `structured_mapping.yaml`.
- **ocr_llm / ocr_hybrid**: OCR JSON as produced (`{"status": ..., "pages": [{"page_number": 1,
  "text_lines": [...], "structured_lines": [...]}]}`) or plain text. A payload JSON
  (`{"documents": [{"party_id", "doc_type", "file_name", "ocr"}]}`) and the samples also work.

The person (`applicant`, `co_applicant_1`, ...) and the document type of each file are guessed from
the file name and can be changed in the UI before the trigger.

## What is compared (the lead is the first source)

| Order | Person | Checks | Sources |
|---|---|---|---|
| 1 | Applicant | Name, date of birth | lead, every applicant document, bureau (mock) |
| | | Father name, mother name, address | lead, applicant documents that print it |
| | | PAN, Aadhaar (last 4), passport, DL, voter ID | lead, documents of that type |
| 2 | Father | Name as parent | applicant's father name (lead + applicant documents) vs father's lead name, his documents, bureau |
| | | Date of birth, own parents, IDs | father's lead, his documents (+ bureau for DOB) |
| | | Household address | father's lead + documents vs applicant's address |
| 3 | Mother | same as father | |
| 4 | Others | Name, DOB, parents, address, IDs | their own lead, documents, bureau |

Then per person (mocked APIs): bureau address (last 12 months), PAN-Aadhaar link (sanction
condition), Voter ID / DL verification (CM justification), email, face match >= 75% (critical).
The checklist lists every check as done, only one source, or no data, with its result.

## Layout

```
backend/src/
  main.py                          app factory, middleware, error mapping
  api/                             system (info, samples), leads (auto-fill, lead), cases (trigger, result)
  services/                        autofill_service, case_service, models, errors
  adapters/bedrock/client.py       Bedrock models for Strands, schema-bound calls (text + images)
  adapters/storage/case_store.py   per case: lead, results, uploads and their extracted JSON
  adapters/kyc/                    provider interface, models, mock provider
  ai/agents/orchestrator.py        Orchestrator Agent
  ai/agents/anomaly_detection/
    agent.py                       runs the configured mode
    schemas.py                     documents, case input, extraction record
    structured_input.py            structured JSON -> fields (no LLM)
    extraction.py                  hybrid: LLM reads one document, grounded in its OCR
    llm_verification.py            full LLM: read + compare, one call per person
    sources.py, groups.py          people, value sources, the checks in order
    comparison.py                  findings and cross_verify on every pair
    third_party.py                 mocked third-party checks
    report.py, truth_table.py      checklist, report, truth table
    cross_verify/                  the engine: common, config, names, dates, address_parser,
                                   addresses, numbers, contacts, short_text, checks, engine
  ai/prompts/                      manager.py, templates/*.j2, configs/*.yaml (model per prompt)
  config/                          settings.py, anomaly_config.yaml, structured_mapping.yaml
  security/                        rate_limit, request_limits, uploads, pii (Aadhaar masking)
  utils/                           images (PDF / image blocks), ocr_text, logging/
```

## Storage

`<DATA_DIR>/<case_id>/`: `lead.json`, `result.json`, `runs/<run_id>.json`,
`application_form/<file>` + `<file>.extracted.json`, `documents/<party_id>/<file>` +
`<file>.extracted.json`. Switch with `storage.keep_uploads` / `storage.keep_extracted_json`.

## Privacy

- The extracted JSON, the report and the logs keep only the last 4 Aadhaar digits.
- Uploaded files are stored as they were sent (`keep_uploads: true`), so an Aadhaar image or OCR
  file keeps the full number. Turn it off, or move storage to an encrypted store, before real use.
- The Orchestrator Agent's LLM sees only the case_id and a short summary, never document text.

## Mock third-party overrides

```json
{"applicant": {"bureau": {"name": "...", "dob": "...", "addresses": [{"address": "...", "reported_on": "2026-08-01"}]},
               "pan_aadhaar_linked": false, "voter_dl": {"status": "NOT_VERIFIED"},
               "email_ownership_verified": false, "face_match": {"match_pct": 68, "status": "SUCCESS"}}}
```
Real APIs: implement `KycProvider` (`backend/src/adapters/kyc/base.py`) and pass it to
`AnomalyDetectionAgent(settings, provider=...)`.
