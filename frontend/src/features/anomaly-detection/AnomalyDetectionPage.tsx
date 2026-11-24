import { useEffect, useMemo, useRef, useState } from "react";
import { isAccepted, payloadToUploads, readFileText, toUploads } from "../../lib/uploads";
import { anomalyApi } from "../../services/anomalyApi";
import type { AutofillResponse, BackendInfo, CasePayload, CoApplicantLead, DocumentUpload, Lead, RunResult } from "../../types/api";
import { RELATIONSHIPS } from "../../types/api";
import { DocumentsEditor } from "./components/DocumentsEditor";
import { LeadForm } from "./components/LeadForm";
import { ResultView } from "./components/ResultView";

const EMPTY_LEAD: Lead = { applicant: { name: "" }, co_applicants: [] };
const CASE_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

/** What to upload in each mode (the backend decides the mode). */
const UPLOAD_HINT: Record<BackendInfo["mode"], string> = {
  vision_llm: "PDF or images (PNG, JPG). The vision LLM reads them.",
  structured: "Structured JSON (key-value pairs): one file per document, or one case file with every person's documents. No LLM is used.",
  ocr_llm: "Raw OCR JSON ({pages: [...]}) or plain text. The LLM reads and compares.",
  ocr_hybrid: "Raw OCR JSON ({pages: [...]}) or plain text. The LLM reads, cross_verify compares.",
};

/** Empty inputs are sent as null so the backend sees "not provided". */
function cleanLead(lead: Lead): Lead {
  const blank = <T extends object>(o: T): T =>
    Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === "string" && v.trim() === "" ? null : v])) as T;
  return { ...blank(lead), applicant: blank(lead.applicant), co_applicants: lead.co_applicants.map(blank) };
}

function leadFromAutofill(res: AutofillResponse, applicantName: string, coNames: string[]): Lead {
  const cos: CoApplicantLead[] = res.lead.co_applicants.map((c, i) => ({
    ...c,
    party_id: c.party_id,
    relationship: (RELATIONSHIPS as readonly string[]).includes(String(c.relationship)) ? c.relationship! : "other",
    name: c.name ?? coNames[i] ?? "",
  }));
  for (let i = cos.length; i < coNames.length; i += 1) {
    if (coNames[i].trim()) cos.push({ party_id: `co_applicant_${i + 1}`, relationship: "other", name: coNames[i].trim() });
  }
  return {
    application_no: res.lead.application_no ?? null,
    lead_id: res.lead.lead_id ?? null,
    applicant: { ...res.lead.applicant, name: res.lead.applicant.name ?? applicantName },
    co_applicants: cos,
  };
}

function autofillMessage(res: AutofillResponse, fileName: string): string {
  const masked = res.dropped.filter((d) => d.reason === "MASKED");
  const missing = res.dropped.filter((d) => d.reason !== "MASKED");
  const list = (items: typeof res.dropped) => items.map((d) => d.field).join(", ");
  return [
    `Auto-filled ${Object.keys(res.grounding).length} field(s) from ${fileName} in ${(res.elapsed_ms / 1000).toFixed(1)} s (${res.mode}).`,
    masked.length ? `${masked.length} value(s) masked by a PII guardrail (enter them by hand): ${list(masked)}.` : "",
    missing.length ? `${missing.length} value(s) dropped (not found in the file): ${list(missing)}.` : "",
    ...res.warnings,
    res.stored.length ? `Stored: ${res.stored.join(", ")}.` : "",
    "Review every field before creating the lead.",
  ]
    .filter(Boolean)
    .join(" ");
}

