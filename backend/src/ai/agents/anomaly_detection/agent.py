"""
File: agent.py
Purpose: Anomaly Detection Agent (KYC & identity): runs the configured mode and builds one report.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: strands-agents

Every mode builds the same groups (groups.py) and the same report:
  structured  structured JSON -> fields in code ------------> cross_verify compares
  ocr_hybrid  OCR -> LLM reads each document (grounded) ----> cross_verify compares
  ocr_llm     OCR -> one LLM call per person reads and compares
  vision_llm  images / PDF -> one vision LLM call per person reads and compares
Then the mocked third-party checks run, and the report holds the checklist, the
per-person findings, the truth table and the JSON read from every document.
"""

import datetime as dt
import json
import time
from functools import lru_cache
from typing import Any

from src.adapters.bedrock.client import BedrockModels
from src.adapters.kyc.base import KycProvider
from src.adapters.kyc.mock_provider import MockKycProvider
from src.adapters.kyc.models import BureauReport
from src.ai.agents.anomaly_detection import cross_verify
from src.ai.agents.anomaly_detection.comparison import COLOR_STATUS
from src.ai.agents.anomaly_detection.comparison import evaluate_groups
from src.ai.agents.anomaly_detection.comparison import not_compared
from src.ai.agents.anomaly_detection.comparison import run_cross_verify
from src.ai.agents.anomaly_detection.cross_verify.common import REASONS
from src.ai.agents.anomaly_detection.extraction import DocumentExtractor
from src.ai.agents.anomaly_detection.groups import build_groups
from src.ai.agents.anomaly_detection.llm_verification import LlmVerifier
from src.ai.agents.anomaly_detection.llm_verification import add_document_sources
from src.ai.agents.anomaly_detection.llm_verification import llm_findings
from src.ai.agents.anomaly_detection.report import build_report
from src.ai.agents.anomaly_detection.schemas import CaseInput
from src.ai.agents.anomaly_detection.schemas import DocumentExtraction
from src.ai.agents.anomaly_detection.schemas import LlmComparison
from src.ai.agents.anomaly_detection.schemas import reason_codes
from src.ai.agents.anomaly_detection.sources import Group
from src.ai.agents.anomaly_detection.sources import Party
from src.ai.agents.anomaly_detection.sources import Src
from src.ai.agents.anomaly_detection.sources import attach_extractions
from src.ai.agents.anomaly_detection.sources import party_context
from src.ai.agents.anomaly_detection.sources import resolve_parties
from src.ai.agents.anomaly_detection.structured_input import read_documents
from src.ai.agents.anomaly_detection.third_party import AddressCompare
from src.ai.agents.anomaly_detection.third_party import evaluate_third_party
from src.ai.agents.anomaly_detection.third_party import recent_addresses
from src.ai.prompts.manager import PromptManager
from src.ai.prompts.manager import get_prompt_manager
from src.config.settings import Settings
from src.config.settings import get_anomaly_config
from src.config.settings import get_settings
from src.config.settings import get_structured_mapping
from src.utils.logging.logger import get_logger

logger = get_logger(__name__)

AGENT_NAME = "anomaly_detection"
AGENT_VERSION = "0.4.0"
LLM_MODES = ("vision_llm", "ocr_llm")
_NOT_COMPARED: dict[str, Any] = {
    "status": "not_evaluated",
    "color": "grey",
    "reasons": [],
    "highlight": {"base": [], "candidate": []},
}


def _bureau_groups(
    parties: list[Party],
    bureau: dict[str, BureauReport],
    config: dict[str, Any],
    today: dt.date,
) -> list[Group]:
    """Lead address vs the recent bureau addresses, for the LLM to compare."""
    months = int(config["third_party"]["bureau_address_window_months"])
    out = []
    for p in parties:
        recent = recent_addresses(bureau[p.party_id], months, today)
        if not p.lead.address or not recent:
            continue
        sources = [
            Src(
                "",
                "lead",
                f"Lead · {p.label} · address",
                p.lead.address,
                p.party_id,
                "self",
            )
        ] + [
            Src("", "bureau", f"Bureau address {n}", a.address, p.party_id, "self")
            for n, a in enumerate(recent, start=1)
        ]
        out.append(
            Group(
                f"{p.party_id}.BUREAU_ADDRESS",
                p.party_id,
                "BUREAU_ADDRESS",
                "address",
                "Lead address vs bureau addresses",
                sources,
            )
        )
    return out


