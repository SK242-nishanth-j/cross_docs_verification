"""
File: cross_verify_cli.py
Purpose: Command-line demo of the cross_verify engine (checks JSON in, report JSON out).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

Same options as the original cross_verify.py command line. Run from the backend folder:
    python -m scripts.cross_verify_cli --input checks.json [--config path]
        [--env-file .env] [--compact]
"""

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from src.ai.agents.anomaly_detection.cross_verify import CrossVerifyError
from src.ai.agents.anomaly_detection.cross_verify import create_verifier
from src.ai.agents.anomaly_detection.cross_verify.common import DEFAULT_CONFIG_NAME
from src.ai.agents.anomaly_detection.cross_verify.common import ENV_CONFIG_PATH


def read_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Read KEY=value lines. Blank lines and # comments are skipped.

    Args:
        path: The settings file.

    Returns:
        The settings found in the file.
    """
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("\"'")
    return values


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
    parser.add_argument(
        "--env-file", default=".env", help="KEY=value settings file (default: .env)"
    )
    parser.add_argument("--compact", action="store_true", help="print one line of JSON")
    args = parser.parse_args(argv)
    if Path(args.env_file).is_file():
        for key, value in read_env_file(args.env_file).items():
            os.environ.setdefault(key, value)
    logging.basicConfig(
        level=os.environ.get("CROSS_VERIFY_LOG_LEVEL", "INFO").upper(),
        stream=sys.stderr,
    )
    try:
        source = sys.stdin if args.input == "-" else open(args.input, encoding="utf-8")  # noqa: SIM115
        with source:
            report = create_verifier(config_path=args.config)(json.load(source))
    except (CrossVerifyError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
