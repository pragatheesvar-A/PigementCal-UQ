import { describe, expect, it, vi } from "vitest";
import { parsePacket, parseSerialLine, RingBuffer, type Sample } from "./acquisition";
import { SerialSource, type SerialPortLike } from "./sources";
import { CSV_HEADER, SessionRecorder, connectionLabel, idProblem, serialErrorMessage } from "./session";

const J = (o: object) => JSON.stringify(o);

describe("JSON packet parsing", () => {
  it("parses the documented packet (timestamp in ms -> seconds)", () => {
    expect(parsePacket(J({ timestamp: 123456, red: 12345, ir: 23456 }))).toEqual({ kind: "sample", sample: { t: 123.456, red: 12345, ir: 23456 } });
  });
  it("parses the optional accelerometer", () => {
    const p = parsePacket(J({ timestamp: 10, red: 1, ir: 2, accelerometer_x: 0.1, accelerometer_y: 0.2, accelerometer_z: 0.9 }));
    expect(p.kind === "sample" && p.sample.accel).toEqual([0.1, 0.2, 0.9]);
  });
  it("rejects an incomplete accelerometer instead of guessing", () => {
    expect(parsePacket(J({ timestamp: 10, red: 1, ir: 2, accelerometer_x: 0.1 }))).toMatchObject({ kind: "error", code: "corrupted" });
  });
  it("names each missing field", () => {
    expect(parsePacket(J({ timestamp: 1, red: 1 }))).toMatchObject({ kind: "error", code: "missing_ir" });
    expect(parsePacket(J({ timestamp: 1, ir: 1 }))).toMatchObject({ kind: "error", code: "missing_red" });
    expect(parsePacket(J({ red: 1, ir: 1 }))).toMatchObject({ kind: "error", code: "missing_timestamp" });
  });
  it("rejects invalid JSON, truncated lines and non-objects", () => {
    for (const bad of ['{"timestamp":1,"red":2,"ir":', "{not json}", "[1,2,3]", "{"]) expect(parsePacket(bad)).toMatchObject({ kind: "error", code: "invalid_json" });
  });
  it("rejects corrupted values: strings, null-like, negative, NaN, Infinity", () => {
    expect(parsePacket(J({ timestamp: 1, red: "abc", ir: 2 }))).toMatchObject({ code: "corrupted" });
    expect(parsePacket(J({ timestamp: 1, red: 1, ir: -5 }))).toMatchObject({ code: "corrupted" });
    expect(parsePacket('{"timestamp":1,"red":1,"ir":1e999}')).toMatchObject({ code: "corrupted" });
    expect(parsePacket(J({ timestamp: 1, red: null, ir: 2 }))).toMatchObject({ code: "missing_red" });
  });
  it("skips blank and comment lines, and still accepts the legacy CSV line", () => {
    expect(parsePacket("")).toEqual({ kind: "skip" });
    expect(parsePacket("# PIGMENTCAL,v2-json")).toEqual({ kind: "skip" });
    expect(parseSerialLine("1500,81234,101234")).toEqual({ t: 1.5, red: 81234, ir: 101234 });
    expect(parseSerialLine("garbage")).toBeNull();
  });
  it("never throws on arbitrary input", () => {
    for (const x of ["\u0000\u0001", "{{{{", "}", '{"a":', "null", "1", '"x"', "{\"timestamp\":1,\"red\":1,\"ir\":1}}"]) expect(() => parsePacket(x)).not.toThrow();
  });
});

describe("buffering", () => {
  it("keeps only the newest window of JSON samples", () => {
    const rb = new RingBuffer(2);
    const batch: Sample[] = [];
    for (let i = 0; i < 500; i++) { const p = parsePacket(J({ timestamp: i * 10, red: 1, ir: 2 })); if (p.kind === "sample") batch.push(p.sample); }
    rb.push(batch);
    expect(rb.seconds).toBeLessThanOrEqual(2);
    expect(rb.rate).toBeCloseTo(100, 0);
  });
});

describe("anonymous IDs", () => {
  it("accepts anonymous IDs", () => { expect(idProblem("P001")).toBeNull(); expect(idProblem("P001_S01")).toBeNull(); });
  it("rejects empty, email, phone, spaces (names) and over-long values", () => {
    for (const bad of ["", "  ", "a@b.com", "+91 98765 43210", "9876543210", "John Smith", "x".repeat(65)]) expect(idProblem(bad)).not.toBeNull();
  });
});

const sample = (t: number, extra: Partial<Sample> = {}): Sample => ({ t, red: 100 + t, ir: 200 + t, ...extra });

