export interface MetricRow { metric: string; estimate: number | null; ci_low: number | null; ci_high: number | null; n_obs: number; n_participants: number; ci_status: string }
export interface ErrGroup { group: string; n_obs: number; n_participants: number; status: "OK" | "INSUFFICIENT DATA"; ridge: MetricRow[]; lightgbm: MetricRow[]; spo2_as_is: MetricRow[] }
export interface CovGroup { group: string; n_total: number; n_abstained: number; n_obs: number; n_participants: number; status: "OK" | "INSUFFICIENT DATA"; median_width: number | null; metrics: MetricRow[] }
export interface Hist { edges: number[]; counts: Record<string, number[]> }

export interface ValidationReport {
  available: true; research_status?: ReportStatus; stale: boolean; split: string; generated_at: string;
  data_provenance: { kind: string; label: string };
  sample: { test_participants: number; test_observations: number };
  bootstrap: { method: string; replicates: number; seed: number; level: number; min_participants_for_ci: number };
  error_definition: string;
  overall: { ridge: MetricRow[]; lightgbm: MetricRow[]; spo2_as_is: MetricRow[] };
  subgroups: { ita: ErrGroup[]; pi: ErrGroup[]; ita_x_pi: ErrGroup[] };
  conformal: { available: false } | { available: true; target_coverage: number; overall: CovGroup; ita: CovGroup[]; pi: CovGroup[]; ita_x_pi: CovGroup[]; wording: string };
  plots: { scatter: { sao2: number; spo2: number; ridge: number; lightgbm: number }[]; error_hist: Hist; width_hist?: Hist };
  notes: string[];
}

export interface XaiReport {
  available: true; notice: string; explanation: string; features: string[];
  ridge: { intercept: number; alpha: number; note: string; rows: { feature: string; description: string; coef_standardized: number; coef_per_unit: number; direction: string }[] };
  lightgbm: { note: string; shap_data: string; rows: { feature: string; description: string; gain_importance: number; mean_abs_shap: number; mean_shap: number }[] };
  interval_models: Record<"lo" | "hi", { feature: string; description: string; gain_importance: number }[]> | null;
}

export type Loaded<T> = { ok: true; data: T } | { ok: false; message: string };

async function load<T>(path: string): Promise<Loaded<T>> {
  try {
    const res = await fetch(path);
    if (res.ok) {
      const body = await res.json();
      if (body && body.available === false) return { ok: false, message: body.errors?.[0]?.message ?? "Not available." };
      return { ok: true, data: body };
    }
    const b = await res.json().catch(() => ({}));
    return { ok: false, message: b.errors?.[0]?.message ?? "Not available." };
  } catch { return { ok: false, message: "The service is not reachable. Start the backend (see README.md)." }; }
}

export interface ResearchGate {
  state: string; label: string; results_allowed: boolean; verified_data: boolean; failed_checks: string[];
  checks: { id: string; title: string; passed: boolean; detail: string }[]; attestation_present: boolean; note: string; rule: string;
}
export const fetchResearchGate = () => load<ResearchGate>("/api/research/status");
export interface ReportStatus { state: string; label: string; results_allowed: boolean; failed_checks: string[] }
export const fetchValidation = () => load<ValidationReport>("/api/validation/report");
export const fetchXai = () => load<XaiReport>("/api/xai/report");

export const fmt = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : v.toFixed(d));
export const ci = (r: MetricRow | undefined, d = 2) => (!r ? "—" : r.ci_low === null || r.ci_high === null ? "CI not reported" : `[${fmt(r.ci_low, d)}, ${fmt(r.ci_high, d)}]`);
