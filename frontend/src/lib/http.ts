/** Shared helpers for the API clients. */

export const OFFLINE_MESSAGE = "The analysis service is not reachable. Start the backend (see README.md), then reload.";
export const WRONG_SERVICE_MESSAGE = "A different service is answering on the API port, not the PigmentCal-UQ backend. Stop it or start this backend on that port (see README.md), then reload.";

/** The dev/preview proxy answers 502/503/504 when the backend is down; that is "not reachable", not an unexpected server error. */
export const gatewayDown = (status: number) => status === 502 || status === 503 || status === 504;

/** Message for a non-OK response that carried no usable error body. */
export const failMessage = (status: number, fallback: string) => (gatewayDown(status) ? OFFLINE_MESSAGE : fallback);

/** The "not there yet" envelope is { available: false, errors: [...] } (HTTP 200). Status payloads that merely contain an `available` flag are not that envelope. */
export function unavailableMessage(body: unknown): string | null {
  const b = body as { available?: boolean; errors?: { message?: string }[] } | null;
  return b && b.available === false && Array.isArray(b.errors) ? b.errors[0]?.message ?? "Not available." : null;
}
