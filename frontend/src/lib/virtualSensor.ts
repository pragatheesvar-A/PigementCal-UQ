/**
 * VIRTUAL HARDWARE SIMULATION: a software stand-in for ESP32 + MAX30102. For software integration testing ONLY.
 *
 * It is NOT a physical measurement, NOT human physiology, NOT hardware validation, NOT clinical or research data.
 * Every session recorded from it is marked dataset_type=virtual_hardware_simulation / research_validity=not_for_research_validation.
 *
 * Layers (each a separate class, mirroring the real chain):
 *   SignalModel       deterministic, seeded RED/IR optical (reflectance) PPG model
 *   VirtualMax30102   I2C slave at 0x57: PART ID 0xFF = 0x15, 32-deep FIFO, mode/FIFO/SPO2 config (logic ported from
 *                     hardware/wokwi/max-30102.chip.c, which is a C Wokwi chip; this is a TypeScript re-implementation, not that binary)
 *   VirtualEsp32      the firmware loop (hardware/esp32_max30102): scan, read PART ID, configure, drain the FIFO, print JSON lines
 *   VirtualSerialPort a Web-Serial-shaped port, so the SAME SerialSource / parser / ring buffer / recorder / analysis path is used
 *
 * Only raw RED and IR counts leave the sensor. No PI, SpO2, SQI, SaO2, ITA or reliability state is ever written to the stream.
 */
import type { SerialPortLike } from "./sources";

export const VIRTUAL_META = {
  dataset_type: "virtual_hardware_simulation",
  research_validity: "not_for_research_validation",
  generated_for: "hardware_pipeline_integration_testing",
} as const;
export const VIRTUAL_BANNER = "VIRTUAL HARDWARE SIMULATION — NOT REAL MEASUREMENTS";
/** The device name the backend knows for the simulation (config.DEVICES); a real board is "ESP32 + MAX30102". */
export const VIRTUAL_DEVICE = "Virtual ESP32 + Virtual MAX30102 (simulation)";

// ---------------------------------------------------------------- scenarios
export type ScenarioId = "normal" | "low_perfusion" | "low_perfusion_noisy" | "high_motion" | "high_noise" | "fast_pulse" | "slow_pulse" | "combined";
export type NoiseLevel = "low" | "intermediate" | "medium" | "high";
export type MotionLevel = "none" | "moderate" | "high";

export interface SimParams {
  scenario: ScenarioId;
  hr: number;                 // beats per minute
  noise: NoiseLevel;
  motion: MotionLevel;
  seed: number;
  perfusion: number;          // IR pulsatile peak-to-peak as a fraction of the IR DC level (an optical amplitude, not a clinical PI)
  irDc: number;               // counts
  redDc: number;              // counts
  ratio: number;              // RED/IR relative pulse amplitude used by the optical model (an internal scenario constant)
}

export const SCENARIOS: Record<ScenarioId, { label: string; hr: number; noise: NoiseLevel; motion: MotionLevel; perfusion: number }> = {
  normal:        { label: "Normal",              hr: 72,  noise: "low",  motion: "none",     perfusion: 0.02 },
  low_perfusion: { label: "Low perfusion",       hr: 72,  noise: "low",  motion: "none",     perfusion: 0.003 },
  low_perfusion_noisy: { label: "Low perfusion + intermediate noise", hr: 72, noise: "intermediate", motion: "none", perfusion: 0.003 },
  high_motion:   { label: "High motion",         hr: 72,  noise: "low",  motion: "high",     perfusion: 0.02 },
  high_noise:    { label: "High noise",          hr: 72,  noise: "high", motion: "none",     perfusion: 0.02 },
  fast_pulse:    { label: "Fast pulse (110)",    hr: 110, noise: "low",  motion: "none",     perfusion: 0.02 },
  slow_pulse:    { label: "Slow pulse (50)",     hr: 50,  noise: "low",  motion: "none",     perfusion: 0.02 },
  combined:      { label: "Combined challenge",  hr: 72,  noise: "high", motion: "moderate", perfusion: 0.006 },
};
export const SCENARIO_IDS = Object.keys(SCENARIOS) as ScenarioId[];

