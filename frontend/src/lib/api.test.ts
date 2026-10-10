import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchHealth } from "./api";
import { OFFLINE_MESSAGE, WRONG_SERVICE_MESSAGE, failMessage, gatewayDown, unavailableMessage } from "./http";
import { fetchConformalStatus, fetchCoverage, predictConformal } from "./conformalApi";
import { fetchModelMetrics } from "./modelApi";
import { fetchStatus } from "./collectionApi";
import { fetchStatus as fetchDatasetStatus } from "./datasetApi";
import { fetchValidation } from "./validationApi";

const reply = (status: number, body: unknown, json = true) =>
  vi.fn(async () => new Response(json ? JSON.stringify(body) : String(body), { status, headers: { "Content-Type": json ? "application/json" : "text/plain" } }));

afterEach(() => vi.unstubAllGlobals());

describe("gateway errors mean 'not reachable'", () => {
  it("maps 502/503/504 and nothing else", () => {
    expect([502, 503, 504].every(gatewayDown)).toBe(true);
    expect([200, 404, 422, 500].some(gatewayDown)).toBe(false);
    expect(failMessage(502, "x")).toBe(OFFLINE_MESSAGE);
    expect(failMessage(500, "fallback")).toBe("fallback");
  });
  it("every API client reports a dead backend as unreachable, not 'unexpected error'", async () => {
    vi.stubGlobal("fetch", reply(502, "Bad Gateway", false));
    await expect(fetchStatus()).rejects.toThrow(/not reachable/);
    await expect(fetchDatasetStatus()).rejects.toThrow(/not reachable/);
    await expect(fetchCoverage()).rejects.toThrow(/not reachable/);
    await expect(fetchModelMetrics()).rejects.toThrow(/not reachable/);
    expect(await predictConformal({})).toEqual({ unavailable: OFFLINE_MESSAGE });
    expect(await fetchValidation()).toMatchObject({ ok: false });
  });
  it("a real server error with a JSON message keeps that message", async () => {
    vi.stubGlobal("fetch", reply(500, { errors: [{ code: "internal_error", message: "The service hit an unexpected problem (X)." }] }));
    await expect(fetchStatus()).rejects.toThrow(/unexpected problem \(X\)/);
  });
});

describe("health accepts only this application", () => {
  it("accepts the PigmentCal-UQ answer", async () => {
    vi.stubGlobal("fetch", reply(200, { status: "ok", app: "PigmentCal-UQ", version: "1", dataset: { loaded: false, rows: 0, participants: 0, note: "" } }));
    expect((await fetchHealth()).version).toBe("1");
  });
  it("rejects another service answering 200 on the same port", async () => {
    vi.stubGlobal("fetch", reply(200, { ok: true, env: "dev" }));
    await expect(fetchHealth()).rejects.toThrow(WRONG_SERVICE_MESSAGE);
  });
  it("rejects a non-JSON 200 and reports a 502 as unreachable", async () => {
    vi.stubGlobal("fetch", reply(200, "<html></html>", false));
    await expect(fetchHealth()).rejects.toThrow(WRONG_SERVICE_MESSAGE);
    vi.stubGlobal("fetch", reply(502, "", false));
    await expect(fetchHealth()).rejects.toThrow(/not reachable/);
  });
});

describe("optional resources that do not exist yet are an empty state, not a result", () => {
  it("detects available:false and its reason", () => {
    expect(unavailableMessage({ available: false, errors: [{ message: "Train first." }] })).toBe("Train first.");
    expect(unavailableMessage({ available: true })).toBeNull();
    expect(unavailableMessage({ rows: [] })).toBeNull();
    expect(unavailableMessage({ available: false, fitted: false, message: "CONFORMAL MODEL NOT AVAILABLE" })).toBeNull();   // a status payload, not the envelope
  });
  it("model metrics and conformal coverage never return fake data when unavailable", async () => {
    vi.stubGlobal("fetch", reply(200, { available: false, errors: [{ code: "model_not_trained", message: "No models yet." }] }));
    await expect(fetchModelMetrics()).rejects.toThrow("No models yet.");
    await expect(fetchCoverage()).rejects.toThrow("No models yet.");
  });
  it("the conformal STATUS payload (which carries available:false when not fitted) is returned as data, not treated as an error", async () => {
    vi.stubGlobal("fetch", reply(200, { available: false, message: "CONFORMAL MODEL NOT AVAILABLE", fitted: false, can_fit: false, blockers: ["x"] }));
    expect((await fetchConformalStatus()).fitted).toBe(false);
  });
  it("a conformal prediction before calibration is an 'unavailable' answer with the reason", async () => {
    vi.stubGlobal("fetch", reply(200, { available: false, errors: [{ code: "not_calibrated", message: "CONFORMAL MODEL NOT AVAILABLE." }] }));
    expect(await predictConformal({})).toEqual({ unavailable: "CONFORMAL MODEL NOT AVAILABLE." });
  });
  it("validation and explainability reports surface the reason", async () => {
    vi.stubGlobal("fetch", reply(200, { available: false, errors: [{ message: "Train the models first." }] }));
    expect(await fetchValidation()).toEqual({ ok: false, message: "Train the models first." });
  });
});
