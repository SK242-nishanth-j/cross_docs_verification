"""
File: case_service.py
Purpose: Lead storage and the trigger: lead + uploaded documents -> Orchestrator Agent -> stored result.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic

Every uploaded file and the JSON read from it are stored file by file under the
case (see the ``storage`` section of anomaly_config.json).
"""

import datetime as dt
import uuid
from typing import Any

from pydantic import ValidationError

from src.adapters.bedrock.client import BedrockUnavailableError
from src.adapters.kyc.models import PartyMockOverride
from src.adapters.storage.case_store import CaseStore
from src.ai.agents.anomaly_detection.agent import AGENT_NAME
from src.ai.agents.anomaly_detection.schemas import CaseInput
from src.ai.agents.anomaly_detection.schemas import DocumentIn
from src.ai.agents.orchestrator import OrchestratorAgent
from src.services.errors import AgentUnavailableError
from src.services.errors import CaseNotFoundError
from src.services.errors import InvalidCaseError
from src.services.errors import ResultNotFoundError
from src.services.models import Lead
from src.services.models import LeadRecord
from src.services.models import RunResult
from src.utils.logging.logger import get_logger

logger = get_logger(__name__)


def _now() -> str:
    """Return the current UTC time as ISO text."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class CaseService:
    """Creates leads and runs triggers."""

    def __init__(
        self,
        store: CaseStore,
        orchestrator: OrchestratorAgent,
        config: dict[str, Any],
    ) -> None:
        self._store = store
        self._orchestrator = orchestrator
        self._storage = config["storage"]

    def create_lead(self, case_id: str, lead: Lead) -> LeadRecord:
        """Store the reviewed lead; it becomes the base truth of the case.

        Args:
            case_id: The case.
            lead: The lead.

        Returns:
            The stored record.
        """
        record = LeadRecord(
            case_id=case_id, created_at=_now(), source="application_form", lead=lead
        )
        self._store.save_lead(case_id, record.model_dump(mode="json"))
        logger.info(
            "lead.created", case_id=case_id, co_applicants=len(lead.co_applicants)
        )
        return record

    def get_lead(self, case_id: str) -> LeadRecord:
        """Return the stored lead.

        Args:
            case_id: The case.

        Returns:
            The lead record.

        Raises:
            CaseNotFoundError: If no lead exists for the case.
        """
        record = self._store.get_lead(case_id)
        if record is None:
            raise CaseNotFoundError("lead not found for this case")
        return LeadRecord.model_validate(record)

    def get_result(self, case_id: str) -> RunResult:
        """Return the latest result.

        Args:
            case_id: The case.

        Returns:
            The run result.

        Raises:
            ResultNotFoundError: If the case has no result yet.
        """
        result = self._store.get_result(case_id)
        if result is None:
            raise ResultNotFoundError("no result yet for this case")
        return RunResult.model_validate(result)

    def _folder(self, party_id: str) -> str:
        """Storage folder of one person's documents."""
        return f"{self._storage['documents_dir']}/{party_id}"

    def _build_case(
        self,
        case_id: str,
        documents: list[DocumentIn],
        mock_overrides: dict[str, PartyMockOverride],
    ) -> CaseInput:
        """Combine the stored lead with the uploaded documents."""
        lead = self.get_lead(case_id).lead
        try:
            return CaseInput(
                case_id=case_id,
                lead=lead,
                documents=documents,
                mock_overrides=mock_overrides,
            )
        except ValidationError as exc:  # messages only, never the input values
            raise InvalidCaseError(
                "; ".join(e["msg"] for e in exc.errors(include_input=False))
            ) from None

    def _store_extracted(self, case_id: str, report: dict[str, Any]) -> None:
        """Store the JSON read from every document next to its file."""
        for item in report.get("extraction", []):
            path = self._store.save_extracted(
                case_id, self._folder(item["party_id"]), item["file_name"], item
            )
            item["extracted_json"] = path

    def trigger(
        self,
        case_id: str,
        documents: list[DocumentIn],
        mock_overrides: dict[str, PartyMockOverride],
    ) -> RunResult:
        """Run the Orchestrator Agent on the case.

        Args:
            case_id: The case.
            documents: Every uploaded document with its person and type.
            mock_overrides: Forced mock answers per person.

        Returns:
            The run result (also stored as the latest result).

        Raises:
            CaseNotFoundError: If no lead exists for the case.
            InvalidCaseError: If a document refers to a person not in the lead.
            AgentUnavailableError: If Bedrock refuses the calls.
        """
        case = self._build_case(case_id, documents, mock_overrides)
        if self._storage.get("keep_uploads"):
            for doc in case.documents:
                doc.stored_as = self._store.save_upload(
                    case_id, self._folder(doc.party_id), doc.file_name, doc.content
                )
        run_id = f"run-{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
        run: dict[str, Any] = {
            "run_id": run_id,
            "case_id": case_id,
            "status": "running",
            "started_at": _now(),
            "documents": [d.model_dump(mode="json") for d in case.documents],
            "mock_overrides": {
                k: v.model_dump(mode="json", exclude_none=True)
                for k, v in case.mock_overrides.items()
            },
        }
        logger.info(
            "trigger.started", case_id=case_id, run_id=run_id, documents=len(documents)
        )
        with self._store.lock(case_id):
            self._store.save_run(case_id, run_id, run)
            completed = False
            try:
                out = self._orchestrator.run(case)
                completed = True
            except BedrockUnavailableError as exc:
                run.update(status="failed", error=str(exc))
                raise AgentUnavailableError(str(exc)) from exc
            finally:
                if not completed:  # record the failure, then let it propagate
                    run.setdefault("error", "unexpected error")
                    run.update(status="failed", finished_at=_now())
                    self._store.save_run(case_id, run_id, run)
                    logger.error("trigger.failed", case_id=case_id, run_id=run_id)
            if self._storage.get("keep_extracted_json"):
                self._store_extracted(case_id, out["results"][AGENT_NAME])
            result = RunResult(
                run_id=run_id,
                case_id=case_id,
                status="completed",
                started_at=run["started_at"],
                finished_at=_now(),
                orchestrator=out["orchestrator"],
                results=out["results"],
            )
            run.update(status="completed", finished_at=result.finished_at)
            self._store.save_run(
                case_id, run_id, {**run, "result": result.model_dump(mode="json")}
            )
            self._store.save_result(case_id, result.model_dump(mode="json"))
        logger.info("trigger.completed", case_id=case_id, run_id=run_id)
        return result
