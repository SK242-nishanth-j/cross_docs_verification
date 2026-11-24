"""
File: orchestrator.py
Purpose: Orchestrator Agent (Strands, Bedrock LLM) that calls the specialist agents as tools.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: strands-agents

If the LLM does not call the tool, or tool calling fails for a non-credential
reason, the orchestrator calls the specialist agent directly, so a trigger always
produces a result.
"""

from typing import Any

from strands import Agent

from src.adapters.bedrock.client import MODEL_CALL_ERRORS
from src.adapters.bedrock.client import BedrockModels
from src.adapters.bedrock.client import BedrockUnavailableError
from src.adapters.bedrock.client import find_fatal
from src.ai.agents.anomaly_detection.agent import AGENT_NAME
from src.ai.agents.anomaly_detection.agent import get_anomaly_agent
from src.ai.agents.anomaly_detection.report import compact_summary
from src.ai.agents.anomaly_detection.schemas import CaseInput
from src.ai.prompts.manager import PromptManager
from src.ai.tools.anomaly_detection_tool import anomaly_detection_agent
from src.utils.logging.logger import get_logger

logger = get_logger(__name__)

PROMPT_NAME = "orchestrator"
TOOLS: list[Any] = [anomaly_detection_agent]


def _template_summary(s: dict[str, Any]) -> str:
    """Write the summary without the LLM (fallback)."""
    counts = s["summary"]["counts"]
    parts = [
        f"Overall {s['summary']['overall_color']}: {counts['red']} mismatch, "
        f"{counts['yellow']} review, {counts['green']} match, {counts['grey']} not checked."
    ]
    if s["top_anomalies"]:
        top = "; ".join(
            f"{a['party_id']} {a['title']} ({a['color']})"
            for a in s["top_anomalies"][:5]
        )
        parts.append(f"Top anomalies: {top}.")
    if s["sanction_conditions"]:
        parts.append(
            "Sanction conditions: "
            + "; ".join(c["condition"] for c in s["sanction_conditions"])
            + "."
        )
    if s["cm_justifications"]:
        who = ", ".join(
            f"{c['party_id']} {c['rule_id']}" for c in s["cm_justifications"]
        )
        parts.append(f"CM justification required for: {who}.")
    return " ".join(parts)


def _text_of(message: Any) -> str | None:
    """Join the text blocks of the agent's final message."""
    content = (message or {}).get("content", [])
    text = "".join(
        block.get("text", "") for block in content if "text" in block
    ).strip()
    return text or None


class OrchestratorAgent:
    """Calls the specialist agents for a case and writes the summary for the CM."""

    def __init__(self, prompts: PromptManager, models: BedrockModels) -> None:
        self._prompts = prompts
        self._models = models

    def run(self, case: CaseInput) -> dict[str, Any]:
        """Run the orchestration of one case.

        Args:
            case: The case input.

        Returns:
            ``{"orchestrator": trace and summary, "results": {agent: report}}``.

        Raises:
            BedrockUnavailableError: If Bedrock refuses the calls for a fatal reason.
        """
        cfg = self._prompts.config(PROMPT_NAME)
        state: dict[str, Any] = {"case": case, "results": {}}
        trace: dict[str, Any] = {"mode": "agent", "tools_called": [], "fallback": False}
        summary: str | None = None
        try:
            agent = Agent(
                model=self._models.get(
                    cfg.llm.model_id, cfg.llm.temperature, cfg.llm.max_tokens
                ),
                system_prompt=self._prompts.render_system(PROMPT_NAME),
                tools=TOOLS,
                callback_handler=None,
                name="orchestrator",
            )
            result = agent(
                self._prompts.render_user(PROMPT_NAME, case_id=case.case_id),
                invocation_state=state,
            )
            summary = _text_of(result.message)
            trace["stop_reason"] = str(result.stop_reason)
        except BedrockUnavailableError:
            raise
        except MODEL_CALL_ERRORS as exc:
            fatal = find_fatal(exc)
            if fatal:
                raise BedrockUnavailableError(fatal) from exc
            logger.warning(
                "orchestrator.agent_failed",
                case_id=case.case_id,
                error_type=type(exc).__name__,
            )
            trace["error"] = type(exc).__name__

        results: dict[str, Any] = state["results"]
        if AGENT_NAME in results:
            trace["tools_called"].append(AGENT_NAME)
        else:  # the LLM did not call the tool: its text is not based on results, so drop it
            trace["fallback"] = True
            logger.warning(
                "orchestrator.fallback", case_id=case.case_id, tool=AGENT_NAME
            )
            results[AGENT_NAME] = get_anomaly_agent().run(case)
            summary = None
        trace["summary_source"] = "llm" if summary else "template"
        trace["summary"] = summary or _template_summary(
            compact_summary(results[AGENT_NAME])
        )
        trace["model_id"] = self._models.model_id(cfg.llm.model_id)
        trace["prompt_version"] = cfg.version
        return {"orchestrator": trace, "results": results}
