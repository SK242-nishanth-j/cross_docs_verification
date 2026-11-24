"""
File: export_openapi.py
Purpose: Write the OpenAPI contract to contracts/openapi.json for the frontend.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi

Run from the backend folder:  python -m scripts.export_openapi
"""

import json
from pathlib import Path

from src.main import app

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "contracts" / "openapi.json"


def main() -> None:
    """Generate the contract file."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    document = json.dumps(app.openapi(), indent=2, sort_keys=True)
    OUTPUT_PATH.write_text(document + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
