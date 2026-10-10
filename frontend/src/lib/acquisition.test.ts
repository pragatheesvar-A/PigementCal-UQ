import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LineSplitter, RingBuffer, dueCount, meanChannel, parseRecording, parseSerialLine, recordingToCsv, toWindow, type Sample } from "./acquisition";
import { ReplaySource, SerialSource, type SerialPortLike } from "./sources";

describe("parseSerialLine", () => {
  it("parses a 3-field line (millis, red, ir) into seconds", () => {
    expect(parseSerialLine("1500,81234,101234")).toEqual({ t: 1.5, red: 81234, ir: 101234 });
  });
  it("parses the accelerometer variant", () => {
    expect(parseSerialLine("20,1,2,0.01,-0.02,0.98")).toEqual({ t: 0.02, red: 1, ir: 2, accel: [0.01, -0.02, 0.98] });
  });
  it("tolerates CRLF and surrounding spaces", () => {
    expect(parseSerialLine("  100,5,6 \r")).toEqual({ t: 0.1, red: 5, ir: 6 });
  });
  it.each(["", "   ", "# header line", "ms,red,ir", "10,20", "10,20,30,40", "a,b,c", "10,,30", "-5,1,2", "10,1,Infinity", "10,1,NaN", "1,2,3,4,5,x"])(
    "rejects %j without throwing", (line) => { expect(parseSerialLine(line)).toBeNull(); });
});

describe("LineSplitter", () => {
  it("reassembles lines split across chunks", () => {
    const s = new LineSplitter();
    expect(s.push("10,1,2\n20,3")).toEqual(["10,1,2"]);
    expect(s.push(",4\n30,5,6\n")).toEqual(["20,3,4", "30,5,6"]);
  });
  it("drops runaway garbage without growing forever", () => {
    const s = new LineSplitter();
    s.push("x".repeat(5000));
    expect(s.push("10,1,2\n")).toEqual(["10,1,2"]);
  });
});

const mk = (i: number, fs = 100): Sample => ({ t: i / fs, ir: i });

describe("RingBuffer", () => {
  it("keeps only the newest window and reports the measured rate", () => {
    const r = new RingBuffer(2);
    r.push(Array.from({ length: 1000 }, (_, i) => mk(i)));
    expect(r.seconds).toBeCloseTo(2, 1);
    expect(r.length).toBeLessThanOrEqual(202);
    expect(r.rate).toBeCloseTo(100, 0);
    expect(r.last(1).length).toBeGreaterThanOrEqual(100);
  });
  it("starts a clean window if the device clock restarts (reconnect)", () => {
    const r = new RingBuffer(30);
    r.push(Array.from({ length: 500 }, (_, i) => mk(i)));
    r.push([{ t: 0.01, ir: 1 }, { t: 0.02, ir: 2 }]);
    expect(r.length).toBe(2);
  });
  it("has no rate until there is data", () => {
    expect(new RingBuffer(5).rate).toBeNull();
  });
});

describe("toWindow", () => {
  it("always sends per-sample times and includes red / accel only when every sample has them", () => {
    const s: Sample[] = [{ t: 0, ir: 1, red: 2, accel: [0, 0, 1] }, { t: 0.01, ir: 3, red: 4, accel: [0, 0, 1] }];
    expect(toWindow(s, "esp32")).toEqual({ ir: [1, 3], t: [0, 0.01], red: [2, 4], accel: [[0, 0, 1], [0, 0, 1]], source: "esp32" });
    const partial: Sample[] = [{ t: 0, ir: 1, red: 2 }, { t: 0.01, ir: 3 }];
    const w = toWindow(partial, "camera");
    expect(w.red).toBeUndefined();
    expect(w.accel).toBeUndefined();
  });
});

