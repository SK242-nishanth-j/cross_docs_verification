import type { ApplicantLead, CoApplicantLead, Lead } from "../../../types/api";
import { RELATIONSHIPS } from "../../../types/api";

interface Props {
  lead: Lead;
  onChange: (lead: Lead) => void;
  grounding: Record<string, string>;
}

type Field<T> = { key: keyof T & string; label: string; wide?: boolean };

const PERSON: Field<ApplicantLead>[] = [
  { key: "name", label: "Name *" },
  { key: "father_name", label: "Father / spouse name" },
  { key: "mother_name", label: "Mother's name" },
  { key: "dob", label: "Date of birth" },
  { key: "gender", label: "Gender" },
  { key: "pan", label: "PAN" },
  { key: "aadhaar_last4", label: "Aadhaar (last 4 digits)" },
  { key: "passport_or_dl_number", label: "Passport / DL number" },
  { key: "voter_id", label: "Voter ID" },
  { key: "mobile", label: "Mobile" },
  { key: "email", label: "Email" },
  { key: "address", label: "Current address", wide: true },
  { key: "permanent_address", label: "Permanent address", wide: true },
];
const APPLICANT_ONLY: Field<ApplicantLead>[] = [
  { key: "admission_status", label: "Admission status" },
  { key: "university", label: "University" },
  { key: "course", label: "Course" },
  { key: "country", label: "Country" },
];
const CO_ONLY: Field<CoApplicantLead>[] = [
  { key: "bank_name", label: "Bank name" },
  { key: "account_number", label: "Account number" },
  { key: "employer_name", label: "Employer / business name" },
  { key: "employer_address", label: "Employer / business address", wide: true },
];

function nextPartyId(existing: CoApplicantLead[]): string {
  const used = new Set(existing.map((c) => c.party_id));
  let n = 1;
  while (used.has(`co_applicant_${n}`)) n += 1;
  return `co_applicant_${n}`;
}

function Input({
  label,
  value,
  wide,
  filled,
  onChange,
}: {
  label: string;
  value: string;
  wide?: boolean;
  filled?: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className={`${wide ? "wide" : ""} ${filled ? "autofilled" : ""}`} title={filled ? `auto-filled (${filled})` : ""}>
      <span>
        {label}
        {filled && <em> · from form</em>}
      </span>
      {wide ? (
        <textarea rows={2} value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input value={value} onChange={(e) => onChange(e.target.value)} />
      )}
    </label>
  );
}

export function LeadForm({ lead, onChange, grounding }: Props) {
  const setApplicant = (key: string, value: string) =>
    onChange({ ...lead, applicant: { ...lead.applicant, [key]: value } });
  const setCo = (index: number, patch: Partial<CoApplicantLead>) =>
    onChange({ ...lead, co_applicants: lead.co_applicants.map((c, i) => (i === index ? { ...c, ...patch } : c)) });
  const addCo = () =>
    onChange({
      ...lead,
      co_applicants: [...lead.co_applicants, { party_id: nextPartyId(lead.co_applicants), relationship: "father", name: "" }],
    });
  const removeCo = (index: number) => onChange({ ...lead, co_applicants: lead.co_applicants.filter((_, i) => i !== index) });

  const a = lead.applicant as unknown as Record<string, string | null | undefined>;
  return (
    <div className="lead-form">
      <div className="grid">
        <Input label="Application no." value={lead.application_no ?? ""} filled={grounding["lead.application_no"]}
          onChange={(v) => onChange({ ...lead, application_no: v })} />
        <Input label="Lead ID" value={lead.lead_id ?? ""} filled={grounding["lead.lead_id"]}
          onChange={(v) => onChange({ ...lead, lead_id: v })} />
      </div>

      <h3>Applicant</h3>
      <div className="grid">
        {[...PERSON, ...APPLICANT_ONLY].map((f) => (
          <Input key={f.key} label={f.label} wide={f.wide} value={a[f.key] ?? ""}
            filled={grounding[`lead.applicant.${f.key}`]} onChange={(v) => setApplicant(f.key, v)} />
        ))}
      </div>

      <div className="row-between">
        <h3>Co-applicants ({lead.co_applicants.length})</h3>
        <button type="button" className="secondary" onClick={addCo}>
          + Add co-applicant
        </button>
      </div>
      {lead.co_applicants.map((c, i) => {
        const values = c as unknown as Record<string, string | null | undefined>;
        const g = (k: string) => grounding[`lead.co_applicants[${c.party_id}].${k}`];
        return (
          <div key={c.party_id} className="co-card">
            <div className="row-between">
              <strong>{c.party_id}</strong>
              <button type="button" className="link danger" onClick={() => removeCo(i)}>
                Remove
              </button>
            </div>
            <div className="grid">
              <label className={g("relationship") ? "autofilled" : ""}>
                <span>Relationship to applicant *{g("relationship") && <em> · from form</em>}</span>
                <select value={c.relationship}
                  onChange={(e) => setCo(i, { relationship: e.target.value as CoApplicantLead["relationship"] })}>
                  {RELATIONSHIPS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
              {[...(PERSON as Field<CoApplicantLead>[]), ...CO_ONLY].map((f) => (
                <Input key={f.key} label={f.label} wide={f.wide} value={values[f.key] ?? ""} filled={g(f.key)}
                  onChange={(v) => setCo(i, { [f.key]: v })} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
