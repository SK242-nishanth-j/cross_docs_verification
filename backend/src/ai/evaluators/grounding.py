"""
File: grounding.py
Purpose: Keep an LLM-extracted value only if it can be found in the OCR text it was read from.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import re
import unicodedata
from dataclasses import dataclass


def _fold(text: str) -> str:
    """Lower-case and drop accents."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


def tokens(text: str) -> list[str]:
    """Split text into folded letter/digit tokens.

    Args:
        text: Any text.

    Returns:
        The tokens in order.
    """
    return re.findall(r"[a-z0-9]+", _fold(text))


@dataclass(frozen=True)
class Source:
    """An OCR text prepared for fast lookups."""

    spaced: str
    compact: str
    token_set: frozenset[str]

    @classmethod
    def of(cls, text: str) -> "Source":
        """Prepare an OCR text.

        Args:
            text: The OCR text.

        Returns:
            The prepared source.
        """
        toks = tokens(text)
        return cls(" " + " ".join(toks) + " ", "".join(toks), frozenset(toks))


def ground(value: str, source: Source) -> str | None:
    """Tell how a value is found in the source text.

    Args:
        value: The extracted value.
        source: The prepared OCR text.

    Returns:
        ``verbatim``, ``compact`` (spacing differs), ``tokens`` (same words in
        another order), or None when the value is not in the text.
    """
    toks = tokens(value)
    if not toks:
        return None
    if " " + " ".join(toks) + " " in source.spaced:
        return "verbatim"
    joined = "".join(toks)
    if len(joined) >= 4 and joined in source.compact:
        return "compact"
    if all(t in source.token_set for t in toks):
        return "tokens"
    return None


def clean(value: object) -> str | None:
    """Collapse whitespace; empty values become None.

    Args:
        value: Any value returned by the model.

    Returns:
        The cleaned text, or None.
    """
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None
