import type { PartyBlock } from "../../../types/api";
import { Chip } from "./ResultAtoms";

const STATUS_LABEL = { done: "Done", one_source: "Only one source", no_data: "No data" } as const;

/** Per-person checklist: every configured check, whether it was done and its result. */
export function Checklist({ parties }: { parties: PartyBlock[] }) {
  return (
    <div className="checklist">
      {parties.map((p) => (
        <div key={p.party_id} className="truth">
          <h4>
            {p.label} · {p.name} <Chip color={p.status_color} />
          </h4>
          <table className="findings">
            <thead>
              <tr>
                <th>Check</th>
                <th style={{ width: 150 }}>Status</th>
                <th style={{ width: 120 }}>Result</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {p.checklist.map((c) => (
                <tr key={c.item}>
                  <td>{c.item}</td>
                  <td>{STATUS_LABEL[c.status]}</td>
                  <td>{c.color ? <Chip color={c.color} /> : <span className="muted">—</span>}</td>
                  <td className="muted">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
