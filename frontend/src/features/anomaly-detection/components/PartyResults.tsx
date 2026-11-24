import { Fragment, useState } from "react";
import type { AnomalyReport, Finding, Pair, PartyBlock, Source } from "../../../types/api";
import { Chip, Highlight, Reasons } from "./ResultAtoms";

/** Sources, an N x N pair grid, then the pairs (differences first). */
function PairDetail({ finding }: { finding: Finding }) {
  const sources = finding.sources ?? [];
  const pairs = finding.pairs ?? [];
  const per = Object.fromEntries((finding.per_source ?? []).map((p) => [p.key, p]));
  const byKey = Object.fromEntries(sources.map((s) => [s.key, s])) as Record<string, Source>;
  const cell = (a: string, b: string): Pair | undefined =>
    pairs.find((p) => (p.a === a && p.b === b) || (p.a === b && p.b === a));
  const [showGreen, setShowGreen] = useState(false);
  const shown = pairs.filter((p) => showGreen || p.color !== "green");

  return (
    <div className="comparisons">
      <table className="inner">
        <thead>
          <tr>
            <th>#</th>
            <th>Source</th>
            <th>Value</th>
            <th>Differs in</th>
            {sources.map((s) => (
              <th key={s.key} className="mx">
                {s.key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sources.map((row) => (
            <tr key={row.key} className={row.kind === "lead" ? "lead-row" : ""}>
              <td>
                <code>{row.key}</code>
              </td>
              <td>{row.label}</td>
              <td>{row.value}</td>
              <td>
                {per[row.key] ? (
                  <Chip color={per[row.key].worst_color} label={`${per[row.key].differs_in}/${per[row.key].pairs}`} />
                ) : (
                  "—"
                )}
              </td>
              {sources.map((col) => {
                if (col.key === row.key) return <td key={col.key} className="mx self" />;
                const p = cell(row.key, col.key);
                return (
                  <td key={col.key} className="mx" title={p ? p.reasons.map((r) => r.code).join(", ") : "not compared"}>
                    {p ? <span className={`dot ${p.color}`} /> : <span className="dot none" />}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="row-between">
        <h5>Pairs ({pairs.length})</h5>
        <label className="inline">
          <input type="checkbox" checked={showGreen} onChange={(e) => setShowGreen(e.target.checked)} /> show matching pairs
        </label>
      </div>
      {shown.length === 0 && <p className="muted">All pairs match.</p>}
      {shown.length > 0 && (
        <table className="inner">
          <tbody>
            {shown.map((p, i) => (
              <tr key={i}>
                <td style={{ width: 90 }}>
                  <Chip color={p.color} />
                </td>
                <td>
                  <div className="muted">{byKey[p.a]?.label}</div>
                  <Highlight segments={p.highlight.a} fallback={byKey[p.a]?.value} />
                </td>
                <td>
                  <div className="muted">{byKey[p.b]?.label}</div>
                  <Highlight segments={p.highlight.b} fallback={byKey[p.b]?.value} />
                </td>
                <td className="reasons">
                  <Reasons reasons={p.reasons} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ApiDetail({ finding }: { finding: Finding }) {
  return (
    <div className="comparisons">
      {finding.base && (
        <div className="base-line">
          <span className="muted">Base (lead)</span> <code>{finding.base.source}</code>: {finding.base.value ?? "—"}
        </div>
      )}
      {finding.comparisons.length > 0 && (
        <table className="inner">
          <tbody>
            {finding.comparisons.map((c, i) => (
              <tr key={i}>
                <td style={{ width: 90 }}>{c.color && <Chip color={c.color} />}</td>
                <td>
                  <div className="muted">Bureau{c.reported_on ? `, reported ${c.reported_on}` : ""}</div>
                  <Highlight segments={c.highlight?.candidate} fallback={c.value} />
                </td>
                <td className="reasons">
                  <Reasons reasons={c.reasons} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <details>
        <summary>API response (mock)</summary>
        <pre>{JSON.stringify(finding.evidence, null, 2)}</pre>
      </details>
    </div>
  );
}

function FindingsTable({ findings, kind }: { findings: Finding[]; kind: "pairs" | "api" }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <table className="findings">
      <thead>
        <tr>
          <th style={{ width: 120 }}>Result</th>
          <th style={{ width: 300 }}>Check</th>
          <th style={{ width: 74 }}>Severity</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {findings.map((f) => (
          <Fragment key={f.check_id}>
            <tr className={`clickable ${open === f.check_id ? "open" : ""}`} onClick={() => setOpen(open === f.check_id ? null : f.check_id)}>
              <td>
                <Chip color={f.color} />
                {f.critical && <span className="chip red critical">CRITICAL</span>}
              </td>
              <td>
                {f.title}
                {kind === "pairs" && <div className="muted">{(f.sources ?? []).length} sources · {(f.pairs ?? []).length} pairs</div>}
              </td>
              <td>{f.severity ?? "—"}</td>
              <td>
                {f.message}
                {f.mitigant && <div className="mitigant">Mitigant: {f.mitigant}</div>}
                {f.sanction_condition && <div className="sanction">Sanction condition: {f.sanction_condition}</div>}
              </td>
            </tr>
            {open === f.check_id && (
              <tr className="detail">
                <td colSpan={4}>{kind === "pairs" ? <PairDetail finding={f} /> : <ApiDetail finding={f} />}</td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

export function PartySection({ party, step }: { party: PartyBlock; step: number }) {
  return (
    <details className="party" open={party.status_color === "red"}>
      <summary>
        <span className="step">{step}</span>
        <Chip color={party.status_color} />
        <strong>{party.label}</strong>
        <span>{party.name}</span>
        <span className="muted">{party.documents.length} document(s)</span>
      </summary>
      <h4>Cross-verification</h4>
      <FindingsTable findings={party.cross_verification} kind="pairs" />
      {party.not_compared.some((n) => n.sources.length === 1) && (
        <p className="muted">
          Only one source, nothing to compare:{" "}
          {party.not_compared.filter((n) => n.sources.length === 1).map((n) => `${n.title} (${n.sources[0]?.label})`).join(" · ")}
        </p>
      )}
      <h4>Third-party checks (mock APIs)</h4>
      <FindingsTable findings={party.third_party} kind="api" />
    </details>
  );
}

export function Extraction({ report }: { report: AnomalyReport }) {
  return (
    <details className="party">
      <summary>
        <strong>JSON read from each document</strong>
        <span className="muted">
          {report.extraction.length} document(s) · read by {report.extraction[0]?.read_by ?? "—"} · model {String(report.config.llm_model_id ?? "none")}
        </span>
      </summary>
      <table className="findings">
        <thead>
          <tr>
            <th>Document</th>
            <th>Party</th>
            <th>Status</th>
            <th>Fields read</th>
            <th>Dropped / stored as</th>
          </tr>
        </thead>
        <tbody>
          {report.extraction.map((e) => (
            <tr key={e.document_index}>
              <td>
                {e.file_name}
                <div className="muted">
                  {e.doc_type}{e.stats?.pages ? ` · ${e.stats.pages} page(s)` : ""}
                  {e.stats?.mean_confidence != null ? ` · OCR conf ${e.stats.mean_confidence}` : ""}
                </div>
              </td>
              <td>{e.party_id}</td>
              <td>
                <Chip color={e.status === "ok" ? "green" : "red"} label={e.status} />
                <div className="muted">{e.elapsed_ms} ms</div>
              </td>
              <td>
                {Object.entries(e.fields).map(([k, v]) => (
                  <div key={k}>
                    <code>{k}</code> {v}
                  </div>
                ))}
                {e.error && <div className="reason fail">{e.error}</div>}
              </td>
              <td>
                {e.dropped.map((d) => (
                  <div key={d.field} className="reason warn">
                    <code>{d.field}</code> “{d.value}”
                  </div>
                ))}
                {e.extracted_json && <div className="muted">{e.extracted_json}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
