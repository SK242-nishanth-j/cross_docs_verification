"""
File: agent.py
Purpose: Anomaly Detection Agent (KYC & identity): LLM extraction, all-pairs cross_verify, KYC checks.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: strands-agents

One run:
  1. OCR of every document -> text, Aadhaar masked.
  2. LLM extraction per document + grounding against the OCR text.
  3. Parties in check order; relationships come from the lead.
  4. Mocked bureau report per party (its name / DOB join the KY-01 pairs).
  5. All-pairs cross-verification with cross_verify (this package); the lead is a source.
  6. Third-party checks KY-02..KY-06 (mocked).
  7. One report.
"""

import datetime as dt
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.adapters.bedrock.client import BedrockModels
from src.adapters.kyc.base import KycProvider
from src.adapters.kyc.mock_provider import MockKycProvider
from src.ai.agents.anomaly_detection import cross_verify
from src.ai.agents.anomaly_detection.extraction import PROMPT_NAME
from src.ai.agents.anomaly_detection.extraction import DocumentExtractor
from src.ai.agents.anomaly_detection.groups import build_groups
from src.ai.agents.anomaly_detection.kyc_rules import evaluate_kyc_rules
from src.ai.agents.anomaly_detection.pairs import evaluate_groups
from src.ai.agents.anomaly_detection.parties import party_context
from src.ai.agents.anomaly_detection.parties import resolve_parties
from src.ai.agents.anomaly_detection.report import build_report
from src.ai.agents.anomaly_detection.schemas import CaseInput
from src.ai.prompts.manager import get_prompt_manager
from src.config.settings import Settings
from src.config.settings import get_settings
from src.utils.logging.logger import get_logger

logger = get_logger(__name__)

AGENT_NAME = "anomaly_detection"
AGENT_VERSION = "0.3.0"


def load_rules(path: Path) -> dict[str, Any]:
    """Read the anomaly rules configuration.

    Args:
        path: Path to ``anomaly_rules.json``.

    Returns:
        The configuration mapping.
    """
    rules: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return rules


class AnomalyDetectionAgent:
    """KYC & identity anomaly detection for one case."""

    def __init__(
        self,
        settings: Settings,
        *,
        extractor: DocumentExtractor | None = None,
        provider: KycProvider | None = None,
        today: dt.date | None = None,
    ) -> None:
        self._rules = load_rules(settings.anomaly_rules_path)
        self._cv_config = cross_verify.load_config(settings.cross_verify_config_path)
        self._verify = cross_verify.create_verifier(
            config_path=settings.cross_verify_config_path
        )
        self.extractor = extractor or DocumentExtractor(
            settings, self._rules, get_prompt_manager(), BedrockModels(settings)
        )
        self._provider = provider or MockKycProvider(
            self._rules["mock_defaults"], today
        )
        self._today = today

    def run(self, case: CaseInput) -> dict[str, Any]:
        """Run every check of one case.

        Args:
            case: Lead (base truth), documents and mock overrides.

        Returns:
            The full report.

        Raises:
            BedrockUnavailableError: If Bedrock refuses the extraction calls.
        """
        started = time.perf_counter()
        today = self._today or dt.date.today()
        extractions = self.extractor.extract_all(case.documents)
        extracted_at = time.perf_counter()

        parties = resolve_parties(case, extractions)
        bureau = {
            p.party_id: self._provider.bureau_report(party_context(p, case))
            for p in parties
        }
        groups = build_groups(parties, bureau, self._rules)
        limit = int(self._cv_config["limits"]["max_checks"])
        cross, single, engine = evaluate_groups(
            groups, self._verify, self._rules, today, limit
        )
        third_party = evaluate_kyc_rules(
            parties, bureau, self._provider, self._verify, case, self._rules, today
        )
        report = build_report(
            case_id=case.case_id,
            parties=parties,
            cross=cross,
            third_party=third_party,
            single=single,
            extractions=extractions,
            config={
                "agent_version": AGENT_VERSION,
                "rules_label": self._rules.get("config_label"),
                "cross_verify": engine,
                "llm_model_id": self.extractor.model_id,
                "prompt": PROMPT_NAME,
                "third_party_provider": self._provider.name,
                "third_party_is_mock": self._provider.is_mock,
            },
        )
        report["timing_ms"] = {
            "extraction": int((extracted_at - started) * 1000),
            "total": int((time.perf_counter() - started) * 1000),
        }
        logger.info(
            "anomaly_detection.completed",
            case_id=case.case_id,
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
