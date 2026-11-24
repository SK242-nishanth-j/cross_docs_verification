"""
File: sources.py
Purpose: Sources of a value (lead, document, bureau) and comparison groups with their pairs.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from src.adapters.kyc.models import BureauReport
from src.ai.agents.anomaly_detection.parties import Party

DOC_LABEL = {
    "PAN": "PAN",
    "AADHAAR": "Aadhaar",
    "PASSPORT": "Passport",
    "VOTER_ID": "Voter ID",
    "DRIVING_LICENCE": "Driving licence",
    "MARKSHEET": "Marksheet",
    "DEGREE_CERTIFICATE": "Degree certificate",
    "ADMIT_LETTER": "Admit letter",
    "OTHER": "Other",
}
APPLICANT_SIDE = "applicant_side"


@dataclass
class Src:
    """One source of a value: the lead, a document or the bureau."""

    key: str
    kind: str  # lead | document | bureau
    label: str
    value: str
    party_id: str
    side: str
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the source for the report.

        Returns:
            Key, kind, label, value, party and citation details.
        """
        return {
            "key": self.key,
            "kind": self.kind,
            "label": self.label,
            "value": self.value,
            "party_id": self.party_id,
            "side": self.side,
            **self.meta,
        }


@dataclass
class Group:
    """One field compared across every source that has it."""

    group_id: str
    party_id: str
    check: str
    field_type: str  # cross_verify type
    title: str
    sources: list[Src]
    # Pairs whose two sources both have a side in this set are skipped
    # (they were already compared in the applicant section).
    skip_sides: frozenset[str] = frozenset()

    def pairs(self) -> list[tuple[int, int]]:
        """Return the source pairs to compare.

        Returns:
            (i, j) index pairs with i < j, without pairs already compared elsewhere.
        """
        out = []
        for i in range(len(self.sources)):
            for j in range(i + 1, len(self.sources)):
                a, b = self.sources[i].side, self.sources[j].side
                if not (a in self.skip_sides and b in self.skip_sides):
                    out.append((i, j))
        return out


class SourceBuilder:
    """Collects the sources of one group and numbers them s0, s1, ..."""

    def __init__(self) -> None:
        self.items: list[Src] = []

    def lead(
        self,
        party: Party,
        attr: str,
        value: str | None,
        side: str = "self",
        who: str | None = None,
    ) -> "SourceBuilder":
        """Add a lead value.

        Args:
            party: Whose lead value it is.
            attr: Lead attribute, for example ``father_name``.
            value: The value; nothing is added when it is empty.
            side: Side tag used to skip pairs.
            who: Label override, for example ``Applicant``.

        Returns:
            The builder, for chaining.
        """
        if value:
            label = f"Lead · {who or party.label} · {attr.replace('_', ' ')}"
            meta = {"path": party.lead_path(attr)}
            self.items.append(Src("", "lead", label, value, party.party_id, side, meta))
        return self

    def docs(
        self,
        party: Party,
        attr: str,
        doc_types: set[str] | None = None,
        side: str = "self",
        who: str | None = None,
    ) -> "SourceBuilder":
        """Add the value ``attr`` of every readable document of a party.

        Args:
            party: Whose documents.
            attr: Extracted field, for example ``dob``.
            doc_types: Only these document types; None for all.
            side: Side tag used to skip pairs.
            who: Text appended to the label, for example ``applicant's father``.

        Returns:
            The builder, for chaining.
        """
        for e in party.readable():
            value = e.get(attr)
            if value and (doc_types is None or e.doc_type in doc_types):
                label = f"{DOC_LABEL.get(e.doc_type, e.doc_type)} · {e.file_name}"
                label += f" · {who}" if who else ""
                meta = {
                    "file_name": e.file_name,
                    "doc_type": e.doc_type,
                    "field": attr,
                    "document_index": e.document_index,
                }
                self.items.append(
                    Src("", "document", label, value, party.party_id, side, meta)
                )
        return self

    def bureau(
        self, party: Party, report: BureauReport | None, attr: str
    ) -> "SourceBuilder":
        """Add a bureau value.

        Args:
            party: Whose bureau report.
            report: The bureau report, or None.
            attr: ``name`` or ``dob``.

        Returns:
            The builder, for chaining.
        """
        value = getattr(report, attr, None) if report else None
        if report and value:
            label = f"Bureau ({report.provider}) · {party.label}"
            meta = {"provider": report.provider, "field": attr}
            self.items.append(
                Src("", "bureau", label, value, party.party_id, "self", meta)
            )
        return self

    def build(self) -> list[Src]:
        """Number the sources s0, s1, ... and return them.

        Returns:
            The sources in the order they were added.
        """
        for n, src in enumerate(self.items):
            src.key = f"s{n}"
        return self.items
