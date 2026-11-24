"""
File: structured_input.py
Purpose: Structured mode: key-value JSON -> lead fields and document fields, no LLM.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

Every key path comes from structured_mapping.yaml, so a new form layout or a new
document layout needs a config change only. A document file is one document, or a
case bundle with the documents of every person (person sections as on the form).
"""

import re
from typing import Any

from src.ai.agents.anomaly_detection.extraction import clean_fields
from src.ai.agents.anomaly_detection.schemas import DOC_TYPES
from src.ai.agents.anomaly_detection.schemas import DocumentExtraction
from src.ai.agents.anomaly_detection.schemas import DocumentIn
from src.ai.evaluators.grounding import clean
from src.security.pii import aadhaar_last4
from src.services.models import normalize_relationship

_ROOT = "$."
READ_BY = "structured"


def read_path(data: Any, path: str, section: Any = None) -> Any:
    """Read one value by its key path.

    Args:
        data: The whole JSON document.
        path: Keys joined with ``.``; ``$.`` starts at the top, else at ``section``.
        section: The person's section of the document.

    Returns:
        The value, or None when a key is missing.
    """
    node = data if path.startswith(_ROOT) or section is None else section
    rest = path.removeprefix(_ROOT)
    while rest:
        if not isinstance(node, dict):
            return None
        # Keys may contain dots ("Passport/ DL. No"): take the longest key that fits.
        keys = [
            k
            for k in node
            if isinstance(k, str) and (rest == k or rest.startswith(k + "."))
        ]
        if not keys:
            return None
        key = max(keys, key=len)
        node, rest = node[key], rest[len(key) + 1 :]
    return node


def _scalar(value: Any) -> str | None:
    """Return a printable value; dictionaries, lists and booleans are not values."""
    if isinstance(value, dict | list | bool) or value is None:
        return None
    return clean(value)


def field_value(spec: Any, data: Any, section: Any = None) -> str | None:
    """Read one field as configured in structured_mapping.yaml.

    A spec is a path; a list of specs (the first one with a value wins);
    ``{join: [specs], sep}`` (the values joined); or ``{join_all: path, sep}``
    (every value of the object at ``path`` joined, for addresses split in parts).

    Args:
        spec: The field definition.
        data: The whole JSON document.
        section: The person's section of the document.

    Returns:
        The value, or None when nothing is filled in.
    """
    if isinstance(spec, str):
        return _scalar(read_path(data, spec, section))
    if isinstance(spec, list):
        for alternative in spec:
            value = field_value(alternative, data, section)
            if value:
                return value
        return None
    if not isinstance(spec, dict):
        return None
    sep = str(spec.get("sep", " "))
    if isinstance(spec.get("join"), list):
        parts = [field_value(p, data, section) for p in spec["join"]]
        return sep.join(p for p in parts if p) or None
    if isinstance(spec.get("join_all"), str):
        node = read_path(data, spec["join_all"], section)
        if isinstance(node, dict):
            return sep.join(p for p in map(_scalar, node.values()) if p) or None
        return _scalar(node)
    return None


def _person(
    data: Any, section: Any, fields: dict[str, Any], prefix: str, found: dict[str, str]
) -> dict[str, Any]:
    """Read every configured field of one person."""
    out: dict[str, Any] = {}
    for name, spec in fields.items():
        value = field_value(spec, data, section)
        if isinstance(spec, dict) and spec.get("same_as_above") and not value:
            flag = read_path(data, str(spec["same_as_above"]), section)
            value = out.get(str(spec.get("same_as"))) if flag is True else None
        if value and name == "aadhaar_last4":
            digits = "".join(ch for ch in value if ch.isdigit())
            value = aadhaar_last4(value) if len(digits) >= 4 else None
        if value:
            out[name] = value
            found[f"{prefix}.{name}"] = READ_BY
    return out


