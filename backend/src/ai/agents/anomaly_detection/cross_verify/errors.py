"""
File: errors.py
Purpose: Errors raised by the cross_verify engine.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations


class CrossVerifyError(Exception):
    """Base class of every error raised here."""


class ConfigError(CrossVerifyError):
    """The configuration file is missing or invalid."""


class InputError(CrossVerifyError, ValueError):
    """The request itself is malformed (a bad data value is never an error, it is red)."""


class ModeNotImplementedError(CrossVerifyError, NotImplementedError):
    """hybrid and llm are not developed yet."""