describe("parseRecording", () => {
  const rows = (n: number, f: (i: number) => string) => Array.from({ length: n }, (_, i) => f(i)).join("\n");

  it("reads a regular time column and derives the sampling rate from it", () => {
    const r = parseRecording("time_s,ir\n" + rows(50, (i) => `${(i / 100).toFixed(2)},${1000 + i}`));
    expect(r.fs).toBe(100);
    expect(r.fsSource).toBe("time column");
    expect(r.ir.length).toBe(50);
    expect(r.warnings).toEqual([]);
  });
  it("converts a millisecond time column", () => {
    expect(parseRecording("time_ms,ir,red\n" + rows(50, (i) => `${i * 10},${i},${i}`)).fs).toBe(100);
  });
  it("refuses to trust an irregular time column and asks for the rate", () => {
    const t = (i: number) => (i < 25 ? i * 0.008 : 0.2 + (i - 25) * 0.01).toFixed(4);
    const r = parseRecording("Time [s], RESP, PLETH\n" + rows(50, (i) => `${t(i)},0.3,${0.4 + i / 1000}`));
    expect(r.fs).toBeNull();
    expect(r.fsSource).toBe("none");
    expect(r.irColumn.trim()).toBe("PLETH");
    expect(r.warnings[0]).toMatch(/irregular/);
  });
  it("does the same when time goes backwards", () => {
    const r = parseRecording("t,ir\n" + rows(50, (i) => `${i === 30 ? 0 : i / 100},${i}`));
    expect(r.fs).toBeNull();
    expect(r.warnings.length).toBe(1);
  });
  it("accepts a single column, a 2-column file, and red / accelerometer columns by name", () => {
    expect(parseRecording(rows(20, (i) => String(i))).ir.length).toBe(20);
    expect(parseRecording(rows(20, (i) => `${i / 50},${i}`)).fs).toBe(50);
    const full = parseRecording("t,ir,red,ax,ay,az\n" + rows(20, (i) => `${i / 100},${i},${i + 1},0,0,1`));
    expect(full.red?.[3]).toBe(4);
    expect(full.accel?.[0]).toEqual([0, 0, 1]);
  });
  it("ignores an incomplete trailing row, and says so (real exported files are often cut off)", () => {
    const r = parseRecording("t,ir\n" + rows(20, (i) => `${i / 100},${i}`) + "\n0.2,\n0.21");
    expect(r.ir.length).toBe(20);
    expect(r.warnings.join(" ")).toMatch(/2 incomplete trailing row/);
  });
  it("still rejects a bad cell in the middle, even when the end is cut off", () => {
    expect(() => parseRecording("t,ir\n" + rows(20, (i) => (i === 5 ? "0.05,xyz" : `${i / 100},${i}`)) + "\n0.2,")).toThrow(/non-numeric/);
  });
  it("rejects non-numeric samples instead of guessing, and says where", () => {
    expect(() => parseRecording("t,ir\n" + rows(20, (i) => (i === 7 ? "0.07,abc" : `${i / 100},${i}`)))).toThrow(/1 non-numeric.*row 8/);
  });
  it.each([["", /empty/], ["t,ir\n1,2\n", /too few/], [Array(20).fill("1,2,3").join("\n"), /header/],
           ["a,b,c\n" + Array(20).fill("1,2,3").join("\n"), /No PPG column/]])("rejects bad file %#", (text, re) => {
    expect(() => parseRecording(text as string)).toThrow(re as RegExp);
  });
  it("falls back to the only remaining column when the header is otherwise unrecognised", () => {
    expect(parseRecording("time,counts\n" + rows(20, (i) => `${i / 100},${i}`)).irColumn).toBe("counts");
  });
  it("supports semicolon delimiters and skips comment lines", () => {
    const r = parseRecording("# exported\nt;ir\n" + rows(20, (i) => `${i / 100};${i}`));
    expect(r.fs).toBe(100);
  });
});

describe("dueCount / meanChannel", () => {
  it("counts samples due after elapsed real time, clamped to the recording", () => {
    expect(dueCount(0, 100, 1000)).toBe(0);
    expect(dueCount(1000, 100, 1000)).toBe(100);
    expect(dueCount(10_000_000, 100, 1000)).toBe(1000);
    expect(dueCount(-5, 100, 1000)).toBe(0);
  });
  it("averages one colour channel over the centre region only", () => {
    const w = 8, h = 8;
    const px = new Uint8ClampedArray(w * h * 4);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const centre = x >= 2 && x < 6 && y >= 2 && y < 6;
      px[(y * w + x) * 4] = centre ? 200 : 10;
      px[(y * w + x) * 4 + 1] = 50;
    }
    expect(meanChannel(px, w, h, 0)).toBe(200);
    expect(meanChannel(px, w, h, 1)).toBe(50);
  });
});

describe("ReplaySource (real-time scheduling)", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("emits samples at the recording's real rate, pauses, resumes, and ends", () => {
    const ir = Array.from({ length: 300 }, (_, i) => i);            // 3 s at 100 Hz
    const got: Sample[] = [];
    let ended = 0;
    const src = new ReplaySource({ ir, red: null, accel: null }, 100, { onSamples: (b) => got.push(...b), onError: () => {}, onEnd: () => ended++ });
    src.play();
    vi.advanceTimersByTime(1000);
    expect(got.length).toBeGreaterThanOrEqual(95);
    expect(got.length).toBeLessThanOrEqual(105);
    expect(got[0]).toEqual({ t: 0, ir: 0 });
    src.pause();
    const n = got.length;
    vi.advanceTimersByTime(2000);
    expect(got.length).toBe(n);                                     // nothing while paused
    src.play();
    vi.advanceTimersByTime(500);
    expect(got.length).toBeGreaterThan(n + 40);                     // resumes where it stopped, no burst of back-catch-up
    expect(got.length).toBeLessThan(n + 60);
    vi.advanceTimersByTime(5000);
    expect(got.length).toBe(300);
    expect(ended).toBe(1);
    expect(got.map((s) => s.ir)).toEqual(ir);                       // every sample, in order, exactly once
  });
});