export function AnomalyDetectionPage() {
  const [info, setInfo] = useState<BackendInfo | null>(null);
  const [health, setHealth] = useState("checking backend…");
  const [samples, setSamples] = useState<string[]>([]);
  const [caseId, setCaseId] = useState("");
  const [applicantName, setApplicantName] = useState("");
  const [coNames, setCoNames] = useState<string[]>([]);
  const [lead, setLead] = useState<Lead>(EMPTY_LEAD);
  const [grounding, setGrounding] = useState<Record<string, string>>({});
  const [autofillInfo, setAutofillInfo] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentUpload[]>([]);
  const [overridesText, setOverridesText] = useState("{}");
  const [leadSavedFor, setLeadSavedFor] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "autofill" | "lead" | "trigger" | "load">("");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<RunResult | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  const isOcr = info?.mode === "ocr_llm" || info?.mode === "ocr_hybrid";
  const accepts = info?.accepts ?? [];

  useEffect(() => {
    anomalyApi
      .info()
      .then((h) => {
        setInfo(h);
        const models = [h.application_form_model, h.documents_model].filter(Boolean).join(" / ") || "no LLM";
        setHealth(`backend ok · ${h.environment} · ${h.mode} · ${models} · ${h.region} · third-party: ${h.third_party}`);
        if (h.mode === "ocr_llm" || h.mode === "ocr_hybrid") anomalyApi.samples().then(setSamples).catch(() => setSamples([]));
      })
      .catch(() => setHealth("backend not reachable"));
  }, []);

  useEffect(() => {
    if (busy !== "trigger" && busy !== "autofill") return;
    const started = Date.now();
    const t = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => clearInterval(t);
  }, [busy]);

  const partyIds = useMemo(() => ["applicant", ...lead.co_applicants.map((c) => c.party_id)], [lead]);
  const partyLabels = useMemo(
    () =>
      Object.fromEntries([
        ["applicant", `applicant · ${lead.applicant.name || "—"}`],
        ...lead.co_applicants.map((c) => [c.party_id, `${c.party_id} · ${c.relationship} · ${c.name || "—"}`]),
      ]) as Record<string, string>,
    [lead],
  );
  const caseIdValid = CASE_ID.test(caseId.trim());
  const leadReady = leadSavedFor !== null && leadSavedFor === caseId.trim();
  const fail = (prefix: string) => (e: unknown) => setError(`${prefix}: ${(e as Error).message}`);
  const refused = (files: File[]) => files.filter((f) => !isAccepted(f, accepts)).map((f) => f.name);

  const onLoadSample = async (name: string) => {
    if (!name) return;
    setBusy("load");
    setError(null);
    try {
      const p: CasePayload = await anomalyApi.sample(name);
      setCaseId(p.case_id);
      setApplicantName(p.lead.applicant.name);
      setCoNames(p.lead.co_applicants.map((c) => c.name));
      setLead(p.lead);
      setGrounding({});
      setAutofillInfo(name.startsWith("local_") ? "Sample loaded (local case data, not auto-filled)." : "Sample loaded (synthetic data, not auto-filled).");
      setDocuments(payloadToUploads(p));
      setOverridesText(JSON.stringify(p.mock_overrides ?? {}, null, 2));
      setLeadSavedFor(null);
      setRun(null);
    } catch (e) {
      fail("Load sample")(e);
    } finally {
      setBusy("");
    }
  };

  const onApplicationForm = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (refused([file]).length) {
      setError(`This mode accepts ${accepts.join(", ")} files only.`);
      return;
    }
    setElapsed(0);
    setBusy("autofill");
    try {
      const res = await anomalyApi.autofill(file, caseId.trim(), applicantName.trim(), coNames.map((n) => n.trim()));
      setLead(leadFromAutofill(res, applicantName.trim(), coNames));
      setGrounding(res.grounding);
      setCaseId(res.case_id);
      setAutofillInfo(autofillMessage(res, file.name));
      setLeadSavedFor(null);
    } catch (e) {
      fail("Auto-fill failed")(e);
    } finally {
      setBusy("");
    }
  };

  const onCreateLead = async () => {
    setError(null);
    setBusy("lead");
    try {
      const id = caseId.trim();
      await anomalyApi.createLead(id, cleanLead(lead));
      setLeadSavedFor(id);
    } catch (e) {
      fail("Create lead failed")(e);
    } finally {
      setBusy("");
    }
  };

  const onDocumentFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const list = Array.from(files);
    const bad = refused(list);
    setError(bad.length ? `Not accepted in this mode (${accepts.join(", ")}): ${bad.join(", ")}` : null);
    const added = toUploads(list.filter((f) => isAccepted(f, accepts)), lead.co_applicants);
    setDocuments((prev) => [...prev.filter((d) => !added.some((a) => a.file.name === d.file.name)), ...added]);
  };

  const onPayloadFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    try {
      const p = JSON.parse(await readFileText(file)) as Partial<CasePayload>;
      if (!Array.isArray(p.documents)) throw new Error('the JSON needs a "documents" list');
      setDocuments(payloadToUploads({ documents: p.documents }));
      if (p.mock_overrides) setOverridesText(JSON.stringify(p.mock_overrides, null, 2));
    } catch (e) {
      fail("Payload upload failed")(e);
    }
  };

  const onTrigger = async () => {
    setError(null);
    let overrides: Record<string, unknown>;
    try {
      overrides = JSON.parse(overridesText || "{}");
    } catch {
      setError("Mock overrides are not valid JSON.");
      return;
    }
    setElapsed(0);
    setBusy("trigger");
    try {
      const res = await anomalyApi.trigger(caseId.trim(), documents, overrides);
      setRun(res);
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (e) {
      fail("Trigger failed")(e);
    } finally {
      setBusy("");
    }
  };

  const onLoadResult = async () => {
    setError(null);
    try {
      setRun(await anomalyApi.result(caseId.trim()));
    } catch (e) {
      fail("No result")(e);
    }
  };

  return (
    <div className="page">
      <header>
        <div>
          <h1>Underwriting Copilot · Anomaly Detection</h1>
          <div className="muted">Orchestrator Agent → Anomaly Detection Agent (KYC &amp; identity) · {info?.mode_label ?? "…"}</div>
        </div>
        <div className="health">{health}</div>
      </header>

      <section className="card">
        <div className="row-between">
          <h2>1 · Create lead (base truth)</h2>
          {isOcr && samples.length > 0 && (
            <select value="" onChange={(e) => onLoadSample(e.target.value)} disabled={busy !== ""}>
              <option value="">Load sample…</option>
              {samples.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="grid">
          <label>
            <span>Case ID (empty: taken from the form)</span>
            <input value={caseId} placeholder="e.g. CASE-0001" className={caseId && !caseIdValid ? "bad" : ""}
              onChange={(e) => setCaseId(e.target.value)} />
          </label>
          <label>
            <span>Applicant name</span>
            <input value={applicantName} onChange={(e) => setApplicantName(e.target.value)} />
          </label>
          {coNames.map((n, i) => (
            <label key={i}>
              <span>
                Co-applicant {i + 1} name{" "}
                <button type="button" className="link danger" onClick={() => setCoNames(coNames.filter((_, j) => j !== i))}>
                  ×
                </button>
              </span>
              <input value={n} onChange={(e) => setCoNames(coNames.map((x, j) => (j === i ? e.target.value : x)))} />
            </label>
          ))}
          <div className="add-co">
            <button type="button" className="secondary" onClick={() => setCoNames([...coNames, ""])}>
              + Co-applicant name
            </button>
          </div>
        </div>

        <div className="upload-row">
          <label className="upload">
            <input type="file" accept={accepts.join(",")} disabled={busy !== "" || !info}
              onChange={(e) => { onApplicationForm(e.target.files?.[0]); e.target.value = ""; }} />
            <span className="button-like">{busy === "autofill" ? `Reading application form… ${elapsed}s` : "Upload application form → auto-fill"}</span>
          </label>
          <span className="muted">{info ? UPLOAD_HINT[info.mode] : ""}</span>
        </div>
        {autofillInfo && <div className="info-line">{autofillInfo}</div>}

        <LeadForm lead={lead} grounding={grounding} onChange={(l) => { setLead(l); setLeadSavedFor(null); }} />

        <div className="actions">
          <button type="button" onClick={onCreateLead} disabled={busy !== "" || !caseIdValid || !lead.applicant.name.trim()}>
            {busy === "lead" ? "Saving…" : "Create lead"}
          </button>
          {leadReady && <span className="ok">Lead saved for {leadSavedFor}. This is the base truth for the comparison.</span>}
        </div>
      </section>

      <section className={`card ${leadReady ? "" : "dimmed"}`}>
        <h2>2 · Documents (every file of every person, one shot)</h2>
        <div className="upload-row">
          <label className="upload">
            <input type="file" accept={accepts.join(",")} multiple onChange={(e) => { onDocumentFiles(e.target.files); e.target.value = ""; }} />
            <span className="button-like secondary">Upload documents (select all)</span>
          </label>
          {isOcr && (
            <label className="upload">
              <input type="file" accept=".json" onChange={(e) => { onPayloadFile(e.target.files?.[0]); e.target.value = ""; }} />
              <span className="button-like secondary">…or one payload JSON ({"{documents: [...]}"})</span>
            </label>
          )}
          {documents.length > 0 && (
            <button type="button" className="link danger" onClick={() => setDocuments([])}>
              Clear all
            </button>
          )}
        </div>
        <p className="muted">{info ? UPLOAD_HINT[info.mode] : ""} Person and document type are guessed from the file name. Check them before triggering.</p>
        <DocumentsEditor documents={documents} partyIds={partyIds} partyLabels={partyLabels} onChange={setDocuments} />
        <details className="overrides">
          <summary>Mock third-party responses (optional overrides)</summary>
          <p className="muted">
            Keyed by party_id. Fields: bureau {"{name, dob, addresses:[{address, reported_on}]}"}, pan_aadhaar_linked, voter_dl{" "}
            {"{status, verified_on}"}, email_ownership_verified, face_match {"{match_pct, status}"}.
          </p>
          <textarea rows={8} value={overridesText} onChange={(e) => setOverridesText(e.target.value)} />
        </details>
      </section>

      <section className="card">
        <h2>3 · Trigger</h2>
        <p className="muted">
          Backend → Orchestrator Agent → Anomaly Detection Agent ({info?.mode_label ?? "…"}): applicant, father, mother, other
          co-applicants → mocked third-party checks → checklist, truth table and JSON.
        </p>
        <div className="actions">
          <button type="button" className="primary" onClick={onTrigger} disabled={busy !== "" || !leadReady || documents.length === 0}>
            {busy === "trigger" ? `Running… ${elapsed}s` : "Trigger"}
          </button>
          <button type="button" className="secondary" onClick={onLoadResult} disabled={busy !== "" || !caseIdValid}>
            Load last result
          </button>
          {!leadReady && <span className="muted">Create the lead for this case ID first.</span>}
        </div>
        {error && <div className="error">{error}</div>}
      </section>

      <div ref={resultRef}>{run && <ResultView run={run} />}</div>
    </div>
  );
}
