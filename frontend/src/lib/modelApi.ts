import { ValidationFailed, type FieldError } from "./reliabilityApi";
import { failMessage, unavailableMessage } from "./http";

export interface Provenance { kind: "LOADED" | "NONE" | "UNVERIFIED" | "MISMATCH"; label: string; reason: string; file?: string }

export interface Metrics {
  n_obs: number; n_participants: number | null;
  mae: number | null; rmse: number | null; bias: number | null; r2: number | null;
}
export interface ModelInfo { label: string; metrics: Metrics; best_params: Record<string, number>; cv_mae: number; cv_scheme: string }

export interface SubgroupCell {
  group?: string; ita_group?: string; pi_group?: string;
  n_obs: number; n_participants: number; sufficient: boolean; status?: "OK" | "INSUFFICIENT DATA";
  models: Record<"ridge" | "lightgbm" | "spo2_as_is", { mae: number | null; bias: number | null }>;
}

export interface TrainResult {
  status: "trained";
  trained_at: string;
  data_provenance: Provenance;
  dataset: { splits: Record<"train" | "calibration" | "test", { rows: number; participants: number; sha256: string }>; split_seed: number | null; calibration_use: string };
  features: string[];
  excluded_features: Record<string, string>;
  target: string;
  error_definition: string;
  models: { ridge: ModelInfo; lightgbm: ModelInfo };
  reference: { label: string; metrics: Metrics };
  best_model: { name: "ridge" | "lightgbm"; criterion: string; mae: number; other_mae: number; mae_difference: number; note: string };
  subgroups: { ita: SubgroupCell[]; pi: SubgroupCell[]; ita_x_pi: SubgroupCell[]; min_participants: number; note: string };
  config: Record<string, unknown>;
  software: Record<string, string>;
  notes: string[];
}

export interface ModelStatus {
  trained: boolean;
  trained_at: string | null;
  lightgbm_available: boolean;
  processed_data_available: boolean;
  stale: boolean | null;
  stale_reason: string | null;
  data_provenance: Provenance;
  current_data_provenance: Provenance;
  readiness: { status: "NOT READY" | "READY FOR TRAINING"; reasons: string[] };
  research_results: boolean;
  research_status?: { state: string; label: string; results_allowed: boolean; failed_checks: string[] };
  research_data: { records: number; participants: number; sessions: number; blocked: boolean; reasons: string[] };
  artifacts: Record<string, boolean>;
  dataset: TrainResult["dataset"] | null;
}

export interface PredictionRow {
  participant_id: string; session_id?: string; spo2: number; sao2: number;
  ridge_prediction: number; lightgbm_prediction: number; ridge_error: number; lightgbm_error: number;
}

export interface PredictOut {
  predictions: Partial<Record<"ridge" | "lightgbm", number>>;
  features: Record<string, number>;
  required_inputs: string[];
  warnings: string[];
  data_provenance: Provenance;
  disclaimer: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error("The model service is not reachable. Start the backend (see README.md) and try again.");
  }
  if (res.status === 422 || res.status === 404) {
    const body = await res.json().catch(() => null);
    if (body?.errors) throw new ValidationFailed(body.errors as FieldError[]);
  }
  if (!res.ok) throw new Error(failMessage(res.status, "The model service returned an unexpected error. Please try again."));
  const body = await res.json();
  const why = unavailableMessage(body);
  if (why) throw new Error(why);
  return body;
}

const post = (path: string, body?: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
});

export const fetchModelStatus = () => call<ModelStatus>("/api/model/status");
export const fetchModelMetrics = () => call<TrainResult>("/api/model/metrics");
export const fetchTestPredictions = (limit = 1000) =>
  call<{ total: number; rows: PredictionRow[] }>(`/api/model/predictions?limit=${limit}`);
export const trainModels = () => call<TrainResult>("/api/model/train", post("/api/model/train"));
export const predictModel = (body: Record<string, unknown>) => call<PredictOut>("/api/model/predict", post("/api/model/predict", body));
