"""
File: constants.py
Purpose: Reason codes, colours, field types and type aliases.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

from typing import Any

Json = dict[str, Any]
Span = tuple[int, int, str]  # (start, end, kind) over the raw text, used for highlights


REASONS: dict[
    str, str
] = {  # reason code -> severity. The colour is the worst severity of the reasons found.
    "EXACT": "info",
    "NORMALIZED_EQUAL": "info",
    "HONORIFIC_IGNORED": "info",
    "CARE_OF_REMOVED": "info",
    "LABEL_STRIPPED": "info",
    "POSSIBLE_TYPO": "info",
    "TOKEN_ORDER_DIFFERENT": "warn",
    "INITIAL_EXPANDED": "warn",
    "EXTRA_INITIALS": "warn",
    "MISSING_INITIALS": "warn",
    "EXTRA_TOKEN": "warn",
    "MISSING_TOKEN": "warn",
    "SPACING_DIFFERENCE": "warn",
    "SPELLING_VARIANT": "warn",
    "NON_LATIN_TEXT_IGNORED": "warn",
    "INCOMPLETE_ADDRESS": "warn",
    "NUMBER_SUBSET": "warn",
    "PINCODE_NEAR": "warn",
    "WORDS_PARTIAL": "warn",
    "ID_MASKED": "warn",
    "ID_OCR_VARIANT": "warn",
    "ID_PARTIAL": "warn",
    "ID_FORMAT_DOUBTFUL": "warn",
    "PHONE_COUNTRY_ASSUMED": "warn",
    "AMOUNT_ROUNDED": "warn",
    "AMOUNT_NEAR": "warn",
    "CURRENCY_ASSUMED": "warn",
    "EMAIL_ALIAS": "warn",
    "PHONE_PARTIAL": "warn",
    "DIFFERENCE_UNCLASSIFIED": "warn",
    "MISSING_VALUE": "fail",
    "BASE_MISSING": "fail",
    "UNPARSEABLE": "fail",
    "UNSUPPORTED_SCRIPT": "fail",
    "TOO_LONG": "fail",
    "DATE_IMPLAUSIBLE": "fail",
    "INTERNAL_ERROR": "fail",
    "TOKEN_CONFLICT": "fail",
    "INSUFFICIENT_NAME": "fail",
    "NO_ANCHOR_MATCH": "fail",
    "DATE_DIFFERENT": "fail",
    "PINCODE_MISMATCH": "fail",
    "CITY_MISMATCH": "fail",
    "NUMBER_MISMATCH": "fail",
    "WORDS_MISMATCH": "fail",
    "ID_DIFFERENT": "fail",
    "AMOUNT_DIFFERENT": "fail",
    "CURRENCY_MISMATCH": "fail",
    "EMAIL_DIFFERENT": "fail",
    "PHONE_DIFFERENT": "fail",
    "TEXT_DIFFERENT": "fail",
}
FLAG_OF_SEVERITY = {"info": "green", "warn": "yellow", "fail": "red"}
FLAG_RANK = {"green": 0, "yellow": 1, "red": 2}
STATUS_OF_FLAG = {"green": "match", "yellow": "warning", "red": "mismatch"}
MODES = ("fuzzy", "hybrid", "llm")
FIELD_TYPES = ("name", "dob", "address", "id", "amount", "email", "phone", "text")

# "type" values a caller may use. Each one names the field type and, where it is implied, the kind.
TYPE_ALIASES: dict[str, tuple[str, str]] = {
    "date_of_birth": ("dob", ""),
    "birth_date": ("dob", ""),
    "aadhaar": ("id", "aadhaar"),
    "aadhar": ("id", "aadhaar"),
    "aadhaar_number": ("id", "aadhaar"),
    "pan": ("id", "pan"),
    "pan_number": ("id", "pan"),
    "passport": ("id", "passport"),
    "passport_number": ("id", "passport"),
    "voter_id": ("id", "voter"),
    "driving_licence": ("id", "driving_licence"),
    "driving_license": ("id", "driving_licence"),
    "id_number": ("id", ""),
    "document_number": ("id", ""),
    "money": ("amount", ""),
    "fee": ("amount", ""),
    "email_id": ("email", ""),
    "e_mail": ("email", ""),
    "mobile": ("phone", ""),
    "mobile_number": ("phone", ""),
    "phone_number": ("phone", ""),
    "gender": ("text", "gender"),
    "sex": ("text", "gender"),
    "relationship": ("text", "relationship"),
    "relation": ("text", "relationship"),
    "nationality": ("text", "nationality"),
    "organisation": ("text", ""),
    "organization": ("text", ""),
    "university": ("text", ""),
    "employer": ("text", ""),
    "course": ("text", ""),
}
ENV_CONFIG_PATH = "CROSS_VERIFY_CONFIG_PATH"
DEFAULT_CONFIG_NAME = "cross_verify_config.json"
