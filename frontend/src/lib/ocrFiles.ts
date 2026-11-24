import type { CoApplicantLead, DocType, DocumentIn, OcrJson } from "../types/api";

export function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("could not read the file"));
    reader.readAsText(file);
  });
}

export function isOcrJson(value: unknown): value is OcrJson {
  return typeof value === "object" && value !== null && Array.isArray((value as OcrJson).pages);
}

/** Reads a .json OCR file ({pages: [...]}) or a .txt file (plain OCR text). */
export async function readOcrFile(file: File): Promise<{ ocr?: OcrJson; raw_ocr?: string }> {
  const text = await readFileText(file);
  if (file.name.toLowerCase().endsWith(".json")) {
    const parsed: unknown = JSON.parse(text);
    if (!isOcrJson(parsed)) throw new Error(`${file.name}: not an OCR JSON (no "pages" list)`);
    return { ocr: parsed };
  }
  return { raw_ocr: text };
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

export async function filesToDocuments(files: File[], coApplicants: CoApplicantLead[]): Promise<DocumentIn[]> {
  const out: DocumentIn[] = [];
  for (const f of files) {
    const content = await readOcrFile(f);
    out.push({ party_id: guessParty(f.name, coApplicants), doc_type: guessDocType(f.name), file_name: f.name, ...content });
  }
  return out;
}

export function ocrStats(d: DocumentIn): string {
  if (d.ocr) {
    const lines = d.ocr.pages.reduce((n, p) => n + (p.text_lines?.length ?? 0), 0);
    return `${d.ocr.pages.length} page(s), ${lines} line(s)`;
  }
  return `${(d.raw_ocr ?? "").length} characters of text`;
}
