/** Recording session for the ESP32 + MAX30102 stream: anonymous IDs, start/stop, sample buffer and CSV export (no DOM, unit-tested).
 *  The CSV contains ONLY what the sensor measured. SaO2 and ITA are never invented; they come from real reference
 *  measurements and are uploaded separately in Data Collection. */

import type { Sample } from "./acquisition";

const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;      // same rule as the backend (collection/rules.py)

/** null if `v` is an acceptable anonymous identifier, otherwise a user-facing reason. */
export function idProblem(v: string): string | null {
  const s = v.trim();
  if (s === "") return "is required";
  if (s.includes("@")) return "looks like an email address; use an anonymous ID such as P001";
  if (/^[+\d\s().-]+$/.test(s) && s.replace(/\D/g, "").length >= 9) return "looks like a phone number; use an anonymous ID such as P001";
  if (!ID_RE.test(s)) return "must be 1–64 characters (letters, digits, _ - .; no spaces) such as P001";
  return null;
}

export const CSV_HEADER = ["participant_id", "session_id", "timestamp", "red", "ir", "accelerometer_x", "accelerometer_y", "accelerometer_z"] as const;

export type SessionState = "idle" | "recording" | "stopped";

export class SessionRecorder {
  state: SessionState = "idle";
  participantId = "";
  sessionId = "";
  private rows: Sample[] = [];
  private lastT = -Infinity;
  /** Packets dropped because the device clock went backwards or repeated (reconnect / duplicates). */
  dropped = 0;
  /** Set only for virtual-hardware-simulation sessions: written as a leading '#' line and into the file name so the file can never pass for real data. */
  meta: Record<string, string> | null = null;

  /** Returns an error message, or null when the session has started. */
  start(participantId: string, sessionId: string, meta: Record<string, string> | null = null): string | null {
    if (this.state === "recording") return "A session is already recording.";
    const p = idProblem(participantId), s = idProblem(sessionId);
    if (p) return `Participant ID ${p}.`;
    if (s) return `Session ID ${s}.`;
    this.participantId = participantId.trim(); this.sessionId = sessionId.trim(); this.meta = meta;
    this.rows = []; this.lastT = -Infinity; this.dropped = 0; this.state = "recording";
    return null;
  }

  /** Called with every accepted sample. Samples are kept only while recording. */
  add(batch: Sample[]) {
    if (this.state !== "recording") return;
    for (const x of batch) {
      if (x.t <= this.lastT) { this.dropped++; continue; }
      this.rows.push(x); this.lastT = x.t;
    }
  }

  stop() { if (this.state === "recording") this.state = "stopped"; }
  reset() { this.state = "idle"; this.rows = []; this.lastT = -Infinity; this.dropped = 0; this.meta = null; }

  get samples() { return this.rows.length; }
  get duration() { return this.rows.length > 1 ? this.rows[this.rows.length - 1].t - this.rows[0].t : 0; }
  get hasData() { return this.rows.length > 0; }

  /** Timestamp is seconds since the first recorded sample. Accelerometer cells are empty when the sensor has none. */
  toCsv(): string {
    const t0 = this.rows[0]?.t ?? 0;
    const lines = this.rows.map((r) => [
      this.participantId, this.sessionId, (r.t - t0).toFixed(3), r.red ?? "", r.ir,
      r.accel ? r.accel[0] : "", r.accel ? r.accel[1] : "", r.accel ? r.accel[2] : "",
    ].join(","));
    const head = this.meta ? ["# " + Object.entries(this.meta).map(([k, v]) => k + "=" + v).join("; ")] : [];
    return [...head, CSV_HEADER.join(","), ...lines].join("\n") + "\n";
  }

  fileName() { return `${this.participantId}_${this.sessionId}${this.meta ? "_VIRTUAL_SIMULATION" : ""}.csv`; }
}

export type ConnectionLabel = "CONNECTED" | "DISCONNECTED" | "RECONNECT REQUIRED" | "UNSUPPORTED BROWSER";

/** Sensor status shown in the UI. `stalled` = connected but no sample for `stallMs`. */
export function connectionLabel(o: { supported: boolean; connected: boolean; wasConnected: boolean; lastDataAgeMs: number | null; stallMs?: number }): { label: ConnectionLabel; note: string } {
  if (!o.supported) return { label: "UNSUPPORTED BROWSER", note: "Web Serial is available in Chrome and Edge on desktop (HTTPS or localhost)." };
  if (!o.connected) return o.wasConnected
    ? { label: "RECONNECT REQUIRED", note: "The connection ended (USB unplugged, port closed or error). Reconnect the sensor." }
    : { label: "DISCONNECTED", note: "No sensor connected." };
  if (o.lastDataAgeMs === null) return { label: "CONNECTED", note: "Waiting for the first sample…" };
  if (o.lastDataAgeMs > (o.stallMs ?? 2000)) return { label: "CONNECTED", note: `The sensor stopped sending data (${(o.lastDataAgeMs / 1000).toFixed(1)} s without a sample). Check the finger, wiring and USB cable.` };
  return { label: "CONNECTED", note: "Receiving data." };
}

/** Plain-language explanation for a Web Serial open/permission failure. */
export function serialErrorMessage(e: { name?: string; message?: string }): string {
  if (e.name === "NotFoundError") return "No port was selected.";
  if (e.name === "SecurityError" || e.name === "NotAllowedError") return "Permission to use the serial port was denied. Allow access when the browser asks, and reconnect.";
  if (e.name === "InvalidStateError" || /already open/i.test(e.message ?? "")) return "That port is already open (another tab or program such as the Arduino Serial Monitor may be using it).";
  if (e.name === "NetworkError") return "Could not open the serial port. Check the USB cable and that no other program is using it.";
  return `Could not open the port: ${e.message ?? "unknown error"}`;
}
