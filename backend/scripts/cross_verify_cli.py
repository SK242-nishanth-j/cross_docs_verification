"""
File: cross_verify_cli.py
Purpose: Command-line demo of the cross_verify engine (checks JSON in, report JSON out).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

Run from the backend folder:
    python -m scripts.cross_verify_cli --input checks.json [--config path] [--compact]
"""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from src.ai.agents.anomaly_detection.cross_verify import CrossVerifyError
from src.ai.agents.anomaly_detection.cross_verify import create_verifier
from src.ai.agents.anomaly_detection.cross_verify.constants import DEFAULT_CONFIG_NAME
from src.ai.agents.anomaly_detection.cross_verify.constants import ENV_CONFIG_PATH


def _read_checks(source: str) -> Any:
    """Read the checks JSON from a file path, or from stdin when ``source`` is ``-``."""
    if source == "-":
        return json.load(sys.stdin)
    with open(source, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Sequence[str] | None = None) -> int:
    """Verify the checks in a JSON file and print the report.

    Args:
        argv: Command-line arguments; ``None`` reads ``sys.argv``.

    Returns:
        ``0`` on success, ``2`` when the input or configuration is invalid.
    """
    parser = argparse.ArgumentParser(
        description="Cross-verify values from several documents."
    )
    parser.add_argument(
        "--input", "-i", required=True, help="JSON file with the checks, or - for stdin"
    )
    parser.add_argument(
        "--config",
        help=f"config file (default: ${ENV_CONFIG_PATH}, else {DEFAULT_CONFIG_NAME})",
    )
    parser.add_argument("--compact", action="store_true", help="print one line of JSON")
    args = parser.parse_args(argv)
    try:
        report = create_verifier(config_path=args.config)(_read_checks(args.input))
    except (CrossVerifyError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
