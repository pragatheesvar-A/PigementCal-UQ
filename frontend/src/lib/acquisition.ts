/**
 * Real-time acquisition building blocks (pure functions and small classes, no DOM) so they can be unit-tested.
 *
 * Serial protocol streamed by the ESP32 + MAX30102 firmware (hardware/esp32_max30102):
 *   # comment / header lines start with '#'
 *   {"timestamp":<ms>,"red":<n>,"ir":<n>[,"accelerometer_x":<g>,"accelerometer_y":<g>,"accelerometer_z":<g>]}   one per line
 *   (legacy, still accepted)  <millis>,<red>,<ir>[,<ax>,<ay>,<az>]
 */

export interface Sample {
  t: number;      // seconds
  ir: number;     // infrared (or the single camera / recording channel)
  red?: number;
  accel?: [number, number, number];
}

const num = (s: string) => (s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : NaN);

export type PacketError = "invalid_json" | "missing_timestamp" | "missing_ir" | "missing_red" | "corrupted";
export type Packet = { kind: "sample"; sample: Sample } | { kind: "skip" } | { kind: "error"; code: PacketError; message: string };

export const PACKET_MESSAGES: Record<PacketError, string> = {
  invalid_json: "Invalid JSON packet",
  missing_timestamp: "Packet is missing the timestamp field",
  missing_ir: "Packet is missing the IR value",
  missing_red: "Packet is missing the RED value",
  corrupted: "Corrupted packet (unreadable or negative numbers)",
};

const fail = (code: PacketError): Packet => ({ kind: "error", code, message: PACKET_MESSAGES[code] });
const isFiniteNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const first = (o: Record<string, unknown>, keys: string[]) => keys.map((k) => o[k]).find((v) => v !== undefined);

function fromJson(s: string): Packet {
  let o: unknown;
  try { o = JSON.parse(s); } catch { return fail("invalid_json"); }
  if (o === null || typeof o !== "object" || Array.isArray(o)) return fail("invalid_json");
  const r = o as Record<string, unknown>;
  const ts = first(r, ["timestamp"]), ir = first(r, ["ir"]), red = first(r, ["red"]);
  if (ts === undefined || ts === null) return fail("missing_timestamp");
  if (ir === undefined || ir === null) return fail("missing_ir");
  if (red === undefined || red === null) return fail("missing_red");
  if (!isFiniteNum(ts) || !isFiniteNum(ir) || !isFiniteNum(red) || ts < 0 || ir < 0 || red < 0) return fail("corrupted");
  const out: Sample = { t: ts / 1000, ir, red };
  const acc = [first(r, ["accelerometer_x", "ax"]), first(r, ["accelerometer_y", "ay"]), first(r, ["accelerometer_z", "az"])];
  if (acc.some((v) => v !== undefined)) {
    if (!acc.every(isFiniteNum)) return fail("corrupted");               // accelerometer is all-or-nothing
    out.accel = acc as [number, number, number];
  }
  return { kind: "sample", sample: out };
}

function fromCsv(s: string): Packet {
  const p = s.split(",");
  if (p.length !== 3 && p.length !== 6) return fail("corrupted");
  const v = p.map(num);
  if (v.some((x) => Number.isNaN(x)) || v.slice(0, 3).some((x) => x < 0)) return fail("corrupted");
  const out: Sample = { t: v[0] / 1000, ir: v[2], red: v[1] };
  if (p.length === 6) out.accel = [v[3], v[4], v[5]];
  return { kind: "sample", sample: out };
}

/** Classify one serial line: a sample, a skipped comment / blank line, or a specific error. Never throws.
 *  Primary protocol: one JSON object per line. The older "millis,red,ir[,ax,ay,az]" lines are still accepted. */
export function parsePacket(line: string): Packet {
  const s = line.trim();
  if (s === "" || s.startsWith("#")) return { kind: "skip" };
  return s.startsWith("{") || s.startsWith("[") ? fromJson(s) : fromCsv(s);
}

/** Parse one serial line. Returns null for comments, headers, partial or corrupted lines (never throws). */
export function parseSerialLine(line: string): Sample | null {
  const p = parsePacket(line);
  return p.kind === "sample" ? p.sample : null;
}

/** Turns arbitrary text chunks from a serial stream into complete lines (handles lines split across chunks). */
export class LineSplitter {
  private rest = "";
  push(chunk: string): string[] {
    const text = this.rest + chunk;
    const parts = text.split(/\r?\n/);
    this.rest = parts.pop() ?? "";
    if (this.rest.length > 4096) this.rest = "";     // garbage without newlines: do not grow forever
    return parts;
  }
}

