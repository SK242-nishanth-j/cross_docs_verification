"""
File: convert_batch_ocr.py
Purpose: Convert a batch OCR export into the trigger payload (and optionally a sample case).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic

The export looks like ``{case, documents: [{file, pages: [{result: {text}}]}]}``.
A mapping file names the party and document type of every file:
``{"Applicant PAN.jpg": ["applicant", "PAN"], ...}``.

Run from the backend folder:
    python scripts/convert_batch_ocr.py ../caseN_full.json ../caseN_mapping.json
        ../caseN_documents.json --sample contracts/examples/local_caseN_<CASE_ID>.json

Keep the export and mapping files out of contracts/examples: they hold real data.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai.agents.anomaly_detection.schemas import CaseInput  # noqa: E402
from src.ai.agents.anomaly_detection.schemas import TriggerRequest  # noqa: E402


def _page_text(page: dict[str, Any]) -> str:
    """Return the OCR text of one exported page.

    Args:
        page: One page of the export.

    Returns:
        ``result.text``, or an empty string when it is missing.
    """
    result = page.get("result")
    if isinstance(result, dict) and isinstance(result.get("text"), str):
        return str(result["text"])
    return ""


def convert(
    export: dict[str, Any], mapping: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """Turn the exported documents into trigger documents.

    Args:
        export: The batch OCR export.
        mapping: File name -> [party_id, doc_type].

    Returns:
        One trigger document per exported file.

    Raises:
        SystemExit: If a file has no entry in the mapping.
    """
    documents = export.get("documents") or []
    unmapped = [doc.get("file") for doc in documents if doc.get("file") not in mapping]
    if unmapped:
        raise SystemExit(f"no mapping for: {', '.join(map(str, unmapped))}")
    out: list[dict[str, Any]] = []
    for doc in documents:
        party_id, doc_type = mapping[doc["file"]]
        pages = [
            {
                "page_number": page.get("page", n),
                "text_lines": [
                    line for line in _page_text(page).splitlines() if line.strip()
                ],
            }
            for n, page in enumerate(doc.get("pages") or [], start=1)
        ]
        out.append(
            {
                "party_id": party_id,
                "doc_type": doc_type,
                "file_name": doc["file"],
                "ocr": {"status": "ok", "pages": pages},
            }
        )
    return out


def main() -> None:
    """Read the export and mapping, write the payload and update the sample."""
    parser = argparse.ArgumentParser(
        description="Convert a batch OCR export into the trigger payload."
    )
    parser.add_argument("export", type=Path, help="batch OCR export (JSON)")
    parser.add_argument("mapping", type=Path, help="file name -> [party_id, doc_type]")
    parser.add_argument("out", type=Path, help="trigger payload to write")
    parser.add_argument(
        "--sample", type=Path, help="sample case whose documents are replaced"
    )
    args = parser.parse_args()

    export = json.loads(args.export.read_text(encoding="utf-8-sig"))
    mapping = json.loads(args.mapping.read_text(encoding="utf-8-sig"))
    docs = convert(export, mapping)

    payload = {"documents": docs, "mock_overrides": {}}
    TriggerRequest.model_validate(payload)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(docs)} documents to {args.out}")

    if args.sample:
        sample = json.loads(args.sample.read_text(encoding="utf-8-sig"))
        sample["documents"] = docs
        CaseInput.model_validate(
            {
                key: sample.get(key)
                for key in ("case_id", "lead", "documents", "mock_overrides")
                if key in sample
            }
        )
        args.sample.write_text(
            json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"replaced the documents of {args.sample}")


if __name__ == "__main__":
    main()
