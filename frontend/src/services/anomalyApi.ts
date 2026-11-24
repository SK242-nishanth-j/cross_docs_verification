import { appConfig } from "../config/appConfig";
import type { AutofillResponse, BackendInfo, CasePayload, DocumentUpload, Lead, RunResult } from "../types/api";
import { requestJson } from "./apiClient";

const enc = encodeURIComponent;

export const anomalyApi = {
  info: () => requestJson<BackendInfo>("/v1/info"),
  samples: () => requestJson<string[]>("/v1/samples"),
  sample: (name: string) => requestJson<CasePayload>(`/v1/samples/${enc(name)}`),
  /** Upload the application form; the backend reads it in the configured mode. */
  autofill: (file: File, caseId: string, applicantName: string, coNames: string[]) => {
    const form = new FormData();
    form.append("file", file);
    form.append("case_id", caseId);
    form.append("applicant_name", applicantName);
    form.append("co_applicant_names", JSON.stringify(coNames));
    return requestJson<AutofillResponse>("/v1/lead/autofill", { method: "POST", body: form }, appConfig.autofillTimeoutMs);
  },
  createLead: (caseId: string, lead: Lead) =>
    requestJson<{ case_id: string; created_at: string }>(`/v1/cases/${enc(caseId)}/lead`, {
      method: "POST",
      body: JSON.stringify({ lead }),
    }),
  /** Upload every document in one shot, with the person and type of each file. */
  trigger: (caseId: string, documents: DocumentUpload[], mockOverrides: Record<string, unknown>) => {
    const form = new FormData();
    documents.forEach((d) => form.append("files", d.file, d.file.name));
    form.append(
      "documents",
      JSON.stringify(documents.map((d) => ({ file_name: d.file.name, party_id: d.party_id, doc_type: d.doc_type }))),
    );
    form.append("mock_overrides", JSON.stringify(mockOverrides));
    return requestJson<RunResult>(`/v1/cases/${enc(caseId)}/trigger`, { method: "POST", body: form }, appConfig.triggerTimeoutMs);
  },
  result: (caseId: string) => requestJson<RunResult>(`/v1/cases/${enc(caseId)}/result`),
};
