"""
File: anomaly_detection_tool.py
Purpose: The Anomaly Detection Agent as a Strands @tool for the Orchestrator Agent (with audit logs).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: strands-agents

The case payload travels in ``invocation_state``; the LLM only passes the case_id
and only sees a compact summary, never document text.
"""

import time
from typing import Any

from strands import ToolContext
from strands import tool

from src.ai.agents.anomaly_detection.agent import AGENT_NAME
from src.ai.agents.anomaly_detection.agent import get_anomaly_agent
from src.ai.agents.anomaly_detection.report import compact_summary
from src.ai.agents.anomaly_detection.schemas import CaseInput
from src.utils.logging.logger import get_logger

logger = get_logger(__name__)


@tool(
    name="anomaly_detection_agent",
    description=(
        "Runs the Anomaly Detection Agent (KYC & identity cross-verification) for one "
        "case: reads every document, compares name, DOB, father's and mother's names, "
        "address and ID numbers across the lead, all documents and the bureau, then "
        "runs the mocked third-party checks (bureau address, PAN-Aadhaar link, Voter "
        "ID / DL, email, face match). Returns a short summary; the full report is kept "
        "by the system."
    ),
    context=True,
)
def anomaly_detection_agent(
    case_id: str, tool_context: ToolContext[Any]
) -> dict[str, Any]:
    """Run the Anomaly Detection Agent for the case that triggered this orchestration.

    Args:
        case_id: The case ID of the current trigger.
        tool_context: Strands tool context; ``invocation_state`` holds the case.

    Returns:
        The compact summary, or an error when the case_id is not this run's case.
    """
    state = tool_context.invocation_state
    case: CaseInput | None = state.get("case")
    logger.info("tool.call", tool=AGENT_NAME, case_id=case_id)
    if case is None or case.case_id != case_id:
        logger.warning("tool.rejected", tool=AGENT_NAME, reason="unknown case_id")
        return {"error": "unknown case_id for this run"}
    results: dict[str, Any] = state.setdefault("results", {})
    started = time.perf_counter()
    if AGENT_NAME not in results:  # one run per trigger, even if the LLM calls twice
        results[AGENT_NAME] = get_anomaly_agent().run(case)
    summary = compact_summary(results[AGENT_NAME])
    logger.info(
        "tool.result",
        tool=AGENT_NAME,
        case_id=case_id,
        overall=summary["summary"]["overall_color"],
        counts=summary["summary"]["counts"],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return summary
