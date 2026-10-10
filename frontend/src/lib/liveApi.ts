import { ValidationFailed, type FieldError } from "./reliabilityApi";
import { failMessage } from "./http";
import type { LiveWindow } from "./acquisition";
import type { Motion, Quality } from "./signalApi";

export interface LiveResult {
  status: "ok";
  sqi: number;
  sqi_components: Record<"skewness" | "noise" | "amplitude" | "regularity", number>;
  signal_quality: Quality;
  motion_state: Motion;
  motion_score: number;
  motion_source: "manual" | "estimated" | "accelerometer";
  pulse_rate_estimate: number | null;
  pi_estimate: number | null;
  ac_ir: number;
  dc_ir: number;
  spo2: { available: boolean; estimate: number | null; ratio_r: number | null; note: string };
  reasons: { severity: "info" | "warning" | "critical"; text: string }[];
  reliability_impact: { state_hint: "GREEN" | "AMBER" | "ABSTAIN"; text: string };
  filtered_ppg: number[];
  peaks: number[];
  metrics: { n_peaks: number };
  device: string;
  source: string;
  fs_used: number;
  t0: number;
  window_seconds: number;
  resampled: boolean;
  polarity_inverted: boolean;
}
export interface LiveCollecting { status: "collecting"; seconds_collected: number; seconds_needed: number }

export async function analyzeLive(w: LiveWindow, signal?: AbortSignal): Promise<LiveResult | LiveCollecting> {
  let res: Response;
  try {
    res = await fetch("/api/live/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(w), signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new Error("The analysis service is not reachable. Start the backend (see README.md).");
  }
  if (res.status === 422) throw new ValidationFailed((await res.json()).errors as FieldError[]);
  if (!res.ok) throw new Error(failMessage(res.status, "The analysis service returned an unexpected error."));
  return res.json();
}
