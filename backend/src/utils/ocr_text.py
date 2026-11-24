"""
File: ocr_text.py
Purpose: Turn an OCR JSON (pages -> text_lines / structured_lines) or plain text into one masked text.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from dataclasses import dataclass
from typing import Any

from src.security.pii import mask_aadhaar_lines


class OcrInputError(ValueError):
    """The OCR payload has no readable text."""


@dataclass(frozen=True)
class OcrText:
    """Masked OCR text with simple statistics."""

    text: str
    pages: int
    lines: int
    mean_confidence: float | None
    truncated: bool

    def stats(self) -> dict[str, Any]:
        """Return the statistics without the text.

        Returns:
            Pages, lines, mean OCR confidence and whether the text was truncated.
        """
        return {
            "pages": self.pages,
            "lines": self.lines,
            "mean_confidence": self.mean_confidence,
            "truncated": self.truncated,
        }


def _page_lines(page: dict[str, Any]) -> list[str]:
    """Read the text lines of one OCR page in its known shapes."""
    if isinstance(page.get("text_lines"), list):
        return [str(t) for t in page["text_lines"] if str(t).strip()]
    if isinstance(page.get("structured_lines"), list):
        return [
            str(s.get("text", ""))
            for s in page["structured_lines"]
            if isinstance(s, dict) and str(s.get("text", "")).strip()
        ]
    if isinstance(page.get("text"), str):
        return [t for t in page["text"].splitlines() if t.strip()]
    return []


def _confidences(page: dict[str, Any]) -> list[float]:
    """Collect the line confidences of one OCR page."""
    return [
        float(s["confidence"])
        for s in page.get("structured_lines") or []
        if isinstance(s, dict) and isinstance(s.get("confidence"), int | float)
    ]


def ocr_to_text(
    ocr: dict[str, Any] | None,
    raw_ocr: str | None,
    *,
    aadhaar_card: bool,
    max_chars: int,
) -> OcrText:
    """Join every page (with a page marker) and mask Aadhaar numbers.

    Args:
        ocr: OCR JSON with a ``pages`` list, or None.
        raw_ocr: Plain OCR text, used when ``ocr`` is None.
        aadhaar_card: Whether the document is an Aadhaar card.
        max_chars: Longest text kept; the rest is cut off.

    Returns:
        The masked text and its statistics.

    Raises:
        OcrInputError: If there is no readable text.
    """
    chunks: list[str] = []
    confidences: list[float] = []
    pages = lines = 0
    if ocr is not None:
        page_list = ocr.get("pages")
        if not isinstance(page_list, list) or not page_list:
            raise OcrInputError("the OCR JSON has no 'pages'")
        for number, page in enumerate(page_list, start=1):
            if not isinstance(page, dict):
                continue
            page_lines = mask_aadhaar_lines(
                _page_lines(page), aadhaar_card=aadhaar_card
            )
            confidences += _confidences(page)
            pages += 1
            lines += len(page_lines)
            label = page.get("page_number", number)
            chunks.append(f"--- Page {label} ---\n" + "\n".join(page_lines))
    elif raw_ocr is not None:
        raw_lines = [t for t in raw_ocr.splitlines() if t.strip()]
        masked = mask_aadhaar_lines(raw_lines, aadhaar_card=aadhaar_card)
        pages, lines = 1, len(masked)
        chunks.append("\n".join(masked))
    text = "\n".join(chunks).strip()
    if lines == 0 or not text:  # page markers alone are not text
        raise OcrInputError("the OCR has no text")
    mean = round(sum(confidences) / len(confidences), 4) if confidences else None
    return OcrText(
        text=text[:max_chars],
        pages=pages,
        lines=lines,
        mean_confidence=mean,
        truncated=len(text) > max_chars,
    )
