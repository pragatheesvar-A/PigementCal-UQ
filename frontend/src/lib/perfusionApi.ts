import { ValidationFailed, type FieldError } from "./reliabilityApi";
import { failMessage } from "./http";

export type PerfusionState = "LOW" | "NORMAL";
export type PiSource = "manual" | "ac_dc" | "ppg";

export interface PerfusionResult {
  pi: number;
  pi_source: PiSource;
  source: PiSource;
  ac_ir: number | null;
  dc_ir: number | null;
  perfusion_state: PerfusionState;
  very_low: boolean;
  usable_for_reliability: boolean;
  warnings: string[];
  impact: string;
  thresholds: { pi_low_below: number; pi_very_low_below: number; pi_typical_high: number; pi_max: number; label: string };
  note: string;
}

/** What the Live Reliability Check consumes from this module. */
export interface PerfusionSummary {
  pi: number;
  state: PerfusionState;
  source: PiSource;
  ac_ir: number | null;
  dc_ir: number | null;
}

export interface Matrix {
  ita_groups: { id: string; range: string }[];
  pi_groups: { id: string; range: string }[];
  cells: { ita_group: string; pi_group: string }[];
  status: string;
}

/** Numbers are sent as numbers; other text is sent as typed so the backend can explain what is invalid. */
export const cell = (s: string): unknown => (s.trim() === "" ? null : Number.isFinite(Number(s)) ? Number(s) : s.trim());

async function call<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, body === undefined ? undefined : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch {
    throw new Error("The perfusion service is not reachable. Start the backend (see README.md) and try again.");
  }
  if (res.status === 422) throw new ValidationFailed((await res.json()).errors as FieldError[]);
  if (!res.ok) throw new Error(failMessage(res.status, "The perfusion service returned an unexpected error. Please try again."));
  return res.json();
}

export const calcDirect = (pi: unknown) => call<PerfusionResult>("/api/perfusion/direct", { pi });
export const calcAcDc = (ac_ir: unknown, dc_ir: unknown, source: "ac_dc" | "ppg" = "ac_dc") =>
  call<PerfusionResult>("/api/perfusion/calculate", { ac_ir, dc_ir, source });
export const fetchMatrix = () => call<Matrix>("/api/perfusion/matrix");