def application_form_lead(
    data: Any, mapping: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Read the lead from a structured application form.

    Args:
        data: The structured JSON of the application form.
        mapping: The ``application_form`` section of structured_mapping.yaml.

    Returns:
        (lead fields for review, ``{field path: "structured"}`` for every field read).
    """
    found: dict[str, str] = {}
    common: dict[str, Any] = mapping["person_fields"]
    app = mapping["applicant"]
    applicant_section = read_path(data, _ROOT + str(app["section"]))
    applicant = _person(
        data,
        applicant_section,
        {**common, **app.get("fields", {})},
        "lead.applicant",
        found,
    )
    co_cfg = mapping["co_applicants"]
    co_applicants = []
    for n in range(1, int(co_cfg.get("max", 6)) + 1):
        section = read_path(data, _ROOT + str(co_cfg["section"]).format(n=n))
        if not isinstance(section, dict):
            break
        party_id = f"co_applicant_{n}"
        values = _person(
            data,
            section,
            {**common, **co_cfg.get("fields", {})},
            f"lead.co_applicants[{party_id}]",
            found,
        )
        relation = field_value(co_cfg["relationship"], data, section)
        co_applicants.append(
            {
                "party_id": party_id,
                **values,
                "relationship": normalize_relationship(relation),
            }
        )
    lead = {
        "application_no": field_value(mapping.get("application_no"), data),
        "lead_id": field_value(mapping.get("lead_id"), data),
        "applicant": applicant,
        "co_applicants": co_applicants,
    }
    return lead, found


def document_type(named: str | None, chosen: str, mapping: dict[str, Any]) -> str:
    """Return the type whose name starts the "Document Type" text, else ``chosen``.

    Args:
        named: The "Document Type" text of the JSON, for example "PAN Card".
        chosen: Type chosen in the UI (guessed from the file name).
        mapping: The ``documents`` section of structured_mapping.yaml.

    Returns:
        One of the document types.
    """
    if named:
        text = " ".join(named.casefold().split())
        for doc_type, names in mapping["document_types"].items():
            if doc_type in DOC_TYPES and any(
                re.match(rf"{re.escape(str(n).casefold())}\b", text) for n in names
            ):
                return str(doc_type)
    return chosen


def _read_fields(
    index: int,
    party_id: str,
    file_name: str,
    item: dict[str, Any],
    chosen: str,
    mapping: dict[str, Any],
) -> DocumentExtraction:
    """Read the identity fields of one document entry (values under "Fields" or at the top)."""
    named = _scalar(item.get(str(mapping["document_type_key"])))
    doc_type = document_type(named, chosen, mapping)
    out = DocumentExtraction(index, party_id, doc_type, file_name, READ_BY)
    values = item.get(str(mapping["fields_key"]))
    source = values if isinstance(values, dict) else item
    specs: dict[str, Any] = mapping["fields"].get(doc_type) or mapping["fields"].get(
        "OTHER", {}
    )
    raw = {name: field_value(spec, source, source) for name, spec in specs.items()}
    out.fields = clean_fields(doc_type, raw)
    out.grounding = dict.fromkeys(out.fields, READ_BY)
    out.stats = {"document_type": named, "mapped_fields": len(out.fields)}
    return out


def _bundle_sections(
    data: dict[str, Any], bundle: dict[str, Any]
) -> list[tuple[str, list[Any]]]:
    """Return (party_id, documents) for every person section of a case bundle."""
    key = str(bundle["documents_key"])
    names = [("applicant", str(bundle["applicant_section"]))] + [
        (f"co_applicant_{n}", str(bundle["co_applicant_section"]).format(n=n))
        for n in range(1, int(bundle.get("max_co_applicants", 6)) + 1)
    ]
    out = []
    for party_id, name in names:
        section = data.get(name)
        if isinstance(section, dict) and isinstance(section.get(key), list):
            out.append((party_id, section[key]))
    return out


def _failed(
    index: int, doc: DocumentIn, error: str, party_id: str | None = None
) -> DocumentExtraction:
    """A document that could not be read."""
    out = DocumentExtraction(
        index, party_id or doc.party_id, doc.doc_type, doc.file_name, READ_BY, "failed"
    )
    out.error, out.stored_as = error, doc.stored_as
    return out


def read_documents(
    documents: list[DocumentIn], mapping: dict[str, Any], known: set[str]
) -> list[DocumentExtraction]:
    """Read every structured upload: one document per file, or a case bundle.

    A case bundle holds the documents of every person under the person sections
    of the application form; each document is read and stored on its own.

    Args:
        documents: The uploaded JSON files.
        mapping: The ``documents`` section of structured_mapping.yaml.
        known: The party IDs of the lead.

    Returns:
        One extraction per document, numbered in reading order.
    """
    out: list[DocumentExtraction] = []
    for doc in documents:
        try:
            data = doc.json_content()
        except ValueError as exc:
            out.append(_failed(len(out), doc, str(exc)))
            continue
        if not isinstance(data, dict):
            out.append(
                _failed(len(out), doc, f"{doc.file_name}: expected a JSON object")
            )
            continue
        sections = _bundle_sections(data, mapping["bundle"])
        if not sections:
            one = _read_fields(
                len(out), doc.party_id, doc.file_name, data, doc.doc_type, mapping
            )
            one.stored_as = doc.stored_as
            out.append(one)
            continue
        for party_id, items in sections:
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = _scalar(item.get(str(mapping["bundle"]["file_key"])))
                name = name or f"{doc.file_name}#{len(out) + 1}"
                if party_id not in known:
                    error = f"{party_id} is not in the lead"
                    out.append(_failed(len(out), doc, error, party_id))
                    out[-1].file_name = name
                    continue
                entry = _read_fields(len(out), party_id, name, item, "OTHER", mapping)
                entry.stored_as = doc.stored_as
                entry.stats["bundle"] = doc.file_name
                out.append(entry)
    return out
