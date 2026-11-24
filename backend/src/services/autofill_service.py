"""
File: autofill_service.py
Purpose: Application form -> lead fields for review, in the configured mode; stores the file and its JSON.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic, strands-agents

structured  key-value JSON -> lead through structured_mapping.json (no LLM)
vision_llm  page images / PDF -> vision LLM
ocr_*       OCR JSON or text -> LLM; every value must be found in the OCR text
"""

import datetime as dt
import json
import re
import time
import uuid
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from src.adapters.bedrock.client import BedrockModels
from src.adapters.bedrock.client import BedrockUnavailableError
from src.adapters.bedrock.client import extract_structured
from src.adapters.storage.case_store import CaseStore
from src.ai.agents.anomaly_detection.structured_input import application_form_lead
from src.ai.evaluators.grounding import Source
from src.ai.evaluators.grounding import clean
from src.ai.evaluators.grounding import ground
from src.ai.prompts.manager import PromptManager
from src.config.settings import Settings
from src.config.settings import get_structured_mapping
from src.services.errors import AgentUnavailableError
from src.services.errors import InvalidInputError
from src.services.models import CASE_ID_PATTERN
from src.services.models import AutofillResponse
from src.services.models import DroppedValue
from src.services.models import normalize_relationship
from src.utils.images import UnreadableFileError
from src.utils.images import to_blocks
from src.utils.logging.logger import get_logger
from src.utils.ocr_text import OcrInputError
from src.utils.ocr_text import ocr_to_text

logger = get_logger(__name__)

_COPY = "Copy exactly as printed. null if not printed."
# Anonymisation tags such as {NAME}, {PHONE}, {US_BANK_ACCOUNT_NUMBER}.
_MASK_TAG = re.compile(r"\{[A-Z][A-Z0-9_]*\}")
_CASE_ID = re.compile(CASE_ID_PATTERN)


class FormPerson(BaseModel):
    """Fields of one person on the application form."""

    model_config = ConfigDict(extra="ignore")
    name: str | None = Field(
        None,
        description="FULL name: First, Middle, Last joined with spaces. " + _COPY,
    )
    father_name: str | None = Field(
        None, description="'Father/ Spouse Name', boxes joined. " + _COPY
    )
    mother_name: str | None = Field(
        None, description="Mother's name, boxes joined. " + _COPY
    )
    dob: str | None = Field(None, description="Date of birth. " + _COPY)
    gender: str | None = Field(None, description=_COPY)
    address: str | None = Field(
        None,
        description="Current address: line, landmark, city, state, "
        "pincode, country joined with ', '. " + _COPY,
    )
    permanent_address: str | None = Field(
        None, description="Permanent address, same format. " + _COPY
    )
    mobile: str | None = Field(None, description=_COPY)
    email: str | None = Field(None, description=_COPY)
    pan: str | None = Field(None, description="PAN No. " + _COPY)
    aadhaar_last4: str | None = Field(
        None, description="Only the last 4 digits printed after 'Aadhar No'."
    )
    passport_or_dl_number: str | None = Field(
        None, description="'Passport/ DL. No'. " + _COPY
    )
    voter_id: str | None = Field(None, description=_COPY)


class FormApplicant(FormPerson):
    """Applicant fields, with COURSE DETAILS."""

    admission_status: str | None = Field(
        None, description="COURSE DETAILS 'Admission Status'. " + _COPY
    )
    university: str | None = Field(
        None, description="COURSE DETAILS 'University'. " + _COPY
    )
    course: str | None = Field(
        None, description="COURSE DETAILS 'Course Name'. " + _COPY
    )
    country: str | None = Field(None, description="COURSE DETAILS 'Country'. " + _COPY)


class FormCoApplicant(FormPerson):
    """Co-applicant fields, with bank and employment details."""

    relationship: str | None = Field(
        None, description="'Relationship with Applicant'. " + _COPY
    )
    bank_name: str | None = Field(
        None, description="This co-applicant's bank name. " + _COPY
    )
    account_number: str | None = Field(
        None, description="This co-applicant's account number. " + _COPY
    )
    employer_name: str | None = Field(
        None, description="'Name of the Current Employer or Business/Firm'. " + _COPY
    )
    employer_address: str | None = Field(
        None,
        description="'Address of the Employer or Business/Firm' "
        "with city, state, pincode, country. " + _COPY,
    )


