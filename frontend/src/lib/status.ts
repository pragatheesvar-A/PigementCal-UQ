import type { Health, ResearchState } from "./api";

/** Short header labels. The decision itself is made by the backend gate (GET /api/research/status); this file only maps it to text.
 *  Nothing here can upgrade a status: a missing or unknown backend value is shown as UNVERIFIED DATA. */
export type ResearchStatus =
  | "STATUS UNKNOWN" | "NO RESEARCH DATA" | "SOFTWARE TEST DATA" | "SIMULATED HARDWARE DATA" | "UNVERIFIED EXTERNAL DATA" | "UNVERIFIED DATA"
  | "VERIFIED RESEARCH DATA" | "REAL RESEARCH RESULTS";

const BY_STATE: Record<ResearchState, ResearchStatus> = {
  NO_DATA: "NO RESEARCH DATA",
  SOFTWARE_TEST_DATA: "SOFTWARE TEST DATA",
  SIMULATED_HARDWARE_DATA: "SIMULATED HARDWARE DATA",
  UNVERIFIED_EXTERNAL_DATA: "UNVERIFIED EXTERNAL DATA",
  UNVERIFIED_DATA: "UNVERIFIED DATA",
  VERIFIED_RESEARCH_DATA: "VERIFIED RESEARCH DATA",
  RESEARCH_RESULTS: "REAL RESEARCH RESULTS",
};

export const labelForState = (s?: string): ResearchStatus => (s && BY_STATE[s as ResearchState]) || "UNVERIFIED DATA";   // anything unexpected is never shown as better than unverified

export function researchStatus(h: Health | null): ResearchStatus {
  if (!h) return "STATUS UNKNOWN";                                     // service not reachable yet: unknown, not "no data"
  return labelForState(h.research_status?.state);
}

export const STATUS_TONE: Record<ResearchStatus, "slate" | "red" | "amber" | "green"> = {
  "STATUS UNKNOWN": "slate", "NO RESEARCH DATA": "slate", "SOFTWARE TEST DATA": "red", "SIMULATED HARDWARE DATA": "red", "UNVERIFIED EXTERNAL DATA": "red",
  "UNVERIFIED DATA": "red", "VERIFIED RESEARCH DATA": "amber", "REAL RESEARCH RESULTS": "green",
};

export interface StatusLines { data: string; model: string; conformal: string; results: string; hardware: string }

export function statusLines(h: Health | null): StatusLines {
  const rs = h?.research_status;
  const verified = !!rs?.verified_data;
  const allowed = !!rs?.results_allowed;
  if (!h) return { data: "UNKNOWN (the service is not reachable)", model: "UNKNOWN", conformal: "UNKNOWN", results: "NOT EVALUATED", hardware: "NOT TESTED (ESP32 + MAX30102; the software was tested with a fake serial port only)" };
  const data = rs?.state === "NO_DATA" || !rs ? "NO RESEARCH DATA (0 real records)"
    : verified ? `VERIFIED RESEARCH DATA · ${h.dataset.rows} records · ${h.dataset.participants} participants` : rs.label;
  // Models fitted on data that is not verified research data are described as exactly that, never as research and never as "not trained".
  const what = rs?.state === "SOFTWARE_TEST_DATA" ? "SYNTHETIC TEST DATA" : rs?.state === "SIMULATED_HARDWARE_DATA" ? "SIMULATED HARDWARE DATA" : "UNVERIFIED DATA";
  const trained = !!h.model.trained, calibrated = !!h.conformal?.calibrated;
  return {
    data,
    model: verified && trained ? "TRAINED" : trained ? `TRAINED ON ${what} — NOT RESEARCH VALIDATED` : "NOT TRAINED",
    conformal: verified && calibrated ? "CALIBRATED" : calibrated ? `CALIBRATED ON ${what} — NOT RESEARCH VALIDATED` : "NOT CALIBRATED",
    results: allowed ? "EVALUATED (see tables)" : rs?.state === "VERIFIED_RESEARCH_DATA" ? "NOT EVALUATED" : "NOT AVAILABLE — REAL RESEARCH DATA REQUIRED",
    hardware: "NOT TESTED (ESP32 + MAX30102; the software was tested with a fake serial port only)",
  };
}