class AnomalyDetectionAgent:
    """KYC & identity anomaly detection for one case, in the configured mode."""

    def __init__(
        self,
        settings: Settings,
        *,
        config: dict[str, Any] | None = None,
        prompts: PromptManager | None = None,
        models: BedrockModels | None = None,
        provider: KycProvider | None = None,
        today: dt.date | None = None,
    ) -> None:
        self._settings = settings
        self._config = config or get_anomaly_config()
        self.mode = str(self._config["mode"])
        cv_path = settings.cross_verify_config_path
        self._cv_config: dict[str, Any] = json.loads(
            cv_path.read_text(encoding="utf-8")
        )
        self._verify = cross_verify.create_verifier(config_path=cv_path)
        overrides = self._cv_config.get("severity_overrides") or {}
        self._severity = {c: overrides.get(c, s) for c, s in REASONS.items()}
        prompts = prompts or get_prompt_manager()
        models = models or BedrockModels(settings)
        self.extractor = (
            DocumentExtractor(settings, self._config, prompts, models)
            if self.mode == "ocr_hybrid"
            else None
        )
        self.verifier = (
            LlmVerifier(
                settings,
                self._config,
                prompts,
                models,
                {"config": self._cv_config, "codes": reason_codes(REASONS, overrides)},
            )
            if self.mode in LLM_MODES
            else None
        )
        self._provider = provider or MockKycProvider(
            self._config["third_party"]["mock_defaults"], today
        )
        self._today = today

    @property
    def model_id(self) -> str | None:
        """Return the LLM the documents go to, or None in the structured mode.

        Returns:
            The effective Bedrock model ID, or None.
        """
        if self.verifier:
            return self.verifier.model_id
        return self.extractor.model_id if self.extractor else None

    def _cross_verify_address(self, today: dt.date) -> AddressCompare:
        """Compare a lead address with bureau addresses using cross_verify."""

        def compare(address: str, others: list[str], _: str) -> list[dict[str, Any]]:
            check = {
                "field": "bureau",
                "type": "address",
                "base": address,
                "candidates": [
                    {"source": f"b{n}", "value": v} for n, v in enumerate(others)
                ],
            }
            fields = run_cross_verify(self._verify, [check], today, 1)["fields"]
            return [
                {k: c[k] for k in ("status", "color", "reasons", "highlight")}
                for c in fields["bureau"]["comparisons"]
            ]

        return compare

    def _llm_address(
        self, comps: dict[str, dict[str, LlmComparison]]
    ) -> AddressCompare:
        """Use the LLM's comparisons of the lead address with the bureau addresses."""

        def compare(_: str, others: list[str], party_id: str) -> list[dict[str, Any]]:
            mine = comps.get(f"{party_id}.BUREAU_ADDRESS", {})
            out: list[dict[str, Any]] = []
            for n in range(2, len(others) + 2):
                c = mine.get(f"k{n}")
                if c is None:
                    out.append(dict(_NOT_COMPARED))
                    continue
                out.append(
                    {
                        "status": COLOR_STATUS[c.color],
                        "color": c.color,
                        "reasons": [
                            {
                                "code": r.code,
                                "severity": self._severity.get(r.code, "warn"),
                                "message": r.message,
                            }
                            for r in c.reasons
                        ],
                        "highlight": {"base": [], "candidate": []},
                    }
                )
            return out

        return compare

    def run(self, case: CaseInput) -> dict[str, Any]:
        """Run every check of one case in the configured mode.

        Args:
            case: Lead (base truth), documents and mock overrides.

        Returns:
            The full report.

        Raises:
            BedrockUnavailableError: If Bedrock refuses the LLM calls.
        """
        started = time.perf_counter()
        today = self._today or dt.date.today()
        parties = resolve_parties(case)
        bureau = {
            p.party_id: self._provider.bureau_report(party_context(p, case))
            for p in parties
        }
        engine: dict[str, Any] = {
            "agent_version": AGENT_VERSION,
            "mode": self.mode,
            "config_label": self._config.get("config_label"),
            "llm_model_id": self.model_id,
            "third_party_provider": self._provider.name,
            "third_party_is_mock": self._provider.is_mock,
        }
        if self.verifier:
            # Placeholders tell groups.py which document types exist (passport vs DL).
            attach_extractions(
                parties,
                [
                    DocumentExtraction(i, d.party_id, d.doc_type, d.file_name, "llm")
                    for i, d in enumerate(case.documents)
                ],
            )
            groups = build_groups(parties, bureau, self._config)
            asked = groups + _bureau_groups(parties, bureau, self._config, today)
            extractions, comps = self.verifier.verify(case.documents, parties, asked)
            for p in parties:
                p.extractions = []
            attach_extractions(parties, extractions)
            add_document_sources(groups, parties)
            cross = llm_findings(groups, comps, self._severity, self._config)
            compare = self._llm_address(comps)
            engine["compared_by"] = "llm"
        else:
            if self.extractor:
                extractions = self.extractor.extract_all(case.documents)
            else:
                extractions = read_documents(
                    case.documents,
                    get_structured_mapping()["documents"],
                    {p.party_id for p in parties},
                )
            attach_extractions(
                parties,
                [e for e in extractions if e.party_id in {p.party_id for p in parties}],
            )
            groups = build_groups(parties, bureau, self._config)
            limit = int(self._cv_config["limits"]["max_checks"])
            cross, engine["cross_verify"] = evaluate_groups(
                groups, self._verify, self._config, today, limit
            )
            compare = self._cross_verify_address(today)
            engine["compared_by"] = "cross_verify"
        extracted_at = time.perf_counter()
        third = evaluate_third_party(
            parties, bureau, self._provider, compare, case, self._config, today
        )
        report = build_report(
            case_id=case.case_id,
            mode=self.mode,
            parties=parties,
            cross=cross,
            third_party=third,
            single=not_compared(groups),
            extractions=extractions,
            config=self._config,
            engine=engine,
        )
        report["timing_ms"] = {
            "documents": int((extracted_at - started) * 1000),
            "total": int((time.perf_counter() - started) * 1000),
        }
        logger.info(
            "anomaly_detection.completed",
            case_id=case.case_id,
            mode=self.mode,
            documents=len(case.documents),
            overall=report["summary"]["overall_color"],
            counts=report["summary"]["counts"],
            total_ms=report["timing_ms"]["total"],
        )
        return report


@lru_cache(maxsize=1)
def get_anomaly_agent() -> AnomalyDetectionAgent:
    """Return the process-wide Anomaly Detection Agent.

    Returns:
        The cached agent.
    """
    return AnomalyDetectionAgent(get_settings())