// counts (Gaussian sd per channel). "intermediate" sits between low and medium: strong enough to lower signal quality to MODERATE at low
// perfusion without destroying the pulse. It is a physical noise level only; nothing about it refers to a reliability state.
const NOISE_SD: Record<NoiseLevel, number> = { low: 20, intermediate: 63, medium: 120, high: 450 };
const MOTION_SPEC: Record<MotionLevel, { every: [number, number]; amp: number } | null> = {
  none: null,
  moderate: { every: [2, 4], amp: 0.03 },
  high: { every: [0.8, 2], amp: 0.08 },
};

export const FS = 100;               // output samples per second after averaging
export const ADC_MAX = 262143;       // 18-bit

/** Scenario defaults, optionally overridden by the user's own HR / noise / motion / seed. */
export function paramsFor(scenario: ScenarioId, o: Partial<Pick<SimParams, "hr" | "noise" | "motion" | "seed">> = {}): SimParams {
  const s = SCENARIOS[scenario];
  return { scenario, hr: o.hr ?? s.hr, noise: o.noise ?? s.noise, motion: o.motion ?? s.motion, seed: o.seed ?? 42,
           perfusion: s.perfusion, irDc: 90000, redDc: 60000, ratio: 0.5 };
}

// ---------------------------------------------------------------- seeded random numbers
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function gaussian(rnd: () => number) { const u = Math.max(rnd(), 1e-12), v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

// ---------------------------------------------------------------- optical PPG model
const bump = (p: number, c: number, w: number) => { let d = Math.abs(p - c); d = Math.min(d, 1 - d); return Math.exp(-(d * d) / (2 * w * w)); };
const rawShape = (p: number) => 0.8 * bump(p, 0.22, 0.09) + 0.35 * bump(p, 0.52, 0.12);       // systolic peak + dicrotic wave of the blood-volume pulse
const SHAPE_MIN = Math.min(...Array.from({ length: 200 }, (_, i) => rawShape(i / 200)));
const SHAPE_MAX = Math.max(...Array.from({ length: 200 }, (_, i) => rawShape(i / 200)));
const shape = (p: number) => (rawShape(p) - SHAPE_MIN) / (SHAPE_MAX - SHAPE_MIN);             // 0..1

/**
 * Blood volume v(t) changes the optical path; reflected intensity FALLS as volume rises:
 *   I_ch(t) = DC_ch * (1 + drift + motion) * (1 - pp_ch * (v(t) - 0.5)) + noise
 * so AC/DC (and therefore PI) emerges downstream from the raw counts; it is never written into the stream.
 * Deterministic parts (pulse, rate variability, drift) do not depend on the seed; noise and motion artefacts do.
 */
export class SignalModel {
  private n = 0;
  private phase = 0;
  private noiseRnd: () => number;
  private motionRnd: () => number;
  private nextMotionAt: number;
  private events: { t0: number; amp: number }[] = [];
  constructor(public params: SimParams) {
    this.noiseRnd = mulberry32(params.seed);
    this.motionRnd = mulberry32((params.seed ^ 0x9e3779b9) >>> 0);
    this.nextMotionAt = this.scheduleFrom(0);
  }
  private scheduleFrom(t: number) {
    const m = MOTION_SPEC[this.params.motion];
    return m ? t + m.every[0] + this.motionRnd() * (m.every[1] - m.every[0]) : Infinity;
  }
  next(): { red: number; ir: number } {
    const p = this.params, t = this.n / FS;
    this.n++;
    const rate = (p.hr / 60) * (1 + 0.03 * Math.sin(2 * Math.PI * 0.25 * t));                // small respiratory rate variability
    this.phase = (this.phase + rate / FS) % 1;
    const v = shape(this.phase);
    const drift = 0.004 * Math.sin(2 * Math.PI * 0.07 * t);                                    // slow baseline drift
    let motion = 0;
    const m = MOTION_SPEC[p.motion];
    if (m) {
      if (t >= this.nextMotionAt) { this.events.push({ t0: t, amp: m.amp * (this.motionRnd() * 2 - 1) }); this.nextMotionAt = this.scheduleFrom(t); }
      this.events = this.events.filter((e) => t - e.t0 < 2);
      for (const e of this.events) motion += e.amp * Math.exp(-(t - e.t0) / 0.3);              // transient baseline artefact
    }
    const ppIr = p.perfusion, ppRed = p.perfusion * p.ratio;
    const sd = NOISE_SD[p.noise];
    const ir = p.irDc * (1 + drift + motion) * (1 - ppIr * (v - 0.5)) + sd * gaussian(this.noiseRnd);
    const red = p.redDc * (1 + drift + 0.9 * motion) * (1 - ppRed * (v - 0.5)) + sd * (p.redDc / p.irDc) * gaussian(this.noiseRnd);
    const clamp = (x: number) => Math.min(ADC_MAX, Math.max(1, Math.round(x)));
    return { red: clamp(red), ir: clamp(ir) };
  }
}

// ---------------------------------------------------------------- virtual MAX30102 (I2C slave 0x57)
const REG = { INT_STATUS1: 0x00, FIFO_WR: 0x04, FIFO_OVF: 0x05, FIFO_RD: 0x06, FIFO_DATA: 0x07, FIFO_CFG: 0x08, MODE: 0x09, SPO2: 0x0a, REV: 0xfe, PART: 0xff } as const;
export const MAX30102_ADDRESS = 0x57;
export const MAX30102_PART_ID = 0x15;
const FIFO_DEPTH = 32;
const RATES = [50, 100, 200, 400, 800, 1000, 1600, 3200];

export class VirtualMax30102 {
  readonly reg = new Uint8Array(256);
  private fifo: number[][] = Array.from({ length: FIFO_DEPTH }, () => new Array(9).fill(0));
  private pointer = 0;
  private dataIdx = 0;
  private acc = 0;
  private model: SignalModel;
  samplesProduced = 0;
  constructor(params: SimParams) { this.model = new SignalModel(params); this.resetRegisters(); }

  private resetRegisters() { this.reg.fill(0); this.reg[REG.REV] = 0x03; this.reg[REG.PART] = MAX30102_PART_ID; this.dataIdx = 0; }
  private channels() { switch (this.reg[REG.MODE] & 7) { case 2: return 1; case 3: return 2; case 7: return 3; default: return 0; } }
  /** Samples per second at the FIFO (ADC rate divided by the averaging factor). */
  get outputHz() { const rate = RATES[(this.reg[REG.SPO2] >> 2) & 7]; const avg = Math.min(1 << ((this.reg[REG.FIFO_CFG] >> 5) & 7), 32); return Math.max(Math.floor(rate / avg), 1); }

  private push() {
    const n = this.channels(); if (n === 0) return;
    const wr = this.reg[REG.FIFO_WR] & 31, rd = this.reg[REG.FIFO_RD] & 31;
    if (((wr + 1) & 31) === rd) {                                            // FIFO full
      if (this.reg[REG.FIFO_CFG] & 0x10) this.reg[REG.FIFO_RD] = (rd + 1) & 31;          // rollover: overwrite the oldest
      else { if (this.reg[REG.FIFO_OVF] < 31) this.reg[REG.FIFO_OVF]++; return; }          // otherwise drop the new sample
    }
    const { red, ir } = this.model.next();
    const vals = [red, ir, 20000];
    for (let i = 0; i < n; i++) { this.fifo[wr][i * 3] = (vals[i] >> 16) & 3; this.fifo[wr][i * 3 + 1] = (vals[i] >> 8) & 255; this.fifo[wr][i * 3 + 2] = vals[i] & 255; }
    this.reg[REG.FIFO_WR] = (wr + 1) & 31;
    this.reg[REG.INT_STATUS1] |= 0x40;
    this.samplesProduced++;
  }

  /** Advance the sensor's internal clock; produces samples at the configured output rate. */
  advance(seconds: number) {
    if (this.channels() === 0) return;
    this.acc += seconds * this.outputHz;
    while (this.acc >= 1) { this.acc -= 1; this.push(); }
  }

  /** One I2C write transaction. Returns false (NACK) for any address other than 0x57. */
  i2cWrite(address: number, bytes: number[]): boolean {
    if (address !== MAX30102_ADDRESS) return false;
    bytes.forEach((d, i) => {
      if (i === 0) { this.pointer = d & 255; return; }
      const r = this.pointer;
      if (r === REG.PART || r === REG.REV || r === REG.FIFO_DATA) return;                     // read-only
      if (r === REG.MODE) {
        if (d & 0x40) { this.resetRegisters(); this.pointer = REG.MODE; return; }             // reset bit self-clears
        this.reg[r] = d & 255;
      } else if (r === REG.FIFO_WR || r === REG.FIFO_RD) { this.reg[r] = d & 31; this.dataIdx = 0; }
      else this.reg[r] = d & 255;
      this.pointer = (this.pointer + 1) & 255;
    });
    return true;
  }

  /** One I2C read transaction from the current register pointer; null = NACK. */
  i2cRead(address: number, length: number): number[] | null {
    if (address !== MAX30102_ADDRESS) return null;
    const out: number[] = [];
    for (let k = 0; k < length; k++) {
      const r = this.pointer;
      if (r === REG.FIFO_DATA) {
        const wr = this.reg[REG.FIFO_WR] & 31, rd = this.reg[REG.FIFO_RD] & 31, n = this.channels();
        if (rd === wr || n === 0) { out.push(0); continue; }
        out.push(this.fifo[rd][this.dataIdx++]);
        if (this.dataIdx >= n * 3) { this.dataIdx = 0; this.reg[REG.FIFO_RD] = (rd + 1) & 31; }
      } else {
        out.push(this.reg[r]);
        if (r === REG.INT_STATUS1) this.reg[REG.INT_STATUS1] = 0;                            // read-to-clear
        this.pointer = (this.pointer + 1) & 255;
      }
    }
    return out;
  }
}

// ---------------------------------------------------------------- virtual ESP32 (the firmware's behaviour)
export class VirtualEsp32 {
  private sampleIndex = 0;
  ready = false;
  constructor(readonly sensor: VirtualMax30102 | null, private params: SimParams) {}

  private readReg(reg: number): number | null {
    if (!this.sensor || !this.sensor.i2cWrite(MAX30102_ADDRESS, [reg])) return null;
    const r = this.sensor.i2cRead(MAX30102_ADDRESS, 1);
    return r ? r[0] : null;
  }
  private writeReg(reg: number, v: number) { this.sensor?.i2cWrite(MAX30102_ADDRESS, [reg, v]); }

  /** I2C scan -> PART ID -> configure exactly like esp32_max30102.ino. Returns the status lines the firmware would print. */
  begin(): string[] {
    const found: number[] = [];
    for (let a = 1; a < 127; a++) if (this.sensor?.i2cWrite(a, [])) found.push(a);
    if (!found.includes(MAX30102_ADDRESS)) return ["# ERROR: MAX30102 not found - check wiring and power"];
    const id = this.readReg(REG.PART);
    if (id !== MAX30102_PART_ID) return [`# ERROR: unexpected PART ID 0x${(id ?? 0).toString(16)} (expected 0x15)`];
    this.writeReg(REG.MODE, 0x40);                                            // soft reset
    this.writeReg(REG.FIFO_CFG, (2 << 5) | 0x10 | 0x0f);                      // average 4, rollover on
    this.writeReg(REG.SPO2, 0x60 | (3 << 2) | 3);                             // 16384 range, 400 sps, 411 us
    this.writeReg(0x0c, 0x3f); this.writeReg(0x0d, 0x3f);                     // LED amplitudes
    this.writeReg(REG.MODE, 0x03);                                            // red + IR
    this.writeReg(REG.FIFO_WR, 0); this.writeReg(REG.FIFO_OVF, 0); this.writeReg(REG.FIFO_RD, 0);
    this.ready = true;
    return [`# PIGMENTCAL,v2-json,fs=${this.sensor!.outputHz},fields=timestamp,red,ir,source=VIRTUAL_SIMULATION,scenario=${this.params.scenario},seed=${this.params.seed}`,
            `# ${VIRTUAL_BANNER}`];
  }

  /** Drain whatever is in the FIFO and format it as JSON lines (timestamp = sample counter, like the firmware). */
  service(): string[] {
    if (!this.ready || !this.sensor) return [];
    const wr = this.readReg(REG.FIFO_WR), rd = this.readReg(REG.FIFO_RD);
    if (wr === null || rd === null) return [];
    const n = ((wr & 31) - (rd & 31) + FIFO_DEPTH) % FIFO_DEPTH;
    if (n === 0) return [];
    this.sensor.i2cWrite(MAX30102_ADDRESS, [REG.FIFO_DATA]);
    const bytes = this.sensor.i2cRead(MAX30102_ADDRESS, n * 6);
    if (!bytes) return [];
    const lines: string[] = [];
    for (let i = 0; i < n; i++) {
      const o = i * 6, v = (k: number) => (((bytes[k] << 16) | (bytes[k + 1] << 8) | bytes[k + 2]) & 0x3ffff);
      const ms = Math.floor((this.sampleIndex * 1000) / FS);
      this.sampleIndex++;
      lines.push(`{"timestamp":${ms},"red":${v(o)},"ir":${v(o + 3)}}`);
    }
    return lines;
  }

  /** Run the virtual firmware loop for `seconds` of simulated time (10 ms steps, as a fast loop would). */
  run(seconds: number, step = 0.01): string[] {
    const out: string[] = [];
    let left = seconds;
    while (left > 1e-9) { const dt = Math.min(step, left); this.sensor?.advance(dt); out.push(...this.service()); left -= dt; }
    return out;
  }
}

// ---------------------------------------------------------------- virtual serial transport (Web-Serial shaped)
export class VirtualSerialPort implements SerialPortLike {
  readable: ReadableStream<Uint8Array> | null = null;
  baudRate = 0;
  readonly esp: VirtualEsp32;
  readonly sensor: VirtualMax30102;
  private ctrl: ReadableStreamDefaultController<Uint8Array> | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private last = 0;
  private enc = new TextEncoder();
  /** autoRun: advance the simulation in real time (Live Monitor). Tests set it false and call pump(). */
  constructor(readonly params: SimParams, private opts: { autoRun?: boolean; tickMs?: number; now?: () => number } = {}) {
    this.sensor = new VirtualMax30102(params);
    this.esp = new VirtualEsp32(this.sensor, params);
  }
  async open(o: { baudRate: number }) {
    if (this.readable) throw Object.assign(new Error("The virtual port is already open."), { name: "InvalidStateError" });
    this.baudRate = o.baudRate;
    this.readable = new ReadableStream<Uint8Array>({ start: (c) => { this.ctrl = c; } });
    this.emit(this.esp.begin());
    if (this.opts.autoRun) {
      const now = this.opts.now ?? (() => performance.now());
      this.last = now();
      this.timer = setInterval(() => { const t = now(); this.pump((t - this.last) / 1000); this.last = t; }, this.opts.tickMs ?? 20);
    }
  }
  private emit(lines: string[]) { if (this.ctrl && lines.length) { try { this.ctrl.enqueue(this.enc.encode(lines.join("\n") + "\n")); } catch { /* closed */ } } }
  /** Advance simulated time (capped so a throttled background tab does not produce a huge burst). */
  pump(seconds: number) { this.emit(this.esp.run(Math.min(Math.max(seconds, 0), 1))); }
  async close() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    try { this.ctrl?.close(); } catch { /* already closed */ }
    this.ctrl = null;
  }
}
