import { describe, expect, it } from "vitest";
import { parsePacket, toWindow, type Sample } from "./acquisition";
import { DEVICES } from "./reliabilityApi";
import { SerialSource } from "./sources";
import { SessionRecorder } from "./session";
import {
  ADC_MAX, FS, MAX30102_ADDRESS, MAX30102_PART_ID, SCENARIO_IDS, SCENARIOS, VIRTUAL_BANNER, VIRTUAL_META,
  VIRTUAL_DEVICE, VirtualEsp32, VirtualMax30102, VirtualSerialPort, paramsFor,
} from "./virtualSensor";

const rig = (scenario = "normal" as (typeof SCENARIO_IDS)[number], seed = 42) => {
  const p = paramsFor(scenario, { seed });
  const sensor = new VirtualMax30102(p), esp = new VirtualEsp32(sensor, p);
  return { p, sensor, esp, header: esp.begin() };
};
const samples = (lines: string[]): Sample[] => lines.map(parsePacket).flatMap((k) => (k.kind === "sample" ? [k.sample] : []));
const dataLines = (lines: string[]) => lines.filter((l) => l.startsWith("{"));
const pp = (v: number[]) => Math.max(...v) - Math.min(...v);
const mean = (v: number[]) => v.reduce((a, b) => a + b, 0) / v.length;