class ApplicationForm(BaseModel):
    """Fields of an Avanse education-loan application form."""

    model_config = ConfigDict(extra="ignore")
    application_no: str | None = Field(
        None, description="'Application No/ SL No'. " + _COPY
    )
    lead_id: str | None = Field(None, description="'Lead Id'. " + _COPY)
    applicant: FormApplicant | None = Field(
        None, description="APPLICANT DETAILS section"
    )
    co_applicants: list[FormCoApplicant] = Field(
        default_factory=list,
        description="One entry per 'CO-APPLICANT n DETAILS' section, in order.",
    )


def _kept(
    obj: BaseModel,
    prefix: str,
    source: Source | None,
    meta: dict[str, str],
    dropped: list[DroppedValue],
) -> dict[str, Any]:
    """Keep the scalar fields of ``obj``: masked tags are dropped, OCR values must be found."""
    out: dict[str, Any] = {}
    for name in type(obj).model_fields:
        value = getattr(obj, name)
        if isinstance(value, BaseModel | list):
            continue
        text = clean(value)
        if text is None:
            continue
        path = f"{prefix}.{name}"
        if _MASK_TAG.search(text):
            # A PII guardrail replaced the value with a tag.
            dropped.append(DroppedValue(field=path, value=text, reason="MASKED"))
            continue
        how = ground(text, source) if source else "vision"
        if how:
            out[name] = text
            meta[path] = how
        else:
            dropped.append(DroppedValue(field=path, value=text, reason="NOT_IN_SOURCE"))
    return out


def _form_lead(
    form: ApplicationForm, source: Source | None
) -> tuple[dict[str, Any], dict[str, str], list[DroppedValue]]:
    """Turn the model's answer into lead fields (grounded when there is OCR text)."""
    meta: dict[str, str] = {}
    dropped: list[DroppedValue] = []
    top = _kept(form, "lead", source, meta, dropped)
    applicant = _kept(
        form.applicant or FormApplicant.model_validate({}),
        "lead.applicant",
        source,
        meta,
        dropped,
    )
    co_applicants = []
    for n, co in enumerate(form.co_applicants, start=1):
        party_id = f"co_applicant_{n}"
        values = _kept(co, f"lead.co_applicants[{party_id}]", source, meta, dropped)
        values["relationship"] = normalize_relationship(
            values.pop("relationship", None)
        )
        co_applicants.append({"party_id": party_id, **values})
    lead = {
        "application_no": top.get("application_no"),
        "lead_id": top.get("lead_id"),
        "applicant": applicant,
        "co_applicants": co_applicants,
    }
    return lead, meta, dropped


