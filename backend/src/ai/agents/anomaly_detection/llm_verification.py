"""
File: llm_verification.py
Purpose: Full-LLM modes: one call per person reads every document and cross-verifies every check.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic, strands-agents

The checks are the same groups cross_verify gets (groups.py); the prompt carries the
cross_verify reason codes and rules. The LLM compares every source of a check with
its base (the first known value). Vision calls with more images than Bedrock takes
in one call are split by document.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from strands.types.content import ContentBlock

from src.adapters.bedrock.client import BedrockModels
from src.adapters.bedrock.client import extract_structured
from src.ai.agents.anomaly_detection.comparison import Finding
from src.ai.agents.anomaly_detection.comparison import group_finding
from src.ai.agents.anomaly_detection.extraction import clean_fields
from src.ai.agents.anomaly_detection.extraction import document_text
from src.ai.agents.anomaly_detection.schemas import DocumentExtraction
from src.ai.agents.anomaly_detection.schemas import DocumentIn
from src.ai.agents.anomaly_detection.schemas import LlmComparison
from src.ai.agents.anomaly_detection.schemas import PersonAnswer
from src.ai.agents.anomaly_detection.schemas import check_type
from src.ai.agents.anomaly_detection.sources import Group
from src.ai.agents.anomaly_detection.sources import Party
from src.ai.agents.anomaly_detection.sources import Src
from src.ai.agents.anomaly_detection.sources import doc_source
from src.ai.prompts.manager import PromptManager
from src.config.settings import Settings
from src.utils.images import UnreadableFileError
from src.utils.images import to_blocks
from src.utils.logging.logger import get_logger
from src.utils.ocr_text import OcrInputError

logger = get_logger(__name__)

_STATUS = {
    "green": "match",
    "yellow": "warning",
    "red": "mismatch",
    "grey": "not_evaluated",
}


class LlmVerifier:
    """Runs the full-LLM modes (vision_llm on images / PDF, ocr_llm on OCR text)."""

    def __init__(
        self,
        settings: Settings,
        config: dict[str, Any],
        prompts: PromptManager,
        models: BedrockModels,
        rules: dict[str, Any],
    ) -> None:
        self._settings = settings
        self._config = config
        self._mode = str(config["mode"])
        self._prompt = str(config["modes"][self._mode]["verification_prompt"])
        self._prompts = prompts
        self._models = models
        self._rules = rules  # cross_verify config and reason codes for the prompt

    @property
    def model_id(self) -> str:
        """Return the model used for the full-LLM calls.

        Returns:
            The effective Bedrock model ID.
        """
        return self._models.model_id(self._prompts.config(self._prompt).llm.model_id)

    def _document_input(
        self, key: str, doc: DocumentIn
    ) -> tuple[dict[str, Any], list[ContentBlock]]:
        """Describe one document for the prompt; images come back as blocks."""
        hints = self._config["fields_by_doc_type"]
        item: dict[str, Any] = {
            "key": key,
            "file_name": doc.file_name,
            "doc_type": doc.doc_type,
            "expected_fields": ", ".join(hints.get(doc.doc_type, hints["OTHER"])),
            "ocr_text": None,
        }
        if self._mode == "vision_llm":
            return item, to_blocks(doc.content, self._config["vision"])
        item["ocr_text"] = document_text(
            doc, self._settings.document_max_ocr_chars
        ).text
        return item, []

    def _batches(
        self, docs: list[tuple[int, DocumentIn]]
    ) -> tuple[
        list[list[tuple[int, DocumentIn, dict[str, Any], list[ContentBlock]]]],
        dict[int, str],
    ]:
        """Prepare every document and split them so each call stays under the image limit."""
        limit = int(self._config["vision"]["max_images_per_call"])
        batches: list[list[Any]] = [[]]
        errors: dict[int, str] = {}
        used = 0
        for n, (index, doc) in enumerate(docs, start=1):
            try:
                item, blocks = self._document_input(f"d{n}", doc)
            except (UnreadableFileError, OcrInputError, ValueError) as exc:
                errors[index] = f"File not readable: {exc}"
                continue
            if batches[-1] and used + len(blocks) > limit:
                batches.append([])
                used = 0
            batches[-1].append((index, doc, item, blocks))
            used += len(blocks)
        return [b for b in batches if b], errors

    def _check_inputs(self, groups: list[Group], party: Party) -> list[dict[str, Any]]:
        """Describe the checks of one person: known values and which document field to read."""
        out = []
        for g in groups:
            reads = [r for r in g.doc_reads if r.party_id == party.party_id]
            if not reads and len(g.sources) < 2:
                continue
            types = sorted({t for r in reads for t in (r.doc_types or ())})
            out.append(
                {
                    "check_id": g.group_id,
                    "title": g.title,
                    "field_type": check_type(g.field_type),
                    "doc_field": reads[0].attr if reads else None,
                    "doc_types": types,
                    "known": [
                        {"key": f"k{n}", "label": s.label, "value": s.value}
                        for n, s in enumerate(g.sources, start=1)
                    ],
                }
            )
        return out

    def _call(
        self,
        party: Party,
        batch: list[tuple[int, DocumentIn, dict[str, Any], list[ContentBlock]]],
        checks: list[dict[str, Any]],
    ) -> PersonAnswer:
        """Make one LLM call for one batch of a person's documents."""
        cfg = self._prompts.config(self._prompt)
        vision = self._mode == "vision_llm"
        attachments: list[ContentBlock] = []
        documents = []
        for _, _, item, blocks in batch:
            first = len(attachments) + 1
            attachments += blocks
            documents.append({**item, "images": f"{first}-{len(attachments)}"})
        return extract_structured(
            self._models.get(cfg.llm.model_id, cfg.llm.temperature, cfg.llm.max_tokens),
            system_prompt=self._prompts.render_system(
                self._prompt,
                vision=vision,
                cv=self._rules["config"],
                reason_codes=self._rules["codes"],
            ),
            user_prompt=self._prompts.render_user(
                self._prompt,
                vision=vision,
                party_label=party.label,
                documents=documents,
                checks=checks,
            ),
            schema=PersonAnswer,
            name="anomaly_detection_verifier",
            attachments=attachments if vision else None,
        )

    def verify_person(
        self, party: Party, docs: list[tuple[int, DocumentIn]], groups: list[Group]
    ) -> tuple[list[DocumentExtraction], dict[str, dict[str, LlmComparison]]]:
        """Read and cross-verify every document of one person.

        Args:
            party: The person.
            docs: The person's documents with their position in the case.
            groups: The person's groups (lead and bureau values only).

        Returns:
            (the extraction of every document, check_id -> source key -> comparison).

        Raises:
            BedrockUnavailableError: If Bedrock refuses the call for a fatal reason.
        """
        started = time.perf_counter()
        checks = self._check_inputs(groups, party)
        batches, errors = self._batches(docs)
        extractions: dict[int, DocumentExtraction] = {}
        comparisons: dict[str, dict[str, LlmComparison]] = {}
        for batch in batches or [[]]:
            answer = self._call(party, batch, checks)
            by_key = {d.document: d.fields for d in answer.documents}
            for index, doc, item, _ in batch:
                out = DocumentExtraction(
                    index, doc.party_id, doc.doc_type, doc.file_name, "llm"
                )
                out.stored_as = doc.stored_as
                fields = by_key.get(item["key"])
                if fields is None:
                    out.status, out.error = (
                        "failed",
                        "The LLM did not return this document.",
                    )
                else:
                    out.fields = clean_fields(doc.doc_type, fields.model_dump())
                extractions[index] = out
                # document keys are per call: store them by position in the case
                for c in answer.checks:
                    for comp in c.comparisons:
                        if comp.source == item["key"]:
                            comparisons.setdefault(c.check_id, {})[f"doc{index}"] = comp
            for (
                c
            ) in answer.checks:  # known values: the first batch that compares them wins
                for comp in c.comparisons:
                    if comp.source.startswith("k"):
                        comparisons.setdefault(c.check_id, {}).setdefault(
                            comp.source, comp
                        )
        for index, doc in docs:
            if index in errors:
                failed = DocumentExtraction(
                    index, doc.party_id, doc.doc_type, doc.file_name, "llm", "failed"
                )
                failed.error, failed.stored_as = errors[index], doc.stored_as
                extractions[index] = failed
        elapsed = int((time.perf_counter() - started) * 1000)
        for e in extractions.values():
            e.elapsed_ms = elapsed
        logger.info(
            "llm_verification.person_done",
            party_id=party.party_id,
            documents=len(docs),
            calls=len(batches),
            elapsed_ms=elapsed,
        )
        return [extractions[i] for i, _ in docs], comparisons

    def verify(
        self, documents: list[DocumentIn], parties: list[Party], groups: list[Group]
    ) -> tuple[list[DocumentExtraction], dict[str, dict[str, LlmComparison]]]:
        """Run one person after the other in parallel threads.

        Args:
            documents: Every document of the case.
            parties: The people in check order.
            groups: Every group, built with lead and bureau values only.

        Returns:
            (every extraction in upload order, every check's comparisons).
        """
        work = [
            (
                p,
                [(i, d) for i, d in enumerate(documents) if d.party_id == p.party_id],
                [g for g in groups if g.party_id == p.party_id],
            )
            for p in parties
        ]
        workers = max(1, min(self._settings.extraction_workers, len(work)))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="verify"
        ) as pool:
            results = list(pool.map(lambda w: self.verify_person(*w), work))
        extractions = sorted(
            (e for found, _ in results for e in found), key=lambda e: e.document_index
        )
        comparisons: dict[str, dict[str, LlmComparison]] = {}
        for _, found in results:
            comparisons.update(found)
        return extractions, comparisons


