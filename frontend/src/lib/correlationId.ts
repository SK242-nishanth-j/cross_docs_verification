/**
 * Create an ID for the X-Correlation-ID header (32 hex characters).
 * Uses getRandomValues because randomUUID needs a secure context.
 */
export function newCorrelationId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
