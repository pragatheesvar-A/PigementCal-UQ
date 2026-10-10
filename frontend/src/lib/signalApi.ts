import type { FieldError } from "./reliabilityApi";
import { failMessage } from "./http";
import { ValidationFailed } from "./reliabilityApi";

export type Quality = "GOOD" | "MODERATE" | "POOR";
export type Motion = "LOW" | "MEDIUM" | "HIGH";

export interface SignalAnalysis {
  raw_ppg: number[];
  filtered_ppg: number[];
  peaks: number[];
  sampling_rate: number;
  sqi: number;
  sqi_components: Record<"skewness" | "noise" | "amplitude" | "regularity", number>;
  signal_quality: Quality;
  motion_score: number;
  motion_state: Motion;
  motion_source: "manual" | "estimated";
  estimated_motion_state: Motion;
  pulse_rate_estimate: number | null;
  pulse_rate_note: string;
  pi_estimate: number | null;
  perfusion_state: "LOW" | "NORMAL" | null;
  ac_ir: number;
  dc_ir: number;
  metrics: {
    sampling_rate_hz: number; n_samples: number; duration_s: number; mean: number; std: number;
    amplitude_range: number; filtered_amplitude_range: number; n_peaks: number; invalid_samples: number;
  };
  reasons: { severity: "info" | "warning" | "critical"; text: string }[];
  reliability_impact: { state_hint: "GREEN" | "AMBER" | "ABSTAIN"; text: string };
  thresholds: { sqi_good_min: number; sqi_moderate_min: number; label: string };
}

/** What the Live Reliability Check consumes from this module. */
export interface SignalSummary {
  signal_quality: Quality;
  motion_state: Motion;
  sqi: number;
  /** 0-100 motion score (accelerometer or PPG-estimated); a model input of the conformal layer. */
  motion_score: number;
  source: string;
  /** PPG-derived perfusion inputs; pi_estimate is null when the signal is POOR (withheld). */
  pi_estimate: number | null;
  perfusion_state: "LOW" | "NORMAL" | null;
  ac_ir: number;
  dc_ir: number;
  /** Uncalibrated ratio-of-ratios estimate (needs a red channel); null otherwise. */
  spo2_estimate: number | null;
  device: string;
  live: boolean;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new Error("The signal service is not reachable. Start the backend (see README.md) and try again.");
  }
  if (res.status === 422) throw new ValidationFailed((await res.json()).errors as FieldError[]);
  if (!res.ok) throw new Error(failMessage(res.status, "The signal service returned an unexpected error. Please try again."));
  return res.json();
}

export const analyzeSignal = (ppg: (number | null)[], sampling_rate: number | null, motion: Motion | null) =>
  post<SignalAnalysis>("/api/signal/analyze", { ppg, sampling_rate, motion });


// ---------- CSV parsing (client side; invalid cells become null and are counted by the backend) ----------

const isNum = (s: string) => s.trim() !== "" && Number.isFinite(Number(s));

export interface ParsedCsv { ppg: (number | null)[]; column: string; rows: number }

export function parsePpgCsv(text: string): ParsedCsv {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lines.length === 0) throw new Error("The file is empty.");
  const delim = [",", ";", "\t"].reduce((best, d) => (lines[0].split(d).length > lines[0].split(best).length ? d : best), ",");
  const rows = lines.map((l) => l.split(delim).map((c) => c.trim().replace(/^"|"$/g, "")));
  const hasHeader = rows[0].every((c) => !isNum(c));
  const header = hasHeader ? rows[0] : null;
  const body = hasHeader ? rows.slice(1) : rows;
  if (body.length === 0) throw new Error("The file has a header but no data rows.");

  let col = 0;
  if (header) {
    const named = header.findIndex((h) => /^(ppg|ir|red|signal|value|raw)/i.test(h));
    if (named >= 0) col = named;
    else if (header.length > 1 && /time|stamp|^t$|index|sample/i.test(header[0])) col = 1;
  } else if (body[0].length > 1) {
    const first = body.map((r) => Number(r[0]));
    const increasing = first.every((v, i) => Number.isFinite(v) && (i === 0 || v > first[i - 1]));
    if (increasing) col = 1;
  }
  const ppg = body.map((r) => (r[col] !== undefined && isNum(r[col]) ? Number(r[col]) : null));
  return { ppg, column: header ? header[col] || `column ${col + 1}` : `column ${col + 1}`, rows: body.length };
}
