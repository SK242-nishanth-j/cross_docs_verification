"""
File: images.py
Purpose: Turn an uploaded image or PDF into Bedrock image / document blocks for a vision model.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pillow, pypdfium2

PDF pages are rendered to JPEG (or sent as one PDF document block when
``pdf_input`` is ``document``). Images above the Bedrock limits are scaled down.
"""

import io
from typing import Any
from typing import Literal
from typing import cast

import pypdfium2 as pdfium
from PIL import Image
from PIL import UnidentifiedImageError
from strands.types.content import ContentBlock

ImageFormat = Literal["png", "jpeg", "gif", "webp"]
_FORMATS: dict[str, ImageFormat] = {
    "PNG": "png",
    "JPEG": "jpeg",
    "GIF": "gif",
    "WEBP": "webp",
}
_POINTS_PER_INCH = 72


class UnreadableFileError(ValueError):
    """The file is neither a readable image nor a readable PDF."""


def is_pdf(content: bytes) -> bool:
    """Tell whether the bytes are a PDF file.

    Args:
        content: File bytes.

    Returns:
        True when the file starts with the PDF signature.
    """
    return content[:5] == b"%PDF-"


def _jpeg(image: Image.Image, vision: dict[str, Any]) -> bytes:
    """Encode an image as JPEG within the size and pixel limits."""
    limit_px = int(vision["max_image_px"])
    if max(image.size) > limit_px:
        image.thumbnail((limit_px, limit_px))
    image = image.convert("RGB")
    quality = int(vision["jpeg_quality"])
    while True:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        data = buffer.getvalue()
        if len(data) <= int(vision["max_image_bytes"]) or quality <= 40:
            return data
        quality -= 15
        image = image.resize((image.width * 3 // 4, image.height * 3 // 4))


def _image_block(data: bytes, fmt: ImageFormat) -> ContentBlock:
    """Wrap image bytes in a Bedrock image block."""
    return cast(ContentBlock, {"image": {"format": fmt, "source": {"bytes": data}}})


def _pdf_pages(content: bytes, vision: dict[str, Any]) -> list[ContentBlock]:
    """Render every PDF page to a JPEG image block."""
    scale = float(vision["pdf_render_dpi"]) / _POINTS_PER_INCH
    try:
        pdf = pdfium.PdfDocument(content)
    except pdfium.PdfiumError as exc:
        raise UnreadableFileError("the PDF could not be opened") from exc
    try:
        return [
            _image_block(_jpeg(page.render(scale=scale).to_pil(), vision), "jpeg")
            for page in pdf
        ]
    finally:
        pdf.close()


def to_blocks(content: bytes, vision: dict[str, Any]) -> list[ContentBlock]:
    """Turn an uploaded image or PDF into blocks a vision model can read.

    Args:
        content: File bytes.
        vision: The ``vision`` section of anomaly_config.json.

    Returns:
        One image block per page, or one PDF document block.

    Raises:
        UnreadableFileError: If the bytes are not an image or a PDF.
    """
    if is_pdf(content):
        if vision.get("pdf_input") == "document":
            block = {
                "document": {
                    "format": "pdf",
                    "name": "document",
                    "source": {"bytes": content},
                }
            }
            return [cast(ContentBlock, block)]
        return _pdf_pages(content, vision)
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UnreadableFileError("the file is not an image or a PDF") from exc
    fmt = _FORMATS.get(str(image.format))
    within = len(content) <= int(vision["max_image_bytes"]) and max(image.size) <= int(
        vision["max_image_px"]
    )
    if fmt and within:
        return [_image_block(content, fmt)]
    return [_image_block(_jpeg(image, vision), "jpeg")]
