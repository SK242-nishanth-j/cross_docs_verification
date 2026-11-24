import { appConfig } from "../config/appConfig";
import { newCorrelationId } from "../lib/correlationId";

/** An error whose message is safe to show to the user. */
export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface ValidationItem {
  loc?: unknown[];
  msg?: string;
}

function detailMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return (detail as ValidationItem[]).map((d) => `${(d.loc ?? []).join(".")}: ${d.msg ?? ""}`).join(" | ");
  }
  return `The server answered with HTTP ${status}.`;
}

/**
 * Send a JSON request with a timeout and an X-Correlation-ID header.
 * Throws ApiError with a user-safe message on failure.
 */
export async function requestJson<T>(path: string, init: RequestInit = {}, timeoutMs = appConfig.defaultTimeoutMs): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${appConfig.apiBaseUrl}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-Correlation-ID": newCorrelationId(), ...(init.headers ?? {}) },
    });
    const text = await res.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    if (!res.ok) throw new ApiError(detailMessage(body, res.status), res.status);
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(`The request took longer than ${Math.round(timeoutMs / 1000)} s and was stopped.`);
    }
    throw new ApiError("The backend could not be reached.");
  } finally {
    clearTimeout(timer);
  }
}