class AutofillService:
    """Reads the lead fields from an application form in the configured mode."""

    def __init__(
        self,
        settings: Settings,
        config: dict[str, Any],
        prompts: PromptManager,
        models: BedrockModels,
        store: CaseStore,
    ) -> None:
        self._settings = settings
        self._config = config
        self._mode = str(config["mode"])
        self._prompts = prompts
        self._models = models
        self._store = store

    def _llm_form(
        self, content: bytes, file_name: str, hints: list[str]
    ) -> tuple[ApplicationForm, Source | None, dict[str, Any], list[str]]:
        """Ask the LLM for the form fields (from OCR text or from page images)."""
        name = str(self._config["modes"][self._mode]["application_form_prompt"])
        cfg = self._prompts.config(name)
        vision = self._mode == "vision_llm"
        warnings: list[str] = []
        attachments = None
        variables: dict[str, Any] = {"vision": vision, "hints": hints}
        source: Source | None = None
        stats: dict[str, Any] = {}
        try:
            if vision:
                attachments = to_blocks(content, self._config["vision"])
                limit = int(self._config["vision"]["max_images_per_call"])
                if len(attachments) > limit:
                    warnings.append(
                        f"Only the first {limit} of {len(attachments)} pages were read."
                    )
                    attachments = attachments[:limit]
                variables["pages"] = stats["pages"] = len(attachments)
            else:
                text = self._ocr_text(content, file_name)
                variables["ocr_text"] = text.text
                source = Source.of(text.text)
                stats = text.stats()
            form = extract_structured(
                self._models.get(
                    cfg.llm.model_id, cfg.llm.temperature, cfg.llm.max_tokens
                ),
                system_prompt=self._prompts.render_system(name, vision=vision),
                user_prompt=self._prompts.render_user(name, **variables),
                schema=ApplicationForm,
                name="application_form_autofill",
                attachments=attachments,
            )
        except UnreadableFileError as exc:
            raise InvalidInputError(f"{file_name}: {exc}") from exc
        except BedrockUnavailableError as exc:
            raise AgentUnavailableError(str(exc)) from exc
        stats["model_id"] = self._models.model_id(cfg.llm.model_id)
        stats["prompt_version"] = cfg.version
        return form, source, stats, warnings

    def _ocr_text(self, content: bytes, file_name: str) -> Any:
        """Read an OCR JSON (pages) or a plain-text OCR file into one masked text."""
        try:
            raw = content.decode("utf-8-sig")
            ocr = None
            if file_name.lower().endswith(".json"):
                ocr = json.loads(raw)
                if not isinstance(ocr, dict):
                    raise OcrInputError("the OCR JSON must be an object with 'pages'")
            return ocr_to_text(
                ocr,
                None if ocr is not None else raw,
                aadhaar_card=False,
                max_chars=self._settings.autofill_max_ocr_chars,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidInputError(f"{file_name}: {exc}") from exc

    def _case_id(self, given: str | None, lead: dict[str, Any]) -> str:
        """Use the given case ID, else the form's application number or lead ID."""
        for candidate in (given, lead.get("application_no"), lead.get("lead_id")):
            if candidate and _CASE_ID.fullmatch(str(candidate)):
                return str(candidate)
        return f"CASE-{dt.datetime.now(dt.UTC):%Y%m%d}-{uuid.uuid4().hex[:6]}"

    def autofill(
        self,
        *,
        file_name: str,
        content: bytes,
        case_id: str | None,
        hints: list[str],
    ) -> AutofillResponse:
        """Read every lead field from the application form, then store the file and its JSON.

        Args:
            file_name: Name of the uploaded application form.
            content: The file bytes.
            case_id: The case, or None to take the form's application number.
            hints: Names typed in the UI (help the LLM find the sections).

        Returns:
            The lead fields for review, how each was found and the dropped values.

        Raises:
            InvalidInputError: If the file cannot be read in this mode.
            AgentUnavailableError: If Bedrock refuses the call.
        """
        started = time.perf_counter()
        warnings: list[str] = []
        stats: dict[str, Any] = {}
        if self._mode == "structured":
            try:
                data = json.loads(content.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise InvalidInputError(f"{file_name}: not a valid JSON file") from exc
            mapping = get_structured_mapping()["application_form"]
            lead, grounding = application_form_lead(data, mapping)
            dropped: list[DroppedValue] = []
        else:
            form, source, stats, warnings = self._llm_form(content, file_name, hints)
            lead, grounding, dropped = _form_lead(form, source)
        case = self._case_id(case_id, lead)
        stored = self._store_files(case, file_name, content, lead)
        logger.info(
            "autofill.completed",
            mode=self._mode,
            co_applicants=len(lead["co_applicants"]),
            grounded=len(grounding),
            dropped=len(dropped),
        )
        return AutofillResponse(
            case_id=case,
            mode=self._mode,
            lead=lead,
            grounding=grounding,
            dropped=dropped,
            stats=stats,
            stored=stored,
            warnings=warnings,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    def _store_files(
        self, case_id: str, file_name: str, content: bytes, lead: dict[str, Any]
    ) -> list[str]:
        """Keep the uploaded form and the JSON read from it, as configured."""
        storage = self._config["storage"]
        folder = str(storage["application_form_dir"])
        stored = []
        if storage.get("keep_uploads"):
            stored.append(self._store.save_upload(case_id, folder, file_name, content))
        if storage.get("keep_extracted_json"):
            record = {"file_name": file_name, "mode": self._mode, "lead": lead}
            stored.append(
                self._store.save_extracted(case_id, folder, file_name, record)
            )
        return stored