def llm_findings(
    groups: list[Group],
    comparisons: dict[str, dict[str, LlmComparison]],
    reasons: dict[str, str],
    config: dict[str, Any],
) -> list[Finding]:
    """Turn the LLM comparisons into findings with the same shape as cross_verify's.

    Args:
        groups: Every group, rebuilt with the documents' values.
        comparisons: check_id -> source key (``k1`` ... or ``doc<index>``) -> comparison.
        reasons: cross_verify ``REASONS`` (code -> severity), for display.
        config: The anomaly configuration.

    Returns:
        One finding per group with two or more sources.
    """
    findings = []
    for g in groups:
        if len(g.sources) < 2:
            continue
        mine = comparisons.get(g.group_id, {})
        base = g.sources[0]
        pairs = []
        for n, src in enumerate(g.sources[1:], start=2):
            key = (
                f"doc{src.meta['document_index']}"
                if src.kind == "document"
                else f"k{n}"
            )
            comp = mine.get(key)
            color = comp.color if comp else "grey"
            pair_reasons = (
                [
                    {
                        "code": r.code,
                        "severity": reasons.get(r.code, "warn"),
                        "message": r.message,
                    }
                    for r in comp.reasons
                ]
                if comp
                else [
                    {
                        "code": "NOT_COMPARED",
                        "severity": "warn",
                        "message": "The LLM gave no comparison for this source.",
                    }
                ]
            )
            pairs.append(
                {
                    "a": base.key,
                    "b": src.key,
                    "status": _STATUS[color],
                    "color": color,
                    "reasons": pair_reasons,
                    "highlight": {"a": [], "b": []},
                }
            )
        findings.append(group_finding(g, pairs, config))
    return findings


def add_document_sources(groups: list[Group], parties: list[Party]) -> None:
    """Add the values the LLM read to each group (the person's own documents only).

    Args:
        groups: Groups built with lead and bureau values only.
        parties: The people, with their extractions attached.
    """
    by_id = {p.party_id: p for p in parties}
    for g in groups:
        extra: list[Src] = []
        for read in g.doc_reads:
            if read.party_id != g.party_id:
                continue  # the applicant's documents are compared in the applicant's checks
            for e in by_id[read.party_id].readable():
                value = e.get(read.attr)
                if value and (read.doc_types is None or e.doc_type in read.doc_types):
                    extra.append(doc_source(e, value, read.side, read.who))
        g.sources = [*g.sources, *extra]
        for n, src in enumerate(g.sources):
            src.key = f"s{n}"
