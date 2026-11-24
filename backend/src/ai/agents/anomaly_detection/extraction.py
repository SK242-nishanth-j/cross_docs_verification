"""
File: extraction.py
Purpose: Hybrid mode: one LLM read per document (OCR text -> grounded fields); shared field cleaning.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: strands-agents

The model only reads values out of the OCR text. Every value is then looked up
in that same text (grounding); anything that is not there is dropped, so
cross_verify never compares invented values.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.adapters.bedrock.client import MODEL_CALL_ERRORS
from src.adapters.bedrock.client import BedrockModels
from src.adapters.bedrock.client import BedrockUnavailableError
from src.adapters.bedrock.client import extract_structured
from src.ai.agents.anomaly_detection.schemas import FIELDS
from src.ai.agents.anomaly_detection.schemas import DocumentExtraction
from src.ai.agents.anomaly_detection.schemas import DocumentIn
from src.ai.agents.anomaly_detection.schemas import ExtractedFields
from src.ai.evaluators.grounding import Source
from src.ai.evaluators.grounding import clean
from src.ai.evaluators.grounding import ground
from src.ai.prompts.manager import PromptManager
from src.config.settings import Settings
from src.security.pii import mask_aadhaar_lines
from src.utils.logging.logger import get_logger
from src.utils.ocr_text import OcrInputError
from src.utils.ocr_text import OcrText
from src.utils.ocr_text import ocr_to_text

logger = get_logger(__name__)
_FOUR_DIGITS = re.compile(r"(?<!\d)\d{4}(?!\d)")


def clean_fields(doc_type: str, raw: dict[str, Any]) -> dict[str, str]:
    """Keep the known, non-empty fields; an Aadhaar number keeps its last 4 digits.

    Args:
        doc_type: The document type.
        raw: Field values (from the LLM or a structured JSON).

    Returns:
        Cleaned field values.
    """
    out: dict[str, str] = {}
    for name in FIELDS:
        value = clean(raw.get(name))
        if value is None:
            continue
        if name == "id_number" and doc_type == "AADHAAR":
            masked = mask_aadhaar_lines([value], aadhaar_card=True)[0]
            # Keep "XXXX XXXX 1234" only, without notes such as "(first 8 digits hidden)".
            groups = _FOUR_DIGITS.findall(masked)
            value = f"XXXX XXXX {groups[-1]}" if groups else masked
        out[name] = value
    return out


def document_text(doc: DocumentIn, max_chars: int) -> OcrText:
    """Turn an uploaded OCR file into one Aadhaar-masked text.

    Args:
        doc: The document (OCR JSON or plain text).
        max_chars: Longest text kept.

    Returns:
        The masked text and its statistics.

    Raises:
        OcrInputError: If the file has no readable OCR text.
    """
    try:
        ocr, raw = doc.ocr_input()
    except ValueError as exc:
        raise OcrInputError(str(exc)) from exc
    return ocr_to_text(
        ocr, raw, aadhaar_card=doc.doc_type == "AADHAAR", max_chars=max_chars
    )


def ground_fields(
    fields: dict[str, str], text: str
) -> tuple[dict[str, str], dict[str, str], list[dict[str, str]]]:
    """Keep only the values that are found in the OCR text.

    Args:
        fields: Cleaned field values from the model.
        text: The masked OCR text they were read from.

    Returns:
        (fields kept, how each was found, values dropped as NOT_IN_SOURCE).
    """
    source = Source.of(text)
    kept: dict[str, str] = {}
    grounding: dict[str, str] = {}
    dropped: list[dict[str, str]] = []
    for name, value in fields.items():
        how = ground(value, source)
        if how:
            kept[name], grounding[name] = value, how
        else:
            dropped.append({"field": name, "value": value, "reason": "NOT_IN_SOURCE"})
    return kept, grounding, dropped


class DocumentExtractor:
    """Reads identity fields from each document's OCR text (hybrid mode)."""

    def __init__(
        self,
        settings: Settings,
        config: dict[str, Any],
        prompts: PromptManager,
        models: BedrockModels,
    ) -> None:
        self._settings = settings
        self._hints: dict[str, list[str]] = config["fields_by_doc_type"]
        self._prompt = str(config["modes"]["ocr_hybrid"]["extraction_prompt"])
        self._prompts = prompts
        self._models = models

    @property
    def model_id(self) -> str:
        """Return the model used for extraction.

        Returns:
            The effective Bedrock model ID.
        """
        return self._models.model_id(self._prompts.config(self._prompt).llm.model_id)

    def extract_one(self, index: int, doc: DocumentIn) -> DocumentExtraction:
        """Read one document.

        Args:
            index: Position of the document in the case.
            doc: The document.

        Returns:
            The grounded fields, or a failed record (one document never stops the run).

        Raises:
            BedrockUnavailableError: If Bedrock refuses the call for a fatal reason.
        """
        started = time.perf_counter()
        out = DocumentExtraction(
            index, doc.party_id, doc.doc_type, doc.file_name, "llm"
        )
        out.stored_as = doc.stored_as
        try:
            text = document_text(doc, self._settings.document_max_ocr_chars)
        except OcrInputError as exc:
            out.status, out.error = "failed", f"OCR not readable: {exc}"
            return out
        out.stats = text.stats()
        cfg = self._prompts.config(self._prompt)
        hints = self._hints.get(doc.doc_type, self._hints["OTHER"])
        try:
            raw = extract_structured(
                self._models.get(
                    cfg.llm.model_id, cfg.llm.temperature, cfg.llm.max_tokens
                ),
                system_prompt=self._prompts.render_system(self._prompt),
                user_prompt=self._prompts.render_user(
                    self._prompt,
                    doc_type=doc.doc_type,
                    expected_fields=", ".join(hints),
                    ocr_text=text.text,
                ),
                schema=ExtractedFields,
                name="anomaly_detection_extractor",
            )
            fields = clean_fields(doc.doc_type, raw.model_dump())
            out.fields, out.grounding, out.dropped = ground_fields(fields, text.text)
        except BedrockUnavailableError:
            raise
        except MODEL_CALL_ERRORS as exc:
            logger.warning(
                "extraction.document_failed",
                document_index=index,
                doc_type=doc.doc_type,
                error_type=type(exc).__name__,
            )
            out.status = "failed"
            out.error = f"Extraction failed ({type(exc).__name__})."
        out.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return out

    def extract_all(self, documents: list[DocumentIn]) -> list[DocumentExtraction]:
        """Read every document in parallel.

        Args:
            documents: All documents of the case.

        Returns:
            One extraction per document, in upload order.
        """
        workers = max(1, min(self._settings.extraction_workers, len(documents)))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="extract"
        ) as pool:
            return list(pool.map(self.extract_one, range(len(documents)), documents))
