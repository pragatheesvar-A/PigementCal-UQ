import { WRONG_SERVICE_MESSAGE, failMessage } from "./http";

export type ResearchState = "NO_DATA" | "SOFTWARE_TEST_DATA" | "SIMULATED_HARDWARE_DATA" | "UNVERIFIED_EXTERNAL_DATA" | "UNVERIFIED_DATA" | "VERIFIED_RESEARCH_DATA" | "RESEARCH_RESULTS";

export interface Health {
  status: string;
  version: string;
  dataset: { loaded: boolean; verified?: boolean; rows: number; participants: number; note: string };
  /** The backend's authoritative research-status decision. The frontend only displays it. */
  research_status?: { state: ResearchState; label: string; results_allowed: boolean; verified_data: boolean; failed_checks: string[] };
  model: { trained: boolean; note: string };
  conformal?: { calibrated: boolean };
}

/** Only this application's own health answer is accepted: a 200 from some other service on the same port must not be treated as the backend. */
export async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error(failMessage(res.status, `The analysis service answered with an error (HTTP ${res.status}).`));
  const h = await res.json().catch(() => null);
  if (!h || h.app !== "PigmentCal-UQ" || typeof h.dataset !== "object" || h.dataset === null) throw new Error(WRONG_SERVICE_MESSAGE);
  return h as Health;
}