/** Rolling buffer holding the most recent `maxSeconds` of samples. */
export class RingBuffer {
  private s: Sample[] = [];
  constructor(private maxSeconds: number) {}
  push(batch: Sample[]) {
    for (const x of batch) {
      const last = this.s[this.s.length - 1];
      if (last && x.t < last.t) this.s = [];          // the device clock restarted (reconnect): start a clean window
      this.s.push(x);
    }
    const end = this.s[this.s.length - 1]?.t ?? 0;
    let k = 0;
    while (k < this.s.length && end - this.s[k].t > this.maxSeconds) k++;
    if (k > 0) this.s = this.s.slice(k);
  }
  clear() { this.s = []; }
  get length() { return this.s.length; }
  get seconds() { return this.s.length > 1 ? this.s[this.s.length - 1].t - this.s[0].t : 0; }
  /** Samples measured per second over the buffer (null until there is enough data). */
  get rate(): number | null { return this.s.length > 10 && this.seconds > 0 ? (this.s.length - 1) / this.seconds : null; }
  last(seconds: number): Sample[] {
    const end = this.s[this.s.length - 1]?.t ?? 0;
    return this.s.filter((x) => end - x.t <= seconds);
  }
}

export interface LiveWindow {
  ir: number[]; red?: number[]; t?: number[]; fs?: number; accel?: number[][]; source: "esp32" | "virtual" | "camera" | "file";
}

/** Build the request body for /api/live/analyze from the newest samples. */
export function toWindow(samples: Sample[], source: LiveWindow["source"]): LiveWindow {
  // Per-sample times are always sent: the server derives the sampling rate from them and resamples irregular sources.
  const w: LiveWindow = { ir: samples.map((x) => x.ir), t: samples.map((x) => x.t), source };
  if (samples.length && samples.every((x) => x.red !== undefined)) w.red = samples.map((x) => x.red as number);
  if (samples.length && samples.every((x) => x.accel !== undefined)) w.accel = samples.map((x) => x.accel as number[]);
  return w;
}

// ---------------------------------------------------------------- recordings (replay)
export interface Recording {
  ir: number[]; red: number[] | null; accel: [number, number, number][] | null;
  fs: number | null;            // from the time column only when that column is regular; otherwise the user must enter it
  fsSource: "time column" | "none";
  warnings: string[]; rows: number; irColumn: string;
}

const norm = (h: string) => h.toLowerCase().replace(/[^a-z0-9]/g, "");
const isNum = (s: string) => s.trim() !== "" && Number.isFinite(Number(s));

export function parseRecording(text: string): Recording {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "" && !l.trim().startsWith("#"));
  if (lines.length === 0) throw new Error("The file is empty.");
  const delim = [",", ";", "\t"].reduce((b, d) => (lines[0].split(d).length > lines[0].split(b).length ? d : b), ",");
  const rows = lines.map((l) => l.split(delim).map((c) => c.trim().replace(/^"|"$/g, "")));
  const hasHeader = rows[0].every((c) => !isNum(c));
  const header = hasHeader ? rows[0] : null;
  const body = hasHeader ? rows.slice(1) : rows;
  if (body.length < 10) throw new Error("The file has too few data rows to replay.");

  let timeI = -1, irI = -1, redI = -1;
  let accI: number[] = [];
  if (header) {
    const h = header.map(norm);
    timeI = h.findIndex((x) => /^(time|t|timestamp|ms|times|elapsed)/.test(x));
    redI = h.findIndex((x) => /^red/.test(x));
    irI = h.findIndex((x) => /^(ir|ppg|pleth|signal|raw|infrared|value)/.test(x));
    const ax = ["ax", "accx", "accelx", "accelerometerx"], ay = ["ay", "accy", "accely", "accelerometery"], az = ["az", "accz", "accelz", "accelerometerz"];
    const ai = [ax, ay, az].map((names) => h.findIndex((x) => names.includes(x)));
    if (ai.every((i) => i >= 0)) accI = ai;
    if (irI < 0) {            // fall back only when there is exactly one possible column; never guess between several
      const rest = h.map((_, i) => i).filter((i) => i !== timeI && i !== redI && !accI.includes(i));
      if (rest.length === 1) irI = rest[0];
    }
    if (irI < 0) throw new Error("No PPG column found. Name it ir, ppg, pleth or signal.");
  } else if (body[0].length === 1) irI = 0;
  else if (body[0].length === 2) { timeI = 0; irI = 1; }
  else throw new Error("Files with more than two columns need a header row (time, ir, red, ax, ay, az).");

  const warnings: string[] = [];
  // A cut-off final line is common in exported files: ignore trailing incomplete rows (and say so), but never bad cells in the middle.
  let end = body.length;
  while (end > 0 && !(body[end - 1][irI] !== undefined && isNum(body[end - 1][irI]))) end--;
  if (end < body.length) warnings.push(`${body.length - end} incomplete trailing row(s) at the end of the file were ignored.`);
  body.length = end;
  if (body.length < 10) throw new Error("The file has too few data rows to replay.");

  const col = (i: number) => body.map((r) => (r[i] !== undefined && isNum(r[i]) ? Number(r[i]) : NaN));
  const ir = col(irI);
  const bad = ir.map((v, i) => (Number.isNaN(v) ? i : -1)).filter((i) => i >= 0);
  if (bad.length) throw new Error(`The PPG column has ${bad.length} non-numeric sample(s) (first at data row ${bad[0] + 1}). Fix or remove them before replaying.`);

  let fs: number | null = null;
  let fsSource: Recording["fsSource"] = "none";
  if (timeI >= 0) {
    const scale = header && /ms|millis/i.test(header[timeI]) ? 1000 : 1;
    const t = col(timeI).map((v) => v / scale);
    const dt = t.slice(1).map((v, i) => v - t[i]);
    const sorted = [...dt].sort((a, b) => a - b);
    const med = sorted[Math.floor(sorted.length / 2)];
    const mean = dt.reduce((a, b) => a + b, 0) / dt.length;
    const sd = Math.sqrt(dt.reduce((a, b) => a + (b - mean) ** 2, 0) / dt.length);
    if (dt.some((d) => !(d > 0)) || !(med > 0) || sd / mean > 0.02) {
      warnings.push("The time column is irregular (non-increasing or mixed step sizes), so it cannot be trusted. Enter the sampling rate of the recording.");
    } else { fs = Number((1 / med).toFixed(3)); fsSource = "time column"; }
  }
  return {
    ir, red: redI >= 0 ? col(redI) : null,
    accel: accI.length ? body.map((_, k) => accI.map((c) => Number(body[k][c])) as [number, number, number]) : null,
    fs, fsSource, warnings, rows: body.length, irColumn: header ? header[irI] : "column 1",
  };
}

