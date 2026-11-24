# Underwriting Copilot (dev): Orchestrator Agent + Anomaly Detection Agent

Built to the ShellKode Code Development Framework: SK folder layout, Jinja2 prompts with YAML
configs, Pydantic settings, JSON logs with correlation IDs, rate and request-size limits, IAM
credentials only, and the SK pre-commit gate (ruff, ruff-format, bandit, gitleaks, mypy --strict,
file checks, prompt validator).

```
UI 1. Case ID, applicant / co-applicant names
   2. Upload application form OCR  -> POST /v1/lead/autofill   -> LLM fills the lead fields (nothing stored)
   3. Review / edit                 -> POST /v1/cases/{id}/lead -> saved lead = BASE TRUTH
   4. Upload every document's OCR JSON (one shot) -> POST /v1/cases/{id}/trigger
        -> Orchestrator Agent (Strands Agent, LLM)                 src/ai/agents/orchestrator.py
             -> tool anomaly_detection_agent                         src/ai/tools/anomaly_detection_tool.py
                  a. OCR JSON -> text, Aadhaar masked                src/utils/ocr_text.py, src/security/pii.py
                  b. LLM reads each document + grounding             .../anomaly_detection/extraction.py
                  c. cross_verify: every source vs every source      .../anomaly_detection/cross_verify/
                     1 applicant  2 father  3 mother  4 other co-applicants
                  d. third-party checks (mock): KY-02 .. KY-06       .../anomaly_detection/kyc_rules.py
        <- full report stored, short LLM summary for the CM
```

The LLM does not decide match / mismatch. `cross_verify` does, deterministically.

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

Pre-commit (once the folder is a git repository), from `dev`:
```powershell
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Other scripts, from `dev/backend`:
```powershell
.venv\Scripts\python -m scripts.export_openapi                 # writes contracts/openapi.json
.venv\Scripts\python -m scripts.cross_verify_cli -i checks.json  # cross_verify demo
```

## Input formats

**Application form** (auto-fill): the OCR JSON as produced
(`{"status": "SUCCESS", "pages": [{"page_number": 1, "text_lines": [...], "structured_lines": [...]}]}`)
or a `.txt` file with the plain text.

**Documents** (trigger): upload the OCR JSON files directly (party and document type are guessed
from the file name and can be changed), or one payload JSON:
```json
{
  "documents": [
    {"party_id": "applicant", "doc_type": "PAN", "file_name": "Applicant PAN.json",
     "ocr": {"status": "SUCCESS", "pages": [{"page_number": 1, "text_lines": ["..."]}]}}
  ],
  "mock_overrides": {}
}
```
- `party_id`: `applicant`, `co_applicant_1`, `co_applicant_2`, ... (same as the lead)
- `doc_type`: `PAN`, `AADHAAR`, `PASSPORT`, `VOTER_ID`, `DRIVING_LICENCE`, `MARKSHEET`,
  `DEGREE_CERTIFICATE`, `ADMIT_LETTER`, `OTHER`
- `raw_ocr` (plain text) can be sent instead of `ocr`.

Synthetic example of everything: `backend/contracts/examples/synthetic_case.json` (UI: Load sample).
API contract: `backend/contracts/openapi.json`.

## What is compared (all pairs; the lead is one of the sources)

| Order | Party | Group | Sources |
|---|---|---|---|
| 1 | Applicant | NAME (KY-01) | lead, every applicant document, bureau |
| | | DOB (KY-01) | lead, every applicant document, bureau |
| | | FATHER_NAME / MOTHER_NAME | lead, applicant documents that print it |
| | | ADDRESS | lead, applicant documents that print it |
| | | PAN · AADHAAR (last 4) · PASSPORT_NO · DL_NO · VOTER_ID | lead, documents of that type |
| 2 | Father | PARENT_NAME (KY-01) | applicant's father name (lead + applicant documents) vs father's lead name, his documents, bureau |
| | | DOB (KY-01) · own FATHER/MOTHER_NAME · IDs | father's lead, his documents (+ bureau for DOB) |
| | | HOUSEHOLD_ADDRESS | father's lead + documents vs applicant's lead + documents |
| 3 | Mother | same as father | |
| 4 | Other co-applicants | NAME · DOB · FATHER/MOTHER_NAME · ADDRESS · IDs | their own lead, documents, bureau |

Then per party: KY-02 lead address vs bureau addresses from the last 12 months, KY-03 PAN-Aadhaar
link (sanction condition), KY-04 Voter ID / DL (CM justification), KY-05 email, KY-06 face match
>= 75% (critical). No document presence checks.

## Layout

```
backend/src/
  main.py                         app factory, middleware, error mapping
  api/                            routers: system, leads, cases, dependencies
  services/                       autofill_service, case_service, models (lead + API shapes), errors
  adapters/bedrock/client.py      Bedrock models for Strands (timeouts, retries), schema-bound calls
  adapters/storage/case_store.py  JSON per case: lead.json, result.json, runs/
  adapters/kyc/                   provider interface, models, mock provider
  ai/agents/orchestrator.py       Orchestrator Agent
  ai/agents/anomaly_detection/    agent, extraction, parties, sources, groups, pairs,
                                  bureau_rules, kyc_rules, findings, report, schemas
    cross_verify/                 the deterministic engine, split by field type
  ai/tools/                       anomaly_detection_tool (@tool, audit logs)
  ai/prompts/                     manager.py, templates/*.j2, configs/*.yaml
  ai/evaluators/grounding.py      LLM values must be found in the OCR text
  config/                         settings.py (pydantic-settings), anomaly_rules.json
  security/                       rate_limit, request_limits, pii (Aadhaar masking)
  utils/                          ocr_text, http_types, logging/ (JSON logger, correlation middleware)
backend/scripts/                  export_openapi, cross_verify_cli
backend/contracts/                openapi.json, examples/
scripts/validate_prompts.py       pre-commit prompt validator
frontend/src/                     app/, features/anomaly-detection/, services/, lib/, config/, styles/, types/
```

## Privacy

- Aadhaar: only the last 4 digits are kept, everywhere. On Aadhaar cards every 12-digit number is
  masked; on other documents only numbers on or right after a line that mentions Aadhaar / UID.
- The raw OCR JSON is never stored; the run record keeps the masked text only.
- The Orchestrator Agent's LLM sees only the case_id and a short summary, never document text.
- Logs carry IDs, counts and error types only; never document values.

## Mock third-party overrides

```json
{"applicant": {"bureau": {"name": "...", "dob": "...", "addresses": [{"address": "...", "reported_on": "2026-08-01"}]},
               "pan_aadhaar_linked": false, "voter_dl": {"status": "NOT_VERIFIED"},
               "email_ownership_verified": false, "face_match": {"match_pct": 68, "status": "SUCCESS"}}}
```
Real APIs: implement `KycProvider` (`backend/src/adapters/kyc/base.py`) and pass it to
`AnomalyDetectionAgent(settings, provider=...)`.
