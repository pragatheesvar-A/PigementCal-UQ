import { failMessage } from "./http";
export interface DatasetStatus {
  loaded: boolean;
  verified?: boolean;
  file?: string;
  rows: number;
  participants: number;
  devices: number;
  sha256?: string | null;
  uploaded_at?: string | null;
  processed: boolean;
  status: string;
  type: string;
}

export interface ProcessResult {
  status: "success";
  rows_in: number;
  rows_kept: number;
  rows_dropped: number;
  dropped_by_reason: Record<string, number>;
  excluded_optional_predictors: Record<string, string>;
  participants: number;
  splits: Record<"train" | "calibration" | "test", { participants: number; rows: number }>;
  predictors: string[];
}


export class ApiError extends Error {
  constructor(message: string, public code = "error") { super(message); }
}

async function json<T>(res: Response): Promise<T> {
  if (res.ok) return res.json();
  let msg = failMessage(res.status, "The dataset service returned an unexpected error.");
  let code = "error";
  try { const b = await res.json(); if (b.errors?.[0]) { msg = b.errors[0].message; code = b.errors[0].code; } } catch { /* keep default */ }
  throw new ApiError(msg, code);
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try { res = await fetch(path, init); } catch { throw new ApiError("The dataset service is not reachable. Start the backend (see README.md).", "offline"); }
  return json<T>(res);
}

export const fetchStatus = () => call<DatasetStatus>("/api/dataset/status");
export const fetchQuality = () => call<ProcessResult | { available: false; message: string }>("/api/dataset/quality");
export const processDataset = () => call<ProcessResult>("/api/dataset/process", { method: "POST" });