describe("SerialSource (fake serial port)", () => {
  function fakePort(chunks: string[]) {
    const enc = new TextEncoder();
    let closed = false;
    const port: SerialPortLike = {
      async open() {},
      async close() { closed = true; },
      readable: new ReadableStream<Uint8Array>({
        start(c) { for (const ch of chunks) c.enqueue(enc.encode(ch)); c.close(); },
      }),
    };
    return { port, isClosed: () => closed };
  }

  it("decodes streamed lines (split mid-line), counts rejected ones, and reports closing", async () => {
    const { port } = fakePort(["# PIGMENTCAL v1\n10,100,200\n20,101,2", "01\ngarbage line\n30,102,202,0,0,1\n"]);
    const got: Sample[] = [];
    let closed = false;
    const src = new SerialSource(port, 115200, { onSamples: (b) => got.push(...b), onError: (e) => { throw e; }, onClosed: () => { closed = true; } });
    await src.start();
    await vi.waitFor(() => expect(closed).toBe(true));
    expect(got.map((s) => s.t)).toEqual([0.01, 0.02, 0.03]);
    expect(got[1]).toEqual({ t: 0.02, red: 101, ir: 201 });
    expect(got[2].accel).toEqual([0, 0, 1]);
    expect(src.lines).toBe(3);
    expect(src.rejected).toBe(1);
    expect(src.recent.at(-1)).toMatch(/30,102,202/);
  });

  it("stop() closes the port", async () => {
    const { port, isClosed } = fakePort([]);
    const src = new SerialSource(port, 115200, { onSamples: () => {}, onError: () => {} });
    await src.start();
    await src.stop();
    expect(isClosed()).toBe(true);
  });
});

describe("recordingToCsv (camera / replay / sensor recordings)", () => {
  // browser-clock times with jitter, as the camera source produces them
  const cam = Array.from({ length: 120 }, (_, i) => ({ t: 1523.456789 + i / 30 + (i % 3) * 0.002, ir: 120.123456789 + 5 * Math.sin(i / 5) }));
  it("times are seconds since the FIRST sample, the column is named for what it is, values are rounded, nothing is repaired", () => {
    const { csv, fileStem } = recordingToCsv(cam, "camera");
    const lines = csv.trimEnd().split("\n");
    expect(lines[0]).toMatch(/^# source=phone_camera; signal=mean RED channel .*camera has no infrared channel\); samples=120; duration_s=3\.9\d\d; mean_rate_hz=\d+\.\d\d; times=seconds since the first sample$/);
    expect(lines[1]).toBe("timestamp_s,ppg_camera_red");
    expect(lines[2]).toBe("0.0000,125.123".replace("125.123", cam[0].ir.toFixed(3)));
    expect(lines).toHaveLength(2 + 120);
    for (const l of lines.slice(2)) expect(l).toMatch(/^\d+\.\d{4},-?\d+(\.\d{1,3})?$/);                // no 17-digit floats, no browser-clock times
    expect(Number(lines[lines.length - 1].split(",")[0])).toBeCloseTo(cam[119].t - cam[0].t, 3);
    expect(fileStem).toBe("phone_camera_recording");
  });
  it("sensor / replay recordings keep integer counts and the accelerometer under the same names as the session CSV", () => {
    const rows = Array.from({ length: 20 }, (_, i) => ({ t: i / 100, ir: 90000 + i, red: 60000 + i, accel: [0.01, 0.02, 0.98] as [number, number, number] }));
    const lines = recordingToCsv(rows, "esp32").csv.trimEnd().split("\n");
    expect(lines[1]).toBe("timestamp_s,ir,red,accelerometer_x,accelerometer_y,accelerometer_z");
    expect(lines[2]).toBe("0.0000,90000,60000,0.0100,0.0200,0.9800");
  });
  it("a saved recording can be replayed: the file parses back to the same samples (the # line is ignored)", () => {
    const rows = Array.from({ length: 60 }, (_, i) => ({ t: 50 + i / 50, ir: 1000 + i * 3, red: 800 + i, accel: [0, 0, 1] as [number, number, number] }));
    const r = parseRecording(recordingToCsv(rows, "file").csv);
    expect(r.ir).toEqual(rows.map((x) => x.ir)); expect(r.red).toEqual(rows.map((x) => x.red));
    expect(r.fs).toBeCloseTo(50, 1); expect(r.accel).toHaveLength(60);
  });
  it("a camera recording replays with its signal column recognised (no guessing)", () => {
    const r = parseRecording(recordingToCsv(cam, "camera").csv);
    expect(r.ir).toHaveLength(120); expect(r.irColumn).toBe("ppg_camera_red");
    expect(r.warnings.join(" ")).toMatch(/irregular/);                         // honest: camera frames are not evenly spaced, so the user must enter the rate
  });
});
