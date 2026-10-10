import { failMessage } from "./http";
export type State = "GREEN" | "AMBER" | "RED" | "ABSTAIN";

/** Acquisition devices / sources the engine knows (mirrors backend config.DEVICES). */
export const DEVICES = ["ESP32 + MAX30102", "Virtual ESP32 + Virtual MAX30102 (simulation)", "Phone camera", "Recorded file", "Other"] as const;

export interface Inputs {
  spo2: number | null;
  pi: number | null;
  ita: number | null;
  signal_quality: string;
  motion: string;
  device: string;
  /** Optional: set when signal quality / motion come from the PPG signal module. */
  sqi?: number | null;
  signal_source?: "manual" | "signal_module";
  ita_source?: "manual" | "pigmentation_module";
  pi_source?: "manual" | "ac_dc" | "ppg";
}

export interface Reason {
  code: string;
  severity: "info" | "warning" | "critical";
  title: string;
  text: string;
}

export interface Assessment {
  spo2: number;
  pi: number;
  ita: number;
  pigmentation_group: "Light" | "Medium" | "Dark";
  perfusion_group: "Low" | "Normal";
  signal_quality: string;
  motion: string;
  device: string;
  sqi: number | null;
  signal_source: "manual" | "signal_module";
  ita_source: "manual" | "pigmentation_module";
  pi_source: "manual" | "ac_dc" | "ppg";
  perfusion_state: "LOW" | "NORMAL";
  features: Record<string, number>;
  points: number | null;
  uncertainty_range: null;
  uncertainty_note: string;
  reliability_state: State;
  status: string;
  reasons: Reason[];
}

export interface FieldError {
  field: string;
  code: string;
  message: string;
}

export class ValidationFailed extends Error {
  constructor(public errors: FieldError[]) {
    super("validation");
  }
}

export async function predict(inputs: Inputs): Promise<Assessment> {
  let res: Response;
  try {
    res = await fetch("/api/reliability/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(inputs),
    });
  } catch {
    throw new Error("The reliability service is not reachable. Start the backend (see README.md) and try again.");
  }
  if (res.status === 422) throw new ValidationFailed((await res.json()).errors);
  if (!res.ok) throw new Error(failMessage(res.status, "The reliability service returned an unexpected error. Please try again."));
  return res.json();
}
