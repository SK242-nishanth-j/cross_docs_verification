export const DOC_TYPES = [
  "PAN",
  "AADHAAR",
  "PASSPORT",
  "VOTER_ID",
  "DRIVING_LICENCE",
  "MARKSHEET",
  "DEGREE_CERTIFICATE",
  "ADMIT_LETTER",
  "OTHER",
] as const;
export type DocType = (typeof DOC_TYPES)[number];

export const RELATIONSHIPS = [
  "father",
  "mother",
  "spouse",
  "brother",
  "sister",
  "guardian",
  "uncle",
  "aunt",
  "grandfather",
  "grandmother",
  "other",
] as const;
export type Relationship = (typeof RELATIONSHIPS)[number];

export interface PersonLead {
  name: string;
  father_name?: string | null;
  mother_name?: string | null;
  dob?: string | null;
  gender?: string | null;
  address?: string | null;
  permanent_address?: string | null;
  mobile?: string | null;
  email?: string | null;
  pan?: string | null;
  aadhaar_last4?: string | null;
  passport_or_dl_number?: string | null;
  voter_id?: string | null;
}

export interface ApplicantLead extends PersonLead {
  admission_status?: string | null;
  university?: string | null;
  course?: string | null;
  country?: string | null;
}

export interface CoApplicantLead extends PersonLead {
  party_id: string;
  relationship: Relationship;
  bank_name?: string | null;
  account_number?: string | null;
  employer_name?: string | null;
  employer_address?: string | null;
}

export interface Lead {
  application_no?: string | null;
  lead_id?: string | null;
  applicant: ApplicantLead;
  co_applicants: CoApplicantLead[];
}

export interface OcrJson {
  status?: string;
  pages: { page_number?: number; text_lines?: string[]; structured_lines?: unknown[]; text?: string }[];
}

export interface DocumentIn {
  party_id: string;
  doc_type: DocType;
  file_name: string;
  ocr?: OcrJson;
  raw_ocr?: string;
}

export interface CasePayload {
  case_id: string;
  lead: Lead;
  documents: DocumentIn[];
  mock_overrides?: Record<string, unknown>;
}

export interface AutofillResponse {
  lead: {
    application_no?: string | null;
    lead_id?: string | null;
    applicant: Partial<ApplicantLead>;
    co_applicants: (Partial<CoApplicantLead> & { party_id: string })[];
  };
  grounding: Record<string, string>;
  dropped: { field: string; value: string; reason: string }[];
  ocr: { pages: number; lines: number; mean_confidence: number | null; truncated: boolean };
  model_id: string;
  elapsed_ms: number;
}

export type Color = "green" | "yellow" | "red" | "grey";

export interface Segment {
  text: string;
  kind: string;
}

export interface Reason {
  code: string;
  severity: string;
  message: string;
}

export interface Source {
  key: string;
  kind: "lead" | "document" | "bureau";
  label: string;
  value: string;
  party_id: string;
  side: string;
  file_name?: string;
  doc_type?: string;
  path?: string;
}

export interface Pair {
  a: string;
  b: string;
  status: string;
  color: Color;
  reasons: Reason[];
  highlight: { a: Segment[]; b: Segment[] };
}

export interface Finding {
  check_id: string;
  party_id: string;
  category: "cross_verification" | "third_party";
  check: string;
  rule_id: string | null;
  title: string;
  severity: string | null;
  status: string;
  color: Color;
  critical: boolean;
  message: string;
  mitigant: string | null;
  sanction_condition: string | null;
  base: { value: string | null; source: string } | null;
  comparisons: {
    value: string;
    reported_on?: string;
    color?: Color;
    reasons?: Reason[];
    highlight?: { base: Segment[]; candidate: Segment[] };
  }[];
  evidence: Record<string, unknown>;
  sources?: Source[];
  pairs?: Pair[];
  per_source?: { key: string; label: string; pairs: number; differs_in: number; worst_color: Color }[];
}

export interface PartyBlock {
  party_id: string;
  role: string;
  relationship: string | null;
  name: string;
  label: string;
  status_color: Color;
  documents: { file_name: string; doc_type: string; status: string }[];
  cross_verification: Finding[];
  third_party: Finding[];
  not_compared: { check_id: string; title: string; sources: Source[] }[];
}

export interface ExtractionRow {
  document_index: number;
  party_id: string;
  doc_type: string;
  file_name: string;
  status: string;
  fields: Record<string, string>;
  grounding: Record<string, string>;
  dropped: { field: string; value: string; reason: string }[];
  error: string | null;
  ocr: { pages?: number; lines?: number; mean_confidence?: number | null };
  elapsed_ms: number;
}

export interface AnomalyReport {
  case_id: string;
  generated_at: string;
  config: Record<string, unknown>;
  summary: {
    overall_color: Color;
    counts: Record<Color, number>;
    total_checks: number;
    pairs_compared: number;
    high_severity_flags: number;
    critical_flags: number;
  };
  anomalies: Pick<
    Finding,
    "check_id" | "party_id" | "category" | "rule_id" | "title" | "severity" | "status" | "color" | "critical" | "message" | "mitigant"
  >[];
  sanction_conditions: { party_id: string; rule_id: string; condition: string }[];
  cm_justifications: { party_id: string; rule_id: string; reason: string }[];
  parties: PartyBlock[];
  extraction: ExtractionRow[];
  timing_ms?: { extraction: number; total: number };
}

export interface RunResult {
  run_id: string;
  case_id: string;
  status: string;
  started_at: string;
  finished_at: string;
  orchestrator: { mode: string; tools_called: string[]; fallback: boolean; summary: string; summary_source: string; model_id: string; error?: string };
  results: { anomaly_detection: AnomalyReport };
}
