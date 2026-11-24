/**
 * Build-time settings from VITE_* variables (see .env.example). Nothing here is
 * secret: every value ends up in the browser bundle.
 */
function readMs(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export const appConfig = {
  /** Backend base URL; empty means same-origin requests (dev proxy or reverse proxy). */
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, ""),
  /** The auto-fill call includes one LLM read of the whole application form. */
  autofillTimeoutMs: readMs(import.meta.env.VITE_AUTOFILL_TIMEOUT_MS, 300_000),
  /** The trigger includes one LLM read per document plus the orchestrator. */
  triggerTimeoutMs: readMs(import.meta.env.VITE_TRIGGER_TIMEOUT_MS, 600_000),
  defaultTimeoutMs: readMs(import.meta.env.VITE_DEFAULT_TIMEOUT_MS, 30_000),
} as const;
