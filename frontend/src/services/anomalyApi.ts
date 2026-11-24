import { appConfig } from "../config/appConfig";
import type { AutofillResponse, CasePayload, DocumentIn, Lead, OcrJson, RunResult } from "../types/api";
import { requestJson } from "./apiClient";

const enc = encodeURIComponent;

export interface BackendInfo {
  environment: string;
  region: string;
  model_id: string;
  third_party: string;
}

export const anomalyApi = {
  info: () => requestJson<BackendInfo>("/v1/info"),
  samples: () => requestJson<string[]>("/v1/samples"),
  sample: (name: string) => requestJson<CasePayload>(`/v1/samples/${enc(name)}`),
  autofill: (input: { ocr?: OcrJson; raw_ocr?: string }, applicantName: string, coNames: string[]) =>
    requestJson<AutofillResponse>(
      "/v1/lead/autofill",
      { method: "POST", body: JSON.stringify({ ...input, applicant_name: applicantName || null, co_applicant_names: coNames }) },
      appConfig.autofillTimeoutMs,
    ),
  createLead: (caseId: string, lead: Lead) =>
    requestJson<{ case_id: string; created_at: string }>(`/v1/cases/${enc(caseId)}/lead`, {
      method: "POST",
      body: JSON.stringify({ lead }),
    }),
  trigger: (caseId: string, documents: DocumentIn[], mockOverrides: Record<string, unknown>) =>
    requestJson<RunResult>(
      `/v1/cases/${enc(caseId)}/trigger`,
      { method: "POST", body: JSON.stringify({ documents, mock_overrides: mockOverrides }) },
      appConfig.triggerTimeoutMs,
    ),
  result: (caseId: string) => requestJson<RunResult>(`/v1/cases/${enc(caseId)}/result`),
};
