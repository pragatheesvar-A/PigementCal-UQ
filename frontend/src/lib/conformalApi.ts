import { ValidationFailed, type FieldError, type Reason, type State } from "./reliabilityApi";
import { failMessage, unavailableMessage } from "./http";

export type CellStatus = "CALIBRATED" | "MERGED" | "INSUFFICIENT";

export interface CalibrationCell {
  ita_group: string; pi_group: string; label: string;
  n_rows: number; n_participants: number; own_q: number | null; q: number | null;
  status: CellStatus; source: string | null; merged_with: string[]; requirement: string;
}

export interface GroupCoverage {
  group?: string; ita_group?: string; pi_group?: string; label?: string;
  n_total: number; n_abstained: number; n_obs: number; n_participants: number;
  coverage: number | null; mean_width: number | null; lower_bound_violation_rate: number | null; low_n: boolean;
}
export interface CoverageReport { target_coverage: number; overall: GroupCoverage; ita: GroupCoverage[]; pi: GroupCoverage[]; ita_x_pi: GroupCoverage[] }

export interface CoverageResponse {
  target_coverage: number;
  mondrian: CoverageReport; marginal: CoverageReport; uncalibrated_quantiles: CoverageReport;
  calibration: { cells: Record<string, CalibrationCell>; marginal: { n_rows: number; n_participants: number; q: number | null; sufficient: boolean }; merge_rule: string; min_cell_participants: number; min_cell_rows: number };
  wording: string; alpha: number;
}

export interface ConformalStatus {
  fitted: boolean; can_fit: boolean; blockers: string[]; stale: boolean | null; alpha: number; target_coverage: number;
  fitted_at: string | null; calibration_summary: { calibrated: number; merged: number; insufficient: number } | null;
}

export interface ConformalResult {
  spo2: number; pi: number; ita: number; ita_group: string; pi_group: string;
  cell: { label: string; status: CellStatus; n_participants: number; n_rows: number; source: string | null; requirement: string };
  reliability_state: State; status: string; base_state: State; reasons: Reason[];
  signal_quality?: string; motion?: string;
  predicted_sao2: number | null; interval: { lower: number; upper: number; width: number } | null; lower_bound: number | null;
  target_coverage: number; method: string; wording: string; disclaimer: string;
}

export class ApiError extends Error {
  constructor(message: string, public code = "error") { super(message); }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try { res = await fetch(path, init); } catch { throw new ApiError("The service is not reachable. Start the backend (see README.md).", "offline"); }
  if (res.ok) {
    const body = await res.json();
    const why = unavailableMessage(body);
    if (why) throw new ApiError(why, "unavailable");
    return body;
  }
  let msg = failMessage(res.status, "The service returned an unexpected error."), code = "error";
  try { const b = await res.json(); if (b.errors?.[0]) { msg = b.errors[0].message; code = b.errors[0].code; } } catch { /* default */ }
  throw new ApiError(msg, code);
}

export const fetchConformalStatus = () => call<ConformalStatus>("/api/conformal/status");
export const fetchCoverage = () => call<CoverageResponse>("/api/conformal/coverage");
export const fitConformal = () => call<{ status: "fitted" }>("/api/conformal/fit", { method: "POST" });

/** Resolves with the calibrated result, or { unavailable } when the conformal layer has not been fitted. Invalid inputs throw ValidationFailed. */
export async function predictConformal(body: Record<string, unknown>): Promise<ConformalResult | { unavailable: string }> {
  let res: Response;
  try { res = await fetch("/api/conformal/predict", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
  catch { return { unavailable: "The service is not reachable." }; }
  if (res.ok) {
    const body = await res.json();
    if (body && body.available === false) return { unavailable: body.errors?.[0]?.message ?? "CONFORMAL MODEL NOT AVAILABLE" };
    return body;
  }
  const b = await res.json().catch(() => ({}));
  const errors: FieldError[] = b.errors ?? [];
  if (errors[0]?.code === "not_calibrated") return { unavailable: errors[0].message };
  if (res.status === 422 && errors.length) throw new ValidationFailed(errors);
  return { unavailable: failMessage(res.status, "The conformal service returned an unexpected error.") };
}