describe("virtual MAX30102 (I2C slave) and virtual ESP32", () => {
  it("answers only at I2C address 0x57 and reports PART ID 0x15", () => {
    const { sensor } = rig();
    expect(MAX30102_ADDRESS).toBe(0x57);
    expect(sensor.i2cWrite(0x57, [])).toBe(true);
    expect(sensor.i2cWrite(0x68, [])).toBe(false);
    expect(sensor.i2cRead(0x68, 1)).toBeNull();
    sensor.i2cWrite(0x57, [0xff]);
    expect(sensor.i2cRead(0x57, 1)).toEqual([MAX30102_PART_ID]);
    expect(MAX30102_PART_ID).toBe(0x15);
  });
  it("the virtual ESP32 scans, finds 0x57, reads the PART ID and starts; an absent sensor is reported, not faked", () => {
    const { esp, header } = rig();
    expect(esp.ready).toBe(true);
    expect(header[0]).toMatch(/^# PIGMENTCAL,v2-json,fs=100,fields=timestamp,red,ir,source=VIRTUAL_SIMULATION/);
    expect(header.join("\n")).toContain(VIRTUAL_BANNER);
    const none = new VirtualEsp32(null, paramsFor("normal"));
    expect(none.begin()).toEqual(["# ERROR: MAX30102 not found - check wiring and power"]);
    expect(none.ready).toBe(false);
    expect(none.run(1)).toEqual([]);
  });
  it("PART ID, revision and the reset bit behave like the register map", () => {
    const { sensor } = rig();
    sensor.i2cWrite(0x57, [0xff, 0x00]);                       // read-only: ignored
    sensor.i2cWrite(0x57, [0xff]); expect(sensor.i2cRead(0x57, 1)).toEqual([0x15]);
    sensor.i2cWrite(0x57, [0x09, 0x40]);                       // reset
    sensor.i2cWrite(0x57, [0x09]); expect(sensor.i2cRead(0x57, 1)![0] & 0x40).toBe(0);
  });
  it("produces non-zero RED and IR counts inside the 18-bit ADC range", () => {
    const { esp } = rig();
    const s = samples(esp.run(5));
    expect(s.length).toBeGreaterThan(400);
    for (const x of s) { expect(x.red).toBeGreaterThan(0); expect(x.ir).toBeGreaterThan(0); expect(x.red!).toBeLessThanOrEqual(ADC_MAX); expect(x.ir).toBeLessThanOrEqual(ADC_MAX); }
    expect(new Set(s.map((x) => x.ir)).size).toBeGreaterThan(50);       // not constant
  });
  it("timestamps increase strictly and the stream runs at about 100 Hz", () => {
    const { esp } = rig();
    const lines = dataLines(esp.run(10));
    expect(lines.length).toBeGreaterThanOrEqual(995); expect(lines.length).toBeLessThanOrEqual(1005);
    const ts = samples(lines).map((x) => x.t);
    for (let i = 1; i < ts.length; i++) expect(ts[i]).toBeGreaterThan(ts[i - 1]);
    expect((ts.length - 1) / (ts[ts.length - 1] - ts[0])).toBeCloseTo(FS, 0);
  });
  it("every data line is exactly {timestamp, red, ir}: no PI, SpO2, SQI, SaO2 or ITA ever leaves the sensor", () => {
    const { esp } = rig("combined");
    for (const l of dataLines(esp.run(3))) {
      const o = JSON.parse(l);
      expect(Object.keys(o)).toEqual(["timestamp", "red", "ir"]);
      expect(Object.values(o).every((v) => Number.isInteger(v))).toBe(true);
    }
  });
});

describe("determinism and scenarios", () => {
  it("the same scenario and seed give identical RED/IR samples", () => {
    expect(rig("normal", 42).esp.run(5)).toEqual(rig("normal", 42).esp.run(5));
    expect(rig("combined", 7).esp.run(5)).toEqual(rig("combined", 7).esp.run(5));
  });
  it("a different seed changes the stochastic parts only: noise differs, the pulse is the same", () => {
    const a = samples(rig("normal", 1).esp.run(10)), b = samples(rig("normal", 2).esp.run(10));
    expect(a.map((x) => x.ir)).not.toEqual(b.map((x) => x.ir));
    const ma = mean(a.map((x) => x.ir)), mb = mean(b.map((x) => x.ir));
    expect(Math.abs(ma - mb) / ma).toBeLessThan(0.001);                  // same DC and pulse
    const diff = a.map((x, i) => x.ir - b[i].ir);
    expect(Math.max(...diff.map(Math.abs))).toBeLessThan(400);             // differences are noise-sized (low noise), not pulse-sized (1800)
  });
  it("optical model: the pulse amplitude (AC/DC) and the red/IR amplitude ratio come from the raw counts", () => {
    const n = samples(rig("normal").esp.run(10)), l = samples(rig("low_perfusion").esp.run(10));
    const ac = (v: number[]) => pp(v.map((x, i) => x - mean(v.slice(Math.max(0, i - 50), i + 51)))) ;       // high-pass: remove the slow baseline drift
    const ratio = (s: Sample[]) => ac(s.map((x) => x.ir)) / mean(s.map((x) => x.ir));
    expect(ratio(n)).toBeGreaterThan(0.012); expect(ratio(n)).toBeLessThan(0.03);
    expect(ratio(l)).toBeLessThan(ratio(n) / 3);
    const rr = (ac(n.map((x) => x.red!)) / mean(n.map((x) => x.red!))) / ratio(n);
    expect(rr).toBeGreaterThan(0.35); expect(rr).toBeLessThan(0.7);       // ratio-of-ratios ≈ 0.5
  });
  it("heart rate follows the scenario (72 / 110 / 50 BPM): pulses counted from the raw IR counts", () => {
    const beats = (id: (typeof SCENARIO_IDS)[number]) => {
      const ir = samples(rig(id).esp.run(20)).map((x) => x.ir);
      const sm = ir.map((_, i) => mean(ir.slice(Math.max(0, i - 8), i + 9)));         // moving average
      const dc = ir.map((_, i) => mean(ir.slice(Math.max(0, i - 60), i + 61)));       // local baseline
      let up = 0; for (let i = 1; i < sm.length; i++) if (sm[i - 1] > dc[i - 1] && sm[i] <= dc[i]) up++;   // intensity falls through the baseline once per systole
      return up / 20 * 60;
    };
    expect(beats("normal")).toBeGreaterThan(60); expect(beats("normal")).toBeLessThan(86);
    expect(beats("fast_pulse")).toBeGreaterThan(beats("normal") * 1.3);
    expect(beats("slow_pulse")).toBeLessThan(beats("normal") * 0.85);
  });
  it("scenario switching changes the generated signal, and motion/noise scenarios add disturbance", () => {
    const noiseSd = (id: (typeof SCENARIO_IDS)[number]) => { const v = samples(rig(id).esp.run(10)).map((x) => x.ir); const d = v.slice(1).map((x, i) => x - v[i]); return Math.sqrt(mean(d.map((x) => x * x))); };
    expect(noiseSd("high_noise")).toBeGreaterThan(noiseSd("normal") * 3);
    const range = (id: (typeof SCENARIO_IDS)[number]) => pp(samples(rig(id).esp.run(20)).map((x) => x.ir));
    expect(range("high_motion")).toBeGreaterThan(range("normal") * 1.5);
    expect(SCENARIO_IDS).toEqual(["normal", "low_perfusion", "low_perfusion_noisy", "high_motion", "high_noise", "fast_pulse", "slow_pulse", "combined"]);
    expect(SCENARIOS.combined.perfusion).toBeLessThan(SCENARIOS.normal.perfusion);
    expect(paramsFor("normal").hr).toBe(72); expect(paramsFor("fast_pulse").hr).toBe(110); expect(paramsFor("slow_pulse").hr).toBe(50);
    expect(paramsFor("normal", { hr: 90 }).hr).toBe(90);
  });
  it("no scenario forces a reliability state: the simulator has no notion of GREEN / AMBER / RED / ABSTAIN", () => {
    const text = JSON.stringify(SCENARIOS) + rig("combined").esp.run(1).join("");
    expect(text).not.toMatch(/GREEN|AMBER|ABSTAIN|"RED"/);
  });
});

describe("the same acquisition path as a real board", () => {
  it("the existing parser accepts the stream; malformed or incomplete lines are rejected safely", () => {
    const { esp, header } = rig();
    const lines = [...header, ...esp.run(1)];
    const ok = lines.map(parsePacket);
    expect(ok.filter((k) => k.kind === "sample").length).toBeGreaterThan(90);
    expect(ok.filter((k) => k.kind === "skip").length).toBeGreaterThan(0);      // the "#" header / banner lines
    expect(ok.some((k) => k.kind === "error")).toBe(false);
    expect(parsePacket('{"timestamp":1,"red":').kind).toBe("error");
    expect(parsePacket('{"timestamp":1,"ir":5}')).toMatchObject({ kind: "error", code: "missing_red" });
    expect(parsePacket('{"red":1,"ir":5}')).toMatchObject({ kind: "error", code: "missing_timestamp" });
    expect(parsePacket("garbage")).toMatchObject({ kind: "error" });
  });
  it("VirtualSerialPort -> SerialSource delivers samples (starts, runs, stops and reports the close)", async () => {
    const port = new VirtualSerialPort(paramsFor("normal"));
    const got: Sample[] = []; let closed = false;
    const src = new SerialSource(port, 115200, { onSamples: (b) => got.push(...b), onError: (e) => { throw e; }, onClosed: () => { closed = true; } });
    await src.start();
    expect(port.baudRate).toBe(115200);
    port.pump(1); port.pump(1);
    await new Promise((r) => setTimeout(r, 30));
    expect(got.length).toBeGreaterThanOrEqual(195); expect(got.length).toBeLessThanOrEqual(205);
    expect(src.rejected).toBe(0);
    await src.stop();
    await new Promise((r) => setTimeout(r, 10));
    expect(closed).toBe(true);
  });
  it("the analysis window sent to the PPG / SQI / PI / SpO2 backend contains the virtual RED and IR counts and times", () => {
    const s = samples(rig().esp.run(10));
    const w = toWindow(s.slice(-600), "esp32");
    expect(w.ir).toHaveLength(600); expect(w.red).toHaveLength(600); expect(w.t).toHaveLength(600); expect(w.source).toBe("esp32");
    expect(w.ir[0]).toBe(s[s.length - 600].ir);
  });
  it("recording a virtual session gives the normal acquisition CSV, marked as simulation, with no SaO2 / ITA / PI / SQI", () => {
    const s = samples(rig().esp.run(5));
    const rec = new SessionRecorder();
    expect(rec.start("P001", "P001_S01", { ...VIRTUAL_META, scenario: "normal", seed: "42" })).toBeNull();
    rec.add(s); rec.stop();
    const csv = rec.toCsv().split("\n");
    expect(csv[0]).toBe("# dataset_type=virtual_hardware_simulation; research_validity=not_for_research_validation; generated_for=hardware_pipeline_integration_testing; scenario=normal; seed=42");
    expect(csv[1]).toBe("participant_id,session_id,timestamp,red,ir,accelerometer_x,accelerometer_y,accelerometer_z");
    expect(csv[1]).not.toMatch(/sao2|ita|\bpi\b|sqi/i);
    expect(csv).toHaveLength(2 + s.length + 1);                                    // marker + header + rows + trailing newline
    expect(csv[2]).toMatch(/^P001,P001_S01,0\.000,\d+,\d+,,,$/);                   // accelerometer cells empty
    expect(rec.fileName()).toBe("P001_P001_S01_VIRTUAL_SIMULATION.csv");
    expect(rec.fileName()).toMatch(/simulat/i);                                    // the research gate treats this file name as a test/simulation marker
  });
  it("a real recording session is unchanged: no marker line, normal file name", () => {
    const rec = new SessionRecorder();
    rec.start("P001", "P001_S01"); rec.add([{ t: 0.01, ir: 5, red: 4 }]);
    expect(rec.toCsv().split("\n")[0]).toBe("participant_id,session_id,timestamp,red,ir,accelerometer_x,accelerometer_y,accelerometer_z");
    expect(rec.fileName()).toBe("P001_P001_S01.csv");
  });
});

describe("device label", () => {
  it("the simulation has its own device name, known to the reliability engine, and a real board keeps its own", () => {
    expect(VIRTUAL_DEVICE).toBe("Virtual ESP32 + Virtual MAX30102 (simulation)");
    expect(DEVICES).toContain(VIRTUAL_DEVICE); expect(DEVICES).toContain("ESP32 + MAX30102");
    expect(toWindow(samples(rig().esp.run(1)), "virtual").source).toBe("virtual");
  });
});

import fixtureRaw from "../../../backend/tests/fixtures/virtual_low_perfusion_intermediate_noise_seed42.json?raw";

describe("intermediate noise level + the stored fixture used by the backend RED test", () => {
  it("the generator still reproduces the fixture exactly (so the backend test exercises what the simulator really produces)", () => {
    const doc = JSON.parse(fixtureRaw);
    const p = paramsFor("low_perfusion_noisy", { seed: 42 });
    expect(doc.scenario).toBe("low_perfusion_noisy"); expect(doc.params).toEqual(p);
    const s = samples([...rig("low_perfusion_noisy", 42).esp.run(34)]);
    expect(s.map((x) => x.ir)).toEqual(doc.ir); expect(s.map((x) => x.red)).toEqual(doc.red);
  });
  it("intermediate noise sits between low and medium and the preset is a physical parameter set only", () => {
    const sd = (noise: "low" | "intermediate" | "medium") => {
      const p = { ...paramsFor("normal", { seed: 5, noise }), perfusion: 0 };            // no pulse: only noise remains
      const e = new VirtualEsp32(new VirtualMax30102(p), p); e.begin();
      const ir = samples(e.run(20)).map((x) => x.ir); const m = mean(ir);
      return Math.sqrt(mean(ir.map((x) => (x - m) ** 2)));
    };
    const [a, b, c] = [sd("low"), sd("intermediate"), sd("medium")];
    expect(a).toBeLessThan(b); expect(b).toBeLessThan(c);
    expect(SCENARIOS.low_perfusion_noisy).toMatchObject({ noise: "intermediate", perfusion: SCENARIOS.low_perfusion.perfusion, motion: "none" });
    expect(JSON.stringify(SCENARIOS.low_perfusion_noisy)).not.toMatch(/RED|AMBER|GREEN|ABSTAIN/);
  });
});