export type RecordingSource = "camera" | "file" | "esp32" | "virtual";
const RECORDING_LABEL: Record<RecordingSource, { name: string; signal: string }> = {
  camera: { name: "phone_camera", signal: "mean RED channel of the centre of the camera image (a camera has no infrared channel)" },
  file: { name: "replayed_file", signal: "the PPG column of the replayed file" },
  esp32: { name: "esp32_max30102", signal: "MAX30102 infrared and red counts" },
  virtual: { name: "virtual_max30102_simulation", signal: "virtual MAX30102 simulation, not a real sensor" },
};

/** CSV of a live / replayed recording. Times are seconds since the FIRST sample (not the browser clock), values are rounded sensibly,
 *  and the signal column is named for what it really is. Raw (possibly irregular) sample times are kept; nothing is resampled or repaired. */
export function recordingToCsv(rows: Sample[], source: RecordingSource): { csv: string; fileStem: string } {
  const lab = RECORDING_LABEL[source];
  const t0 = rows[0]?.t ?? 0;
  const dur = rows.length > 1 ? rows[rows.length - 1].t - t0 : 0;
  const hasRed = rows.length > 0 && rows.every((r) => r.red !== undefined), hasAcc = rows.length > 0 && rows.every((r) => r.accel !== undefined);
  const sigCol = source === "camera" ? "ppg_camera_red" : "ir";
  const head = ["timestamp_s", sigCol, ...(hasRed ? ["red"] : []), ...(hasAcc ? ["accelerometer_x", "accelerometer_y", "accelerometer_z"] : [])].join(",");
  const dp = source === "camera" ? 3 : 0;                              // camera means are fractional; sensor counts are integers
  const val = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(dp === 0 ? 3 : dp));
  const body = rows.map((r) => [(r.t - t0).toFixed(4), val(r.ir), ...(hasRed ? [val(r.red as number)] : []), ...(hasAcc ? r.accel!.map((a) => a.toFixed(4)) : [])].join(","));
  const meta = `# source=${lab.name}; signal=${lab.signal}; samples=${rows.length}; duration_s=${dur.toFixed(3)}; mean_rate_hz=${dur > 0 ? ((rows.length - 1) / dur).toFixed(2) : "n/a"}; times=seconds since the first sample`;
  return { csv: [meta, head, ...body].join(String.fromCharCode(10)) + String.fromCharCode(10), fileStem: `${lab.name}_recording` };
}

/** How many samples of a recording are due after `elapsedMs` of real time. */
export function dueCount(elapsedMs: number, fs: number, total: number): number {
  return Math.max(0, Math.min(total, Math.floor((elapsedMs / 1000) * fs)));
}

/** Mean of one colour channel over a centred square region of RGBA pixel data (camera PPG). */
export function meanChannel(rgba: Uint8ClampedArray | number[], width: number, height: number, channel: 0 | 1 | 2, frac = 0.5): number {
  const w0 = Math.floor(width * (1 - frac) / 2), w1 = Math.ceil(width * (1 + frac) / 2);
  const h0 = Math.floor(height * (1 - frac) / 2), h1 = Math.ceil(height * (1 + frac) / 2);
  let sum = 0, n = 0;
  for (let y = h0; y < h1; y++) for (let x = w0; x < w1; x++) { sum += rgba[(y * width + x) * 4 + channel]; n++; }
  return n ? sum / n : 0;
}