describe("SessionRecorder", () => {
  it("does not record before start or after stop", () => {
    const r = new SessionRecorder();
    r.add([sample(0)]);
    expect(r.samples).toBe(0);
    expect(r.start("P001", "P001_S01")).toBeNull();
    r.add([sample(1), sample(2)]);
    r.stop();
    r.add([sample(3)]);
    expect(r.samples).toBe(2);
    expect(r.state).toBe("stopped");
  });
  it("refuses to start with bad IDs, and does not start twice", () => {
    const r = new SessionRecorder();
    expect(r.start("", "S1")).toMatch(/Participant ID/);
    expect(r.start("P001", "a b")).toMatch(/Session ID/);
    expect(r.state).toBe("idle");
    expect(r.start("P001", "S1")).toBeNull();
    expect(r.start("P002", "S2")).toMatch(/already recording/);
  });
  it("drops repeated or backwards timestamps and counts them", () => {
    const r = new SessionRecorder(); r.start("P001", "S1");
    r.add([sample(1), sample(1), sample(0.5), sample(2)]);
    expect(r.samples).toBe(2); expect(r.dropped).toBe(2);
  });
  it("reports samples and duration", () => {
    const r = new SessionRecorder(); r.start("P001", "S1");
    r.add([sample(10), sample(11), sample(12.5)]);
    expect(r.samples).toBe(3); expect(r.duration).toBeCloseTo(2.5);
  });
  it("writes the documented CSV: required header, IDs on every row, time from 0, empty accelerometer cells, no SaO2 / ITA", () => {
    const r = new SessionRecorder(); r.start("P001", "P001_S01");
    r.add([sample(10), sample(10.01, { accel: [0.1, 0.2, 0.9] })]);
    r.stop();
    const lines = r.toCsv().trim().split("\n");
    expect(lines[0]).toBe("participant_id,session_id,timestamp,red,ir,accelerometer_x,accelerometer_y,accelerometer_z");
    expect(lines[0].split(",")).toEqual([...CSV_HEADER]);
    expect(lines[1]).toBe("P001,P001_S01,0.000,110,210,,,");
    expect(lines[2]).toBe("P001,P001_S01,0.010,110.01,210.01,0.1,0.2,0.9");
    expect(r.toCsv()).not.toMatch(/sao2|ita|spo2/i);
    expect(r.fileName()).toBe("P001_P001_S01.csv");
  });
  it("keeps recorded samples after a disconnect (stop) so they can still be saved", () => {
    const r = new SessionRecorder(); r.start("P001", "S1"); r.add([sample(1), sample(2)]);
    r.stop();
    expect(r.hasData).toBe(true);
    expect(r.toCsv().trim().split("\n")).toHaveLength(3);
  });
  it("starting a new session clears the previous one", () => {
    const r = new SessionRecorder(); r.start("P001", "S1"); r.add([sample(1)]); r.stop();
    r.start("P001", "S2");
    expect(r.samples).toBe(0);
  });
});

describe("connection status", () => {
  const base = { supported: true, connected: false, wasConnected: false, lastDataAgeMs: null };
  it("covers every state", () => {
    expect(connectionLabel({ ...base, supported: false }).label).toBe("UNSUPPORTED BROWSER");
    expect(connectionLabel(base).label).toBe("DISCONNECTED");
    expect(connectionLabel({ ...base, wasConnected: true }).label).toBe("RECONNECT REQUIRED");
    expect(connectionLabel({ ...base, connected: true }).label).toBe("CONNECTED");
  });
  it("flags a sensor that stopped sending data", () => {
    expect(connectionLabel({ ...base, connected: true, lastDataAgeMs: 100 }).note).toBe("Receiving data.");
    expect(connectionLabel({ ...base, connected: true, lastDataAgeMs: 5000 }).note).toMatch(/stopped sending data/);
  });
  it("gives friendly serial permission errors", () => {
    expect(serialErrorMessage({ name: "NotFoundError" })).toMatch(/No port/);
    expect(serialErrorMessage({ name: "SecurityError" })).toMatch(/Permission/);
    expect(serialErrorMessage({ name: "NetworkError" })).toMatch(/USB cable/);
  });
});

describe("SerialSource with JSON packets and disconnect", () => {
  function port(chunks: string[], thenError?: Error) {
    const enc = new TextEncoder();
    let i = 0;
    const p: SerialPortLike = {
      async open() {}, async close() {},
      readable: new ReadableStream<Uint8Array>({
        pull(c) { if (i < chunks.length) c.enqueue(enc.encode(chunks[i++])); else if (thenError) c.error(thenError); else c.close(); },
      }),
    };
    return p;
  }
  it("decodes JSON lines split across chunks, counts rejects by reason, and reports the stream closing (USB unplugged)", async () => {
    const a = J({ timestamp: 10, red: 1, ir: 2 }), b = J({ timestamp: 20, red: 3, ir: 4 });
    const got: Sample[] = []; let closed = false;
    const src = new SerialSource(port([`${a}\n${b.slice(0, 9)}`, `${b.slice(9)}\n{"timestamp":30,"red":1}\n{bad\n`]), 115200, { onSamples: (x) => got.push(...x), onError: (e) => { throw e; }, onClosed: () => { closed = true; } });
    await src.start();
    await vi.waitFor(() => expect(closed).toBe(true));
    expect(got.map((s) => s.t)).toEqual([0.01, 0.02]);
    expect(src.rejected).toBe(2);
    expect(src.errors).toEqual({ missing_ir: 1, invalid_json: 1 });
    expect(src.lastError).toMatch(/JSON/);
    expect(src.lastDataAt).not.toBeNull();
  });
  it("reports a read error (device removed mid-stream) through onError", async () => {
    let err: Error | null = null; let closed = false;
    const src = new SerialSource(port([`${J({ timestamp: 1, red: 1, ir: 1 })}\n`], new Error("device lost")), 115200, { onSamples: () => {}, onError: (e) => { err = e; }, onClosed: () => { closed = true; } });
    await src.start();
    await vi.waitFor(() => expect(closed).toBe(true));
    expect(err).not.toBeNull();
    expect((err as unknown as Error).message).toMatch(/device lost/);
  });
});
