"""
File: autofill_service.py
Purpose: Application form OCR -> LLM -> grounded lead fields, shown in the UI for review (nothing stored).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic, strands-agents
"""

import time
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from src.adapters.bedrock.client import BedrockModels
from src.adapters.bedrock.client import BedrockUnavailableError
from src.adapters.bedrock.client import extract_structured
from src.ai.evaluators.grounding import Source
from src.ai.evaluators.grounding import clean
from src.ai.evaluators.grounding import ground
from src.ai.prompts.manager import PromptManager
from src.config.settings import Settings
from src.services.errors import AgentUnavailableError
from src.services.errors import InvalidInputError
from src.services.models import RELATIONSHIPS
from src.services.models import AutofillRequest
from src.services.models import AutofillResponse
from src.services.models import DroppedValue
from src.utils.logging.logger import get_logger
from src.utils.ocr_text import OcrInputError
from src.utils.ocr_text import ocr_to_text

logger = get_logger(__name__)

PROMPT_NAME = "application_form"
_COPY = "Copy exactly as printed. null if not printed."
_REL_SYNONYMS = {
    "dad": "father",
    "mom": "mother",
    "mum": "mother",
    "husband": "spouse",
    "wife": "spouse",
    "legal guardian": "guardian",
    "grand father": "grandfather",
    "grand mother": "grandmother",
}


class FormPerson(BaseModel):
    """Fields of one person on the application form."""

    model_config = ConfigDict(extra="ignore")
    name: str | None = Field(
        None, description="Full name: First, Middle, Last joined with spaces. " + _COPY
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
        None, description="Digits printed after 'Aadhar No' (often the last 4)."
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


def _relationship(value: str | None) -> str | None:
    """Map the form's relationship text to a lead relationship."""
    if not value:
        return None
    text = " ".join(value.casefold().replace("-", " ").split())
    text = _REL_SYNONYMS.get(text, text)
    return text if text in RELATIONSHIPS else "other"


def _grounded(
    obj: BaseModel,
    prefix: str,
    source: Source,
    meta: dict[str, str],
    dropped: list[DroppedValue],
) -> dict[str, Any]:
    """Keep the scalar fields of ``obj`` that are found in the OCR text."""
    out: dict[str, Any] = {}
    for name in type(obj).model_fields:
        value = getattr(obj, name)
        if isinstance(value, BaseModel | list):
            continue
        text = clean(value)
        if text is None:
            continue
        how = ground(text, source)
        path = f"{prefix}.{name}"
        if how:
            out[name] = text
            meta[path] = how
        else:
            dropped.append(DroppedValue(field=path, value=text, reason="NOT_IN_SOURCE"))
    return out


class AutofillService:
    """Reads the lead fields from an application form's OCR."""

    def __init__(
        self, settings: Settings, prompts: PromptManager, models: BedrockModels
    ) -> None:
        self._settings = settings
        self._prompts = prompts
        self._models = models

    def autofill(self, req: AutofillRequest) -> AutofillResponse:
        """Read every lead field from the application form.

        Args:
            req: The application form OCR and the names typed in the UI.

        Returns:
            The grounded lead fields, how each was found and the dropped values.

        Raises:
            InvalidInputError: If the OCR has no readable text.
            AgentUnavailableError: If Bedrock refuses the call.
        """
        started = time.perf_counter()
        try:
            text = ocr_to_text(
                req.ocr,
                req.raw_ocr,
                aadhaar_card=False,
                max_chars=self._settings.autofill_max_ocr_chars,
            )
        except OcrInputError as exc:
            raise InvalidInputError(str(exc)) from exc
        hints = (
            [f"Applicant (typed by the user): {req.applicant_name}"]
            if req.applicant_name
            else []
        )
        hints += [
            f"Co-applicant {n} (typed by the user): {name.strip()}"
            for n, name in enumerate(req.co_applicant_names, start=1)
            if name.strip()
        ]
        cfg = self._prompts.config(PROMPT_NAME)
        try:
            form = extract_structured(
                self._models.get(
                    cfg.llm.model_id, cfg.llm.temperature, cfg.llm.max_tokens
                ),
                system_prompt=self._prompts.render_system(PROMPT_NAME),
                user_prompt=self._prompts.render_user(
                    PROMPT_NAME, hints=hints, ocr_text=text.text
                ),
                schema=ApplicationForm,
                name="application_form_autofill",
            )
        except BedrockUnavailableError as exc:
            raise AgentUnavailableError(str(exc)) from exc

        source = Source.of(text.text)
        meta: dict[str, str] = {}
        dropped: list[DroppedValue] = []
        top = _grounded(form, "lead", source, meta, dropped)
        applicant = _grounded(
            form.applicant or FormApplicant.model_validate({}),
            "lead.applicant",
            source,
            meta,
            dropped,
        )
        co_applicants = []
        for n, co in enumerate(form.co_applicants, start=1):
            party_id = f"co_applicant_{n}"
            values = _grounded(
                co, f"lead.co_applicants[{party_id}]", source, meta, dropped
            )
            values["relationship"] = _relationship(values.pop("relationship", None))
            co_applicants.append({"party_id": party_id, **values})
        logger.info(
            "autofill.completed",
            co_applicants=len(co_applicants),
            grounded=len(meta),
            dropped=len(dropped),
            pages=text.pages,
        )
        return AutofillResponse(
            lead={
                "application_no": top.get("application_no"),
                "lead_id": top.get("lead_id"),
                "applicant": applicant,
                "co_applicants": co_applicants,
            },
            grounding=meta,
            dropped=dropped,
            ocr=text.stats(),
            model_id=self._models.model_id(cfg.llm.model_id),
            prompt_version=cfg.version,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
