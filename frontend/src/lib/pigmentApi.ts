import { ValidationFailed, type FieldError } from "./reliabilityApi";
import { failMessage } from "./http";

export type Group = "Light" | "Medium" | "Dark";
export const LOCATIONS = ["Finger dorsal", "Finger palmar", "Forehead", "Other"] as const;
export const NOT_SPECIFIED = "Not specified";

export interface LabRow { L: string; a: string; b: string; location: string }

export interface Measurement {
  index: number; L: number; a: number; b: number; ita: number; pigmentation_group: Group;
  location: string; usable_for_reliability: boolean; warnings: string[];
}
export interface PigmentResult {
  n: number; n_used: number; measurements: Measurement[];
  median_ita: number | null; pigmentation_group: Group | null; location: string | null;
  mixed_locations: boolean;
  by_location: Record<string, { n: number; median_ita: number; pigmentation_group: Group; usable_for_reliability: boolean }>;
  usable_for_reliability: boolean; warnings: string[];
  thresholds: { light_above: number; dark_at_most: number; note: string };
  label: string;
}

/** What the Live Reliability Check consumes from this module. */
export interface PigmentSummary {
  ita: number; group: Group; n: number; location: string; source: string;
}

/** Numbers are sent as numbers; anything else is sent as typed so the backend can say why it is invalid. */
const cell = (s: string): unknown => (s.trim() === "" ? null : Number.isFinite(Number(s)) ? Number(s) : s.trim());

export async function summarizeParticipant(rows: LabRow[], location: string | null): Promise<PigmentResult> {
  const measurements = rows.map((r) => ({
    L: cell(r.L), a: cell(r.a), b: cell(r.b), location: r.location === NOT_SPECIFIED ? null : r.location,
  }));
  let res: Response;
  try {
    res = await fetch("/api/ita/participant", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ measurements, location }),
    });
  } catch {
    throw new Error("The pigmentation service is not reachable. Start the backend (see README.md) and try again.");
  }
  if (res.status === 422) throw new ValidationFailed((await res.json()).errors as FieldError[]);
  if (!res.ok) throw new Error(failMessage(res.status, "The pigmentation service returned an unexpected error. Please try again."));
  return res.json();
}

// ---------- CSV ----------
export interface CsvGroup { id: string; rows: LabRow[] }

const norm = (h: string) => h.toLowerCase().replace(/[^a-z]/g, "");

export function parseLabCsv(text: string): CsvGroup[] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lines.length === 0) throw new Error("The file is empty.");
  const delim = [",", ";", "\t"].reduce((best, d) => (lines[0].split(d).length > lines[0].split(best).length ? d : best), ",");
  const rows = lines.map((l) => l.split(delim).map((c) => c.trim().replace(/^"|"$/g, "")));
  const isNum = (s: string) => s !== "" && Number.isFinite(Number(s));
  const header = rows[0].every((c) => !isNum(c)) ? rows[0].map(norm) : null;
  const body = header ? rows.slice(1) : rows;
  if (body.length === 0) throw new Error("The file has a header but no data rows.");

  const find = (names: string[]) => (header ? header.findIndex((h) => names.includes(h)) : -1);
  let iL: number, ia: number, ib: number, iP: number, iLoc: number;
  if (header) {
    iL = find(["l", "lstar", "lab"]); ia = find(["a", "astar"]); ib = find(["b", "bstar"]);
    iP = find(["participantid", "participant", "id", "subject", "subjectid"]);
    iLoc = find(["location", "site", "measurementlocation"]);
    const missing = [["L*", iL], ["a*", ia], ["b*", ib]].filter(([, i]) => i === -1).map(([n]) => n);
    if (missing.length) throw new Error(`Column(s) not found: ${missing.join(", ")}. Expected columns: participant_id (optional), L, a, b, location (optional).`);
  } else if (body[0].length === 3) {
    [iL, ia, ib, iP, iLoc] = [0, 1, 2, -1, -1];
  } else {
    throw new Error("Without a header row the file must have exactly three columns: L, a, b.");
  }
  const groups = new Map<string, LabRow[]>();
  body.forEach((r) => {
    const id = iP >= 0 && r[iP] ? r[iP] : "Participant 1";
    const loc = iLoc >= 0 && r[iLoc] ? r[iLoc] : NOT_SPECIFIED;
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id)!.push({ L: r[iL] ?? "", a: r[ia] ?? "", b: r[ib] ?? "", location: loc });
  });
  return [...groups].map(([id, rs]) => ({ id, rows: rs }));
}
