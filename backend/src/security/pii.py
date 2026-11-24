"""
File: pii.py
Purpose: Mask Aadhaar numbers (keep the last 4 digits) before text is stored, logged or sent to an LLM.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import re

_AADHAAR = re.compile(r"(?<![\dX])([2-9]\d{3})[ -]?(\d{4})[ -]?(\d{4})(?!\d)")
_VID = re.compile(r"(?<![\dX])(\d{4})[ -]?(\d{4})[ -]?(\d{4})[ -]?(\d{4})(?!\d)")
_AADHAAR_WORDS = re.compile(r"aadh?aa?r|\buid\b|\bvid\b|enrol?ment", re.IGNORECASE)


def _mask_all(text: str) -> str:
    """Mask every 16-digit VID and every 12-digit Aadhaar-shaped number."""
    text = _VID.sub(lambda m: f"XXXX XXXX XXXX {m.group(4)}", text)
    return _AADHAAR.sub(lambda m: f"XXXX XXXX {m.group(3)}", text)


def _mask_line(line: str) -> str:
    """Mask 12-digit Aadhaar-shaped numbers in one line."""
    return _AADHAAR.sub(lambda m: f"XXXX XXXX {m.group(3)}", line)


def mask_aadhaar_lines(lines: list[str], *, aadhaar_card: bool) -> list[str]:
    """Mask Aadhaar numbers in OCR lines.

    On an Aadhaar card every 12-digit number is masked. On other documents only
    numbers on, or right after, a line that mentions Aadhaar / UID / VID are
    masked, so 12- or 16-digit bank account numbers stay readable.

    Args:
        lines: OCR text lines.
        aadhaar_card: Whether the document is an Aadhaar card.

    Returns:
        The lines with Aadhaar numbers reduced to their last 4 digits.
    """
    if aadhaar_card:
        return [_mask_all(line) for line in lines]
    out: list[str] = []
    previous_mentions = False
    for line in lines:
        mentions = bool(_AADHAAR_WORDS.search(line))
        out.append(_mask_line(line) if mentions or previous_mentions else line)
        previous_mentions = mentions
    return out


def aadhaar_last4(value: str) -> str:
    """Keep only the last 4 digits of an Aadhaar number.

    Args:
        value: A full, masked or partial Aadhaar number.

    Returns:
        The last 4 digits.

    Raises:
        ValueError: If the value has fewer than 4 digits.
    """
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        raise ValueError("Aadhaar: give at least the last 4 digits")
    return digits[-4:]
