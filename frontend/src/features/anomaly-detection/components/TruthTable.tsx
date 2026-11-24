import type { TruthTableData } from "../../../types/api";
import { Chip } from "./ResultAtoms";

/** Renders the truth table JSON built by the backend: one row per source, one column per field. */
function PartyTruthTable({ table }: { table: TruthTableData }) {
  return (
    <div className="truth">
      <h4>
        {table.label} · {table.name} <Chip color={table.status_color} />
      </h4>
      {table.columns.length === 0 ? (
        <p className="muted">No fields to compare.</p>
      ) : (
        <div className="truth-scroll">
          <table className="truth-table">
            <thead>
              <tr>
                <th className="src">Source</th>
                {table.columns.map((c) => (
                  <th key={c.id} title={c.title}>
                    <div>{c.label}</div>
                    {c.color ? <Chip color={c.color} /> : <Chip color="grey" label="1 source" />}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r) => (
                <tr key={r.key} className={r.is_lead ? "lead-row" : ""}>
                  <th className="src">
                    <div>{r.label}</div>
                    <div className="muted">{r.sub}</div>
                  </th>
                  {table.columns.map((c) => {
                    const cell = table.cells[`${r.key}|${c.id}`];
                    if (!cell) return <td key={c.id} className="empty" />;
                    return (
                      <td key={c.id}>
                        <div className={`tcell ${cell.color}`} title={`${cell.value}\n${cell.note}`}>
                          <span className="mark">{cell.mark}</span>
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
      {table.third_party.length > 0 && (
        <div className="truth-third">
          <span className="muted">Third-party checks (mock):</span>
          {table.third_party.map((t) => (
            <span key={t.check_id} title={t.message}>
              <Chip color={t.color} label={t.label} />
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function TruthTable({ tables }: { tables: TruthTableData[] }) {
  return (
    <div>
      <div className="truth-legend muted">
        <span>★ base (first source of the column)</span>
        <span>✓ match</span>
        <span>≈ review</span>
        <span>✗ mismatch</span>
        <span>– not compared</span>
        <span>🔒 masked</span>
        <span>• only source</span>
        <span>Hover a cell for the reason.</span>
      </div>
      {tables.map((t) => (
        <PartyTruthTable key={t.party_id} table={t} />
      ))}
    </div>
  );
}
