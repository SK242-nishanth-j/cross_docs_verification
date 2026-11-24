"""
File: extraction.py
Purpose: Per-document LLM extraction: OCR -> masked text -> one Strands call -> grounded identity fields.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: strands-agents

The model only reads values out of the OCR text. Every value is then looked up
in that same text (grounding); anything that is not there is dropped, so
cross_verify never compares invented values.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from src.adapters.bedrock.client import MODEL_CALL_ERRORS
from src.adapters.bedrock.client import BedrockModels
from src.adapters.bedrock.client import BedrockUnavailableError
from src.adapters.bedrock.client import extract_structured
from src.ai.agents.anomaly_detection.schemas import DocumentIn
from src.ai.agents.anomaly_detection.schemas import ExtractedFields
from src.ai.evaluators.grounding import Source
from src.ai.evaluators.grounding import clean
from src.ai.evaluators.grounding import ground
from src.ai.prompts.manager import PromptManager
from src.config.settings import Settings
from src.utils.logging.logger import get_logger
from src.utils.ocr_text import OcrInputError
from src.utils.ocr_text import ocr_to_text

logger = get_logger(__name__)

PROMPT_NAME = "document_extraction"
FIELDS = tuple(ExtractedFields.model_fields)


@dataclass
class DocumentExtraction:
    """What was read from one document."""

    document_index: int
    party_id: str
    doc_type: str
    file_name: str
    status: str = "ok"  # ok | failed
    fields: dict[str, str] = field(default_factory=dict)
    grounding: dict[str, str] = field(default_factory=dict)
    dropped: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    ocr_stats: dict[str, Any] = field(default_factory=dict)
    masked_text: str = ""
    elapsed_ms: int = 0

    def get(self, name: str) -> str | None:
        """Return one extracted field.

        Args:
            name: Field name, for example ``dob``.

        Returns:
            The value, or None when it was not read.
        """
        return self.fields.get(name)

    def as_report(self) -> dict[str, Any]:
        """Return the extraction for the report (no OCR text).

        Returns:
            Fields, grounding, dropped values, status and timing.
        """
        return {
            "document_index": self.document_index,
            "party_id": self.party_id,
            "doc_type": self.doc_type,
            "file_name": self.file_name,
            "status": self.status,
            "fields": self.fields,
            "grounding": self.grounding,
            "dropped": self.dropped,
            "error": self.error,
            "ocr": self.ocr_stats,
            "elapsed_ms": self.elapsed_ms,
        }


def ground_fields(
    raw: ExtractedFields, text: str
) -> tuple[dict[str, str], dict[str, str], list[dict[str, str]]]:
    """Keep only the values that are found in the OCR text.

    Args:
        raw: The model's answer.
        text: The masked OCR text the answer was read from.

    Returns:
        (fields kept, how each was found, values dropped as NOT_IN_SOURCE).
    """
    source = Source.of(text)
    fields: dict[str, str] = {}
    grounding: dict[str, str] = {}
    dropped: list[dict[str, str]] = []
    for name in FIELDS:
        value = clean(getattr(raw, name))
        if value is None:
            continue
        how = ground(value, source)
        if how:
            fields[name], grounding[name] = value, how
        else:
            dropped.append({"field": name, "value": value, "reason": "NOT_IN_SOURCE"})
    return fields, grounding, dropped


class DocumentExtractor:
    """Reads identity fields from each document's OCR with a Strands Agent on Bedrock."""

    def __init__(
        self,
        settings: Settings,
        rules: dict[str, Any],
        prompts: PromptManager,
        models: BedrockModels,
    ) -> None:
        self._settings = settings
        self._hints: dict[str, list[str]] = rules["extraction"]["fields_by_doc_type"]
        self._prompts = prompts
        self._models = models

    @property
    def model_id(self) -> str:
        """Return the model used for extraction.

        Returns:
            The effective Bedrock model ID.
        """
        return self._models.model_id(self._prompts.config(PROMPT_NAME).llm.model_id)

    def prepare(self, index: int, doc: DocumentIn) -> DocumentExtraction:
        """Turn the OCR into masked text without calling the LLM.

        Args:
            index: Position of the document in the payload.
            doc: The document.

        Returns:
            The extraction record with ``masked_text`` and OCR statistics.
        """
        out = DocumentExtraction(index, doc.party_id, doc.doc_type, doc.file_name)
        try:
            text = ocr_to_text(
                doc.ocr,
                doc.raw_ocr,
                aadhaar_card=doc.doc_type == "AADHAAR",
                max_chars=self._settings.document_max_ocr_chars,
            )
        except OcrInputError as exc:
            out.status, out.error = "failed", f"OCR not readable: {exc}"
            return out
        out.masked_text = text.text
        out.ocr_stats = text.stats()
        return out

    def extract_one(self, index: int, doc: DocumentIn) -> DocumentExtraction:
        """Read one document.

        Args:
            index: Position of the document in the payload.
            doc: The document.

        Returns:
            The grounded fields, or a failed record (one document never stops the run).

        Raises:
            BedrockUnavailableError: If Bedrock refuses the call for a fatal reason.
        """
        started = time.perf_counter()
        out = self.prepare(index, doc)
        if out.status == "ok":
            cfg = self._prompts.config(PROMPT_NAME)
            hints = self._hints.get(doc.doc_type, self._hints["OTHER"])
            user = self._prompts.render_user(
                PROMPT_NAME,
                doc_type=doc.doc_type,
                expected_fields=", ".join(hints)
                or "any identity field that is printed",
                ocr_text=out.masked_text,
            )
            try:
                raw = extract_structured(
                    self._models.get(
                        cfg.llm.model_id, cfg.llm.temperature, cfg.llm.max_tokens
                    ),
                    system_prompt=self._prompts.render_system(PROMPT_NAME),
                    user_prompt=user,
                    schema=ExtractedFields,
                    name="anomaly_detection_extractor",
                )
                out.fields, out.grounding, out.dropped = ground_fields(
                    raw, out.masked_text
                )
            except BedrockUnavailableError:
                raise
            except MODEL_CALL_ERRORS as exc:
                logger.warning(
                    "extraction.document_failed",
                    document_index=index,
                    doc_type=doc.doc_type,
                    error_type=type(exc).__name__,
                )
                out.status, out.error = (
                    "failed",
                    f"Extraction failed ({type(exc).__name__}).",
                )
        out.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return out

    def extract_all(self, documents: list[DocumentIn]) -> list[DocumentExtraction]:
        """Read every document in parallel.

        Args:
            documents: All documents of the case.

        Returns:
            One extraction per document, in payload order.
        """
        workers = max(1, min(self._settings.extraction_workers, len(documents)))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="extract"
        ) as pool:
            return list(pool.map(self.extract_one, range(len(documents)), documents))
