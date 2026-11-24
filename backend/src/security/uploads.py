"""
File: uploads.py
Purpose: Validate uploaded files at the API boundary: allowed extension for the mode, size, count.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

from pathlib import PurePath

from fastapi import UploadFile

from src.services.errors import InvalidInputError


def read_upload(file: UploadFile, accepts: list[str], max_bytes: int) -> bytes:
    """Read one uploaded file after checking its extension and size.

    Args:
        file: The uploaded file.
        accepts: Allowed extensions for the configured mode, for example ``[".pdf"]``.
        max_bytes: Largest accepted size.

    Returns:
        The file bytes.

    Raises:
        InvalidInputError: If the name, the extension or the size is not accepted.
    """
    name = file.filename or ""
    suffix = PurePath(name).suffix.lower()
    if not name or suffix not in accepts:
        raise InvalidInputError(
            f"{name or 'file'}: this mode accepts {', '.join(accepts)} files only"
        )
    content = file.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise InvalidInputError(f"{name}: larger than {max_bytes // 1_000_000} MB")
    if not content:
        raise InvalidInputError(f"{name}: the file is empty")
    return content
