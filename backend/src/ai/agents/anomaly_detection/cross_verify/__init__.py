"""
File: __init__.py
Purpose: Deterministic cross-verification engine (names, dates, addresses, IDs, ...).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: rapidfuzz

Usage:
    verify = create_verifier(config_path=...)
    report = verify([{"field": "name", "type": "name", "base": "...",
                      "candidates": [{"source": "pan", "value": "..."}]}])
"""

from .config import load_config
from .config import prepare_config
from .constants import Json
from .engine import create_verifier
from .engine import run_checks
from .errors import ConfigError
from .errors import CrossVerifyError
from .errors import InputError
from .errors import ModeNotImplementedError

__all__ = [
    "ConfigError",
    "CrossVerifyError",
    "InputError",
    "Json",
    "ModeNotImplementedError",
    "create_verifier",
    "load_config",
    "prepare_config",
    "run_checks",
]
