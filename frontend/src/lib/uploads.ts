import type { CasePayload, CoApplicantLead, DocType, DocumentUpload } from "../types/api";

export function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("could not read the file"));
    reader.readAsText(file);
  });
}

export function guessDocType(fileName: string): DocType {
  const n = fileName.toLowerCase();
  if (/pan ?card|\bpan\b|pancard/.test(n)) return "PAN";
  if (/aadh?aa?r|adhar/.test(n)) return "AADHAAR";
  if (/passport/.test(n)) return "PASSPORT";
  if (/voter/.test(n)) return "VOTER_ID";
  if (/driving|licen[cs]e|\bdl\b/.test(n)) return "DRIVING_LICENCE";
  if (/offer|admit|admission/.test(n)) return "ADMIT_LETTER";
  if (/degree|graduat|certificate/.test(n)) return "DEGREE_CERTIFICATE";
  if (/10th|12th|mark ?sheet|academic|transcript|ssc|hsc/.test(n)) return "MARKSHEET";
  return "OTHER";
}

export function guessParty(fileName: string, coApplicants: CoApplicantLead[]): string {
  const n = fileName.toLowerCase();
  const num = n.match(/co[\s_-]*app(?:licant)?[\s_-]*(\d)/);
  if (num) return `co_applicant_${num[1]}`;
  for (const rel of ["father", "mother"] as const) {
    if (n.includes(rel)) {
      const c = coApplicants.find((x) => x.relationship === rel);
      if (c) return c.party_id;
    }
  }
  if (/co[\s_-]*app/.test(n) && coApplicants[0]) return coApplicants[0].party_id;
  return "applicant";
}

/** True when the file name ends with one of the extensions the backend accepts. */
export function isAccepted(file: File, accepts: string[]): boolean {
  const name = file.name.toLowerCase();
  return accepts.some((ext) => name.endsWith(ext));
}

/** Uploaded files with the person and document type guessed from each name. */
export function toUploads(files: File[], coApplicants: CoApplicantLead[]): DocumentUpload[] {
  return files.map((file) => ({ file, party_id: guessParty(file.name, coApplicants), doc_type: guessDocType(file.name) }));
}

/** A payload or sample JSON ({documents: [...]}) becomes one OCR JSON file per document. */
export function payloadToUploads(payload: Pick<CasePayload, "documents">): DocumentUpload[] {
  return payload.documents.map((d) => {
    const isText = d.ocr === undefined && typeof d.raw_ocr === "string";
    const name = isText ? d.file_name.replace(/\.[^.]*$/, "") + ".txt" : d.file_name.replace(/\.[^.]*$/, "") + ".json";
    const body = isText ? String(d.raw_ocr) : JSON.stringify(d.ocr ?? {});
    const file = new File([body], name, { type: isText ? "text/plain" : "application/json" });
    return { file, party_id: d.party_id, doc_type: d.doc_type };
  });
}

export function sizeLabel(file: File): string {
  const kb = file.size / 1024;
  return kb < 1024 ? `${Math.max(1, Math.round(kb))} KB` : `${(kb / 1024).toFixed(1)} MB`;
}
