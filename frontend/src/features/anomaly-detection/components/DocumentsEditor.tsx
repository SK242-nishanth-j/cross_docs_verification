import { ocrStats } from "../../../lib/ocrFiles";
import type { DocumentIn } from "../../../types/api";
import { DOC_TYPES } from "../../../types/api";

interface Props {
  documents: DocumentIn[];
  partyIds: string[];
  partyLabels: Record<string, string>;
  onChange: (documents: DocumentIn[]) => void;
}

export function DocumentsEditor({ documents, partyIds, partyLabels, onChange }: Props) {
  const set = (index: number, patch: Partial<DocumentIn>) =>
    onChange(documents.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  const remove = (index: number) => onChange(documents.filter((_, i) => i !== index));

  if (documents.length === 0) {
    return <p className="muted">No documents yet. Upload the OCR JSON files (all at once), or one payload JSON.</p>;
  }
  return (
    <table className="findings docs-table">
      <thead>
        <tr>
          <th>File</th>
          <th style={{ width: 230 }}>Party</th>
          <th style={{ width: 200 }}>Document type</th>
          <th style={{ width: 170 }}>OCR</th>
          <th style={{ width: 70 }} />
        </tr>
      </thead>
      <tbody>
        {documents.map((d, i) => (
          <tr key={`${d.file_name}-${i}`} className={partyIds.includes(d.party_id) ? "" : "invalid"}>
            <td>{d.file_name}</td>
            <td>
              <select value={d.party_id} onChange={(e) => set(i, { party_id: e.target.value })}>
                {[...new Set([...partyIds, d.party_id])].map((p) => (
                  <option key={p} value={p}>
                    {partyLabels[p] ?? `${p} (not in lead)`}
                  </option>
                ))}
              </select>
            </td>
            <td>
              <select value={d.doc_type} onChange={(e) => set(i, { doc_type: e.target.value as DocumentIn["doc_type"] })}>
                {DOC_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </td>
            <td className="muted">{ocrStats(d)}</td>
            <td>
              <button type="button" className="link danger" onClick={() => remove(i)}>
                Remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
