import { COLOR_LABEL } from "../../../lib/colors";
import type { Color, RunResult } from "../../../types/api";
import { Extraction, PartySection } from "./PartyResults";
import { Chip } from "./ResultAtoms";

export function ResultView({ run }: { run: RunResult }) {
  const r = run.results.anomaly_detection;
  const s = r.summary;
  const o = run.orchestrator;
  return (
    <section className="card result">
      <div className="row-between">
        <h2>
          Result · {r.case_id} <Chip color={s.overall_color} label={`Overall: ${COLOR_LABEL[s.overall_color]}`} />
        </h2>
        <span className="muted">
          {run.run_id} · {r.timing_ms ? `${(r.timing_ms.total / 1000).toFixed(1)} s` : ""}
        </span>
      </div>

      <div className="callout info">
        <b>Orchestrator Agent</b>{" "}
        <span className="muted">
          ({o.summary_source === "llm" ? "LLM summary" : "template summary"}
          {o.fallback ? ", tool called directly (fallback)" : `, called ${o.tools_called.join(", ")}`})
        </span>
        <p>{o.summary}</p>
      </div>

      <div className="summary">
        <div className="stat">
          <b>{s.total_checks}</b> checks · <b>{s.pairs_compared}</b> pairs
        </div>
        {(["red", "yellow", "grey", "green"] as Color[]).map((c) => (
          <div key={c} className="stat">
            <Chip color={c} /> <b>{s.counts[c]}</b>
          </div>
        ))}
        <div className="stat">
          <b>{s.high_severity_flags}</b> high-severity flags
        </div>
        <div className="stat">
          <b>{s.critical_flags}</b> critical
        </div>
      </div>

      {(r.sanction_conditions.length > 0 || r.cm_justifications.length > 0) && (
        <div className="callouts">
          {r.sanction_conditions.length > 0 && (
            <div className="callout warn">
              <b>Sanction conditions</b>
              <ul>
                {r.sanction_conditions.map((c, i) => (
                  <li key={i}>
                    {c.party_id}: {c.condition} ({c.rule_id})
                  </li>
                ))}
              </ul>
            </div>
          )}
          {r.cm_justifications.length > 0 && (
            <div className="callout fail">
              <b>CM justification required</b>
              <ul>
                {r.cm_justifications.map((c, i) => (
                  <li key={i}>
                    {c.party_id} ({c.rule_id}): {c.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <h3>Anomalies ({r.anomalies.length})</h3>
      {r.anomalies.length === 0 ? (
        <p className="muted">No anomalies found.</p>
      ) : (
        <table className="findings">
          <thead>
            <tr>
              <th style={{ width: 120 }}>Result</th>
              <th style={{ width: 130 }}>Party</th>
              <th style={{ width: 300 }}>Check</th>
              <th style={{ width: 64 }}>Rule</th>
              <th style={{ width: 74 }}>Severity</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {r.anomalies.map((a) => (
              <tr key={a.check_id}>
                <td>
                  <Chip color={a.color} />
                  {a.critical && <span className="chip red critical">CRITICAL</span>}
                </td>
                <td>{a.party_id}</td>
                <td>{a.title}</td>
                <td>{a.rule_id ?? "—"}</td>
                <td>{a.severity ?? "—"}</td>
                <td>
                  {a.message}
                  {a.mitigant && <div className="mitigant">Mitigant: {a.mitigant}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>By party, in check order (click a row for the pair-by-pair comparison)</h3>
      {r.parties.map((p, i) => (
        <PartySection key={p.party_id} party={p} step={i + 1} />
      ))}
      <Extraction report={r} />
      {Boolean(r.config.third_party_is_mock) && (
        <p className="muted">Third-party results (bureau, Karza, email ownership, face match) are mocked.</p>
      )}
    </section>
  );
}
