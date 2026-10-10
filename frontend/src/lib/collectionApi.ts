import { failMessage } from "./http";
export type Kind = "ppg" | "reference" | "pigmentation" | "combined";

export interface UploadEntry {
  id: string;
  kind: Kind;
  filename: string;
  added_at: string;
  staged_rows: number;
  mapping: Record<string, string>;
  ignored_personal_columns: string[];
  summary: Record<string, unknown> & {
    windows?: number; samples?: number; sessions?: { participant_id: string; session_id: string; windows: number; duration_s: number; good: number; moderate: number; poor: number; failed: number }[];
    rows?: number; flagged_rows?: number; notes?: string[]; has_red?: boolean; has_accelerometer?: boolean; spo2_from?: string; time_basis?: string;
  };
}

export interface SubgroupCount { label: string; records: number; participants: number; status: "OK" | "INSUFFICIENT DATA" }
export interface Quality {
  readiness: { status: "NOT READY" | "READY FOR TRAINING"; reasons: string[]; warnings?: string[] };
  subgroups: { ita: SubgroupCount[]; pi: SubgroupCount[]; cells: SubgroupCount[]; min_participants: number; min_records: number };
  devices: string[];
  label: string;
  generated_at: string;
  total_records: number; valid_records: number; invalid_records: number;
  participants: number; sessions: number; participants_all_records: number;
  missing_spo2: number; missing_sao2: number; missing_ita: number; missing_pi: number; missing_sqi: number; missing_motion: number;
  unmatched: { ppg_records: number; sao2_records: number; pigmentation_records: number };
  invalid_reasons: Record<string, number>;
  matching: { tolerance_s: number; window_s: number; hop_s: number; matched_records: number };
  sources: { id: string; kind: string; filename: string; staged_rows: number }[];
  model_training: { blocked: boolean; reasons: string[] };
  consent_notice: string;
}

export interface Report {
  unmatched_ppg: { participant_id: string; session_id: string; timestamp: string; reason: string }[];
  unmatched_sao2: { participant_id: string; session_id: string; sao2: string; timestamp: string; reason: string }[];
  unmatched_pigmentation: { participant_id: string; session_id: string; reason: string }[];
  truncated: { ppg: number; sao2: number; pigmentation: number };
}

export interface Status {
  real_data: { records: number; participants: number; sessions: number; label: string };
  test_data?: { records: number; participants: number; sessions: number; label: string } | null;
  built: boolean;
  stale: boolean;
  last_build: Quality | null;
  staged: { ppg_windows: number; reference_rows: number; pigmentation_rows: number; combined_rows: number };
  uploads: UploadEntry[];
  model_training: { blocked: boolean; reasons: string[] };
  settings: { match_tolerance_s: number; window_s: number; hop_s: number; max_upload_mb: number };
  consent_notice: string;
}

export interface NeedsMapping {
  message: string;
  code: string;
  detected_columns: string[];
  proposed_mapping: Record<string, string>;
  missing_fields: string[];
  fields: { id: string; label: string; required: boolean }[];
}

export class ApiError extends Error {
  constructor(message: string, public code = "error") { super(message); }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try { res = await fetch(path, init); } catch { throw new ApiError("The service is not reachable. Start the backend (see README.md).", "offline"); }
  if (res.ok) return res.json();
  let msg = failMessage(res.status, "The service returned an unexpected error."), code = "error";
  try { const b = await res.json(); if (b.errors?.[0]) { msg = b.errors[0].message; code = b.errors[0].code; } } catch { /* default */ }
  throw new ApiError(msg, code);
}

export const fetchStatus = () => call<Status>("/api/collection/status");
export const fetchReport = () => call<Report | { available: false }>("/api/collection/report");
export const buildDataset = () => call<Quality & { status: "built"; report: Report }>("/api/collection/build", { method: "POST" });
export const removeUpload = (id: string) => call<{ removed: string }>(`/api/collection/uploads/${id}`, { method: "DELETE" });

export interface UploadParams {
  participant_id?: string; session_id?: string; device_id?: string; source?: string; fs?: string; recording_start?: string;
}

/** Upload a CSV as the raw request body. Resolves with the staged upload, or the column mapping the person still has to confirm. */
export async function uploadCsv(kind: Kind, file: File, params: UploadParams, mapping?: Record<string, string>): Promise<{ ok: UploadEntry; ignored: string[] } | { needs: NeedsMapping }> {
  const q = new URLSearchParams({ filename: file.name, attested_real: "true" });
  for (const [k, v] of Object.entries(params)) if (v !== undefined && String(v).trim() !== "") q.set(k, String(v).trim());
  if (mapping && Object.keys(mapping).length) q.set("mapping", JSON.stringify(mapping));
  let res: Response;
  try { res = await fetch(`/api/collection/upload/${kind}?${q}`, { method: "POST", headers: { "Content-Type": "text/csv" }, body: file }); }
  catch { throw new ApiError("The service is not reachable. Start the backend (see README.md).", "offline"); }
  const b = await res.json().catch(() => ({}));
  if (res.status === 422 && b.detected_columns) return { needs: { message: b.errors?.[0]?.message ?? "Columns could not be mapped.", code: b.errors?.[0]?.code ?? "missing_columns", detected_columns: b.detected_columns, proposed_mapping: b.proposed_mapping ?? {}, missing_fields: b.missing_fields ?? [], fields: b.fields ?? [] } };
  if (!res.ok) throw new ApiError(b.errors?.[0]?.message ?? "The file could not be used.", b.errors?.[0]?.code);
  return { ok: b.upload, ignored: b.ignored_personal_columns ?? [] };
}
