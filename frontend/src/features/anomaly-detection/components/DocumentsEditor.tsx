import { sizeLabel } from "../../../lib/uploads";
import type { DocumentUpload } from "../../../types/api";
import { DOC_TYPES } from "../../../types/api";

interface Props {
  documents: DocumentUpload[];
  partyIds: string[];
  partyLabels: Record<string, string>;
  onChange: (documents: DocumentUpload[]) => void;
}

export function DocumentsEditor({ documents, partyIds, partyLabels, onChange }: Props) {
  const set = (index: number, patch: Partial<DocumentUpload>) =>
    onChange(documents.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  const remove = (index: number) => onChange(documents.filter((_, i) => i !== index));

  if (documents.length === 0) {
    return <p className="muted">No documents yet. Upload every file of the applicant and co-applicants at once.</p>;
  }
  return (
    <table className="findings docs-table">
      <thead>
        <tr>
          <th>File</th>
          <th style={{ width: 230 }}>Person</th>
          <th style={{ width: 200 }}>Document type</th>
          <th style={{ width: 90 }}>Size</th>
          <th style={{ width: 70 }} />
        </tr>
      </thead>
      <tbody>
        {documents.map((d, i) => (
          <tr key={`${d.file.name}-${i}`} className={partyIds.includes(d.party_id) ? "" : "invalid"}>
            <td>{d.file.name}</td>
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
              <select value={d.doc_type} onChange={(e) => set(i, { doc_type: e.target.value as DocumentUpload["doc_type"] })}>
                {DOC_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </td>
            <td className="muted">{sizeLabel(d.file)}</td>
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
