"""
File: engine.py
Purpose: Decide colours and run a list of checks into one report.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import datetime as dt
import os
import re
import uuid
from collections.abc import Mapping
from typing import Any

from src.utils.logging.logger import get_logger

from .address_parser import parse_address
from .addresses import compare_addresses
from .amounts import compare_amounts
from .amounts import parse_amount
from .config import load_config
from .config import prepare_config
from .constants import Json
from .contacts import compare_emails
from .contacts import compare_phones
from .contacts import parse_email
from .contacts import parse_phone
from .dates import compare_dobs
from .dates import parse_dob
from .decision import build_result
from .decision import roll_up
from .errors import ModeNotImplementedError
from .identifiers import compare_ids
from .identifiers import parse_id
from .names import compare_names
from .names import parse_name
from .requests import read_checks
from .short_text import compare_texts
from .short_text import parse_text
from .text import add_reason
from .text import failure
from .text import is_missing
from .text import show

logger = get_logger(__name__)
# A bug in one parser or comparer must turn one comparison red, never stop the report.
_RECOVERABLE = (
    ArithmeticError,
    AttributeError,
    LookupError,
    RuntimeError,
    TypeError,
    ValueError,
    re.error,
)


COMPARERS = {
    "name": compare_names,
    "dob": compare_dobs,
    "address": compare_addresses,
    "id": compare_ids,
    "amount": compare_amounts,
    "email": compare_emails,
    "phone": compare_phones,
    "text": compare_texts,
}


def parse_value(
    field_type: str, kind: str, value: Any, cfg: Json, side: str, today: dt.date
) -> Json:
    """Check the value, then parse it.

    Args:
        field_type: One of the supported field types.
        kind: Sub-kind (for id and text types), or an empty string.
        value: The raw value.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.
        today: Reference date.

    Returns:
        ``{"ok": True, ...}`` or ``{"ok": False, "code", "message"}``.
    """
    if is_missing(value, cfg):
        return failure(
            "BASE_MISSING" if side == "base" else "MISSING_VALUE",
            f"The {side} value is missing.",
        )
    text = show(value)
    if text is None:
        return failure(
            "UNPARSEABLE", f"The {side} value is not text, a number or a date."
        )
    if len(text) > cfg["limits"]["max_text_length"][field_type]:
        return failure("TOO_LONG", f"The {side} value is too long.")
    if field_type == "name":
        return parse_name(text, cfg, side)
    if field_type == "address":
        return parse_address(text, cfg, side)
    if field_type == "id":
        return parse_id(text, cfg, side, kind)
    if field_type == "amount":
        return parse_amount(text, cfg, side)
    if field_type == "email":
        return parse_email(text, cfg, side)
    if field_type == "phone":
        return parse_phone(text, cfg, side)
    if field_type == "text":
        return parse_text(text, cfg, side, kind)
    return parse_dob(value, text, cfg, side, today)


def compare_one(
    field_type: str, kind: str, base: Json, value: Any, cfg: Json, today: dt.date
) -> Json:
    """Compare the parsed base with one candidate value. A value that cannot be read becomes red.

    Args:
        field_type: One of the supported field types.
        kind: Sub-kind (for id and text types), or an empty string.
        base: Parsed base value.
        value: Raw candidate value.
        cfg: Prepared configuration.
        today: Reference date.

    Returns:
        The outcome of the comparison.
    """
    cand = parse_value(field_type, kind, value, cfg, "candidate", today)
    broken = base if not base["ok"] else cand if not cand["ok"] else None
    if broken:
        reasons: list[Json] = []
        add_reason(reasons, cfg, broken["code"], broken["message"])
        return {
            "reasons": reasons,
            "exact": False,
            "base_normalized": None,
            "candidate_normalized": None,
            "base_spans": [],
            "cand_spans": [],
        }
    result: Json = COMPARERS[field_type](base, cand, cfg, today)
    return result


def parse_safely(
    field_type: str, kind: str, value: Any, cfg: Json, side: str, today: dt.date
) -> Json:
    """parse_value, but an unexpected error becomes a failure instead of stopping the request.

    Args:
        field_type: One of the supported field types.
        kind: Sub-kind, or an empty string.
        value: The raw value.
        cfg: Prepared configuration.
        side: "base" or "candidate".
        today: Reference date.

    Returns:
        The parsed value, or an INTERNAL_ERROR failure.
    """
    try:
        return parse_value(field_type, kind, value, cfg, side, today)
    except _RECOVERABLE as exc:
        logger.error(
            "cross_verify.parse_failed",
            error_type=type(exc).__name__,
            field_type=field_type,
        )
        return failure("INTERNAL_ERROR", f"The {side} value could not be processed.")


def compare_safely(
    field_type: str, kind: str, base: Json, value: Any, cfg: Json, today: dt.date
) -> Json:
    """compare_one, but an unexpected error becomes a red INTERNAL_ERROR (logged without the values).

    Args:
        field_type: One of the supported field types.
        kind: Sub-kind, or an empty string.
        base: Parsed base value.
        value: Raw candidate value.
        cfg: Prepared configuration.
        today: Reference date.

    Returns:
        The outcome, or an INTERNAL_ERROR outcome.
    """
    try:
        return compare_one(field_type, kind, base, value, cfg, today)
    except _RECOVERABLE as exc:
        logger.error(
            "cross_verify.compare_failed",
            error_type=type(exc).__name__,
            field_type=field_type,
        )
        outcome: Json = {
            "reasons": [],
            "exact": False,
            "base_normalized": None,
            "candidate_normalized": None,
            "base_spans": [],
            "cand_spans": [],
        }
        add_reason(
            outcome["reasons"],
            cfg,
            "INTERNAL_ERROR",
            "The comparison could not be completed.",
        )
        return outcome


def run_checks(
    checks: Any, cfg: Json, request_id: str | None, today: dt.date | None
) -> Json:
    """The whole job: read the request, compare every candidate, roll the results up.

    Args:
        checks: The list of checks (or ``{"checks": [...]}``).
        cfg: Prepared configuration.
        request_id: Request id for the report; generated when None.
        today: Reference date; today's date when None.

    Returns:
        The report: overall result, per-field results and every comparison.

    Raises:
        InputError: If the request is malformed.
    """
    request_id = request_id or uuid.uuid4().hex[:12]
    today = today or dt.date.today()
    fields: list[Json] = []
    counts = {"match": 0, "warning": 0, "mismatch": 0}
    for check in read_checks(checks, cfg):
        # the base is parsed once for all its candidates
        base = parse_safely(
            check["type"], check["kind"], check["base"], cfg, "base", today
        )
        comparisons = []
        for candidate in check["candidates"]:
            outcome = compare_safely(
                check["type"], check["kind"], base, candidate["value"], cfg, today
            )
            comparison = build_result(
                candidate["source"],
                candidate["id"],
                show(check["base"]),
                show(candidate["value"]),
                outcome,
                cfg,
            )
            counts[comparison["status"]] += 1
            comparisons.append(comparison)
        fields.append(
            {
                "field": check["field"],
                "type": check["type"],
                **({"kind": check["kind"]} if check["kind"] else {}),
                "base": {
                    "raw": show(check["base"]),
                    "normalized": base.get("normalized"),
                },
                **roll_up(comparisons),
                "comparisons": comparisons,
            }
        )
    logger.info(
        "cross_verify.verified",
        request_id=request_id,
        checks=len(fields),
        counts=counts,
        config_hash=cfg["config_hash"],
    )
    return {
        "config_hash": cfg["config_hash"],
        "config_label": cfg["config_label"],
        "mode": "fuzzy",
        "request_id": request_id,
        "overall": {**roll_up(fields), "counts": counts},
        "fields": fields,
    }


def create_verifier(
    config: Mapping[str, Any] | None = None,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> Any:
    """Load the settings once and return ``verify(checks, *, request_id=None, today=None)``.

    Pass a config mapping (for tests) or a config_path. Otherwise
    $CROSS_VERIFY_CONFIG_PATH, or the file next to this package, is used. Create it
    once; it is safe to share between threads.

    Args:
        config: Optional configuration mapping.
        config_path: Optional path to the configuration file.

    Returns:
        The verify function.

    Raises:
        ConfigError: If the configuration is invalid.
        ModeNotImplementedError: If the configured mode has no engine yet.
    """
    cfg = prepare_config(config) if config is not None else load_config(config_path)
    mode = cfg["mode"]
    if mode == "fuzzy":
        engine = run_checks  # the rules in this file
    elif mode == "hybrid":
        # Future: run the fuzzy rules first, then let the LLM review the result. Set `engine` here.
        raise ModeNotImplementedError("mode 'hybrid' is not developed yet; use 'fuzzy'")
    elif mode == "llm":
        # Future: the LLM (AWS Bedrock) makes the whole comparison. Set `engine` here.
        raise ModeNotImplementedError("mode 'llm' is not developed yet; use 'fuzzy'")
    else:
        raise ModeNotImplementedError(f"mode '{mode}' has no engine yet; use 'fuzzy'")

    def verify(
        checks: Any, *, request_id: str | None = None, today: dt.date | None = None
    ) -> Json:
        return engine(checks, cfg, request_id, today)

    return verify
