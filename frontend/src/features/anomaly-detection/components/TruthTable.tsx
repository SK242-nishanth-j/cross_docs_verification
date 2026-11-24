import { COLOR_LABEL } from "../../../lib/colors";
import type { Color, Finding, PartyBlock, Source } from "../../../types/api";
import { Chip } from "./ResultAtoms";

/** Anonymisation tags such as {NAME} (Bedrock Guardrails PII filter). */
const MASK_TAG = /\{[A-Z][A-Z0-9_]*\}/;

const FIELD_LABEL: Record<string, string> = {
  NAME: "Name",
  DOB: "Date of birth",
  FATHER_NAME: "Father name",
  MOTHER_NAME: "Mother name",
  ADDRESS: "Address",
  HOUSEHOLD_ADDRESS: "Household address",
  PARENT_NAME: "Name (as parent)",
  PAN: "PAN",
  AADHAAR: "Aadhaar (last 4)",
  PASSPORT_NO: "Passport",
  VOTER_ID: "Voter ID",
  DL_NO: "Driving licence",
};

const MARK: Record<Color, string> = { green: "✓", yellow: "≈", red: "✗", grey: "–" };

interface Column {
  id: string;
  label: string;
  color: Color | null;
  title: string;
  finding?: Finding;
  sources: Source[];
}

interface Cell {
  value: string;
  color: Color | "base" | "masked" | "single";
  note: string;
}

interface Row {
  key: string;
  label: string;
  sub: string;
  order: number;
}

/** Field name of a check ID such as ``applicant.DOB``. */
function fieldOf(checkId: string): string {
  return checkId.split(".").pop() ?? checkId;
}

/** One row per lead person, document file or third-party source. */
function rowOf(s: Source, docOrder: Map<string, number>): Row {
  const parts = s.label.split(" · ");
  if (s.kind === "document" && s.file_name) {
    const index = docOrder.get(s.file_name) ?? docOrder.size;
    return { key: `doc:${s.file_name}`, label: s.file_name, sub: parts[0], order: 100 + index };
  }
  if (s.kind === "lead") {
    const who = parts[1] ?? s.party_id;
    return { key: `lead:${who}`, label: `Lead · ${who}`, sub: "application form", order: who === "Applicant" ? 0 : 1 };
  }
  return { key: `bureau:${s.label}`, label: s.label, sub: "third party (mock)", order: 900 };
}

/** What one source shows in one column, compared with the column's base (first source). */
function cellFor(col: Column, s: Source): Cell {
  if (MASK_TAG.test(s.value)) {
    return { value: s.value, color: "masked", note: "Masked by the Bedrock PII guardrail; not a real value." };
  }
  if (!col.finding || col.sources.length < 2) {
    return { value: s.value, color: "single", note: "Only source of this field; nothing to compare." };
  }
  const base = col.sources[0];
  if (s.key === base.key) {
    return { value: s.value, color: "base", note: "Base: every other source in this column is compared with it." };
  }
  const pair = (col.finding.pairs ?? []).find(
    (p) => (p.a === base.key && p.b === s.key) || (p.a === s.key && p.b === base.key),
  );
  if (!pair) {
    const why = s.side === base.side ? " (both are the applicant's; compared in the applicant table)" : "";
    return { value: s.value, color: "grey", note: `Not compared with ${base.label}${why}` };
  }
  const why = pair.reasons
    .filter((r) => r.severity !== "info")
    .map((r) => r.message)
    .join("; ");
  return { value: s.value, color: pair.color, note: `${COLOR_LABEL[pair.color]} vs ${base.label}${why ? `: ${why}` : ""}` };
}

function markOf(color: Cell["color"]): string {
  if (color === "base") return "★";
  if (color === "masked") return "🔒";
  if (color === "single") return "•";
  return MARK[color];
}

/** Third-party title without the rule ID and the bracketed provider, e.g. "PAN-Aadhaar linkage". */
function shortTitle(title: string): string {
  return title
    .replace(/^KY-\d+\s*/, "")
    .replace(/\s*\([^)]*\)/g, "")
    .trim();
}

function PartyTruthTable({ party }: { party: PartyBlock }) {
  const columns: Column[] = [
    ...party.cross_verification.map((f) => ({
      id: f.check_id,
      label: FIELD_LABEL[f.check] ?? f.title,
      color: f.color,
      title: f.title,
      finding: f,
      sources: f.sources ?? [],
    })),
    ...party.not_compared.map((n) => ({
      id: n.check_id,
      label: FIELD_LABEL[fieldOf(n.check_id)] ?? n.title,
      color: null,
      title: n.title,
      sources: n.sources,
    })),
  ];
  const docOrder = new Map(party.documents.map((d, i) => [d.file_name, i]));
  const rows = new Map<string, Row>();
  const cells = new Map<string, Cell>();
  for (const col of columns) {
    for (const s of col.sources) {
      const row = rowOf(s, docOrder);
      if (!rows.has(row.key)) rows.set(row.key, row);
      const key = `${row.key}|${col.id}`;
      if (!cells.has(key)) cells.set(key, cellFor(col, s));
    }
  }
  const sorted = [...rows.values()].sort((x, y) => x.order - y.order || x.label.localeCompare(y.label));

  return (
    <div className="truth">
      <h4>
        {party.label} · {party.name} <Chip color={party.status_color} />
      </h4>
      {columns.length === 0 ? (
        <p className="muted">No fields to compare.</p>
      ) : (
        <div className="truth-scroll">
          <table className="truth-table">
            <thead>
              <tr>
                <th className="src">Source</th>
                {columns.map((c) => (
                  <th key={c.id} title={c.title}>
                    <div>{c.label}</div>
                    {c.color ? <Chip color={c.color} /> : <Chip color="grey" label="1 source" />}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.key} className={r.key.startsWith("lead:") ? "lead-row" : ""}>
                  <th className="src">
                    <div>{r.label}</div>
                    <div className="muted">{r.sub}</div>
                  </th>
                  {columns.map((c) => {
                    const cell = cells.get(`${r.key}|${c.id}`);
                    if (!cell) return <td key={c.id} className="empty" />;
                    return (
                      <td key={c.id}>
                        <div className={`tcell ${cell.color}`} title={`${cell.value}\n${cell.note}`}>
                          <span className="mark">{markOf(cell.color)}</span>
                          <span className="v">{cell.value}</span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {party.third_party.length > 0 && (
        <div className="truth-third">
          <span className="muted">Third-party checks (mock):</span>
          {party.third_party.map((f) => (
            <span key={f.check_id} title={f.message}>
              <Chip color={f.color} label={`${shortTitle(f.title)}: ${COLOR_LABEL[f.color]}`} />
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function TruthTable({ parties }: { parties: PartyBlock[] }) {
  return (
    <div>
      <div className="truth-legend muted">
        <span>★ base (first source of the column)</span>
        <span>✓ match</span>
        <span>≈ review</span>
        <span>✗ mismatch</span>
        <span>🔒 masked</span>
        <span>• only source</span>
        <span>Hover a cell for the reason.</span>
      </div>
      {parties.map((p) => (
        <PartyTruthTable key={p.party_id} party={p} />
      ))}
    </div>
  );
}
