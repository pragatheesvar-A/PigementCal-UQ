import { describe, expect, it } from "vitest";
import type { Health, ResearchState } from "./api";
import { researchStatus, statusLines } from "./status";

const H = (state?: ResearchState, extra: Partial<Health> = {}): Health => ({
  status: "ok", version: "1", model: { trained: false, note: "" }, conformal: { calibrated: false },
  dataset: { loaded: false, verified: false, rows: 0, participants: 0, note: "" },
  ...(state ? { research_status: { state, label: state, results_allowed: state === "RESEARCH_RESULTS", verified_data: state === "VERIFIED_RESEARCH_DATA" || state === "RESEARCH_RESULTS", failed_checks: [] } } : {}),
  ...extra,
});

describe("research status badge mirrors the backend gate", () => {
  it("shows NO RESEARCH DATA only for NO_DATA, and STATUS UNKNOWN while the service is unreachable", () => {
    expect(researchStatus(null)).toBe("STATUS UNKNOWN");
    expect(statusLines(null).data).toMatch(/^UNKNOWN/);
    expect(researchStatus(H("NO_DATA"))).toBe("NO RESEARCH DATA");
  });
  it("maps every backend state to its own label", () => {
    expect(researchStatus(H("SOFTWARE_TEST_DATA"))).toBe("SOFTWARE TEST DATA");
    expect(researchStatus(H("SIMULATED_HARDWARE_DATA"))).toBe("SIMULATED HARDWARE DATA");
    expect(researchStatus(H("UNVERIFIED_EXTERNAL_DATA"))).toBe("UNVERIFIED EXTERNAL DATA");
    expect(researchStatus(H("UNVERIFIED_DATA"))).toBe("UNVERIFIED DATA");
    expect(researchStatus(H("VERIFIED_RESEARCH_DATA"))).toBe("VERIFIED RESEARCH DATA");
    expect(researchStatus(H("RESEARCH_RESULTS"))).toBe("REAL RESEARCH RESULTS");
  });
  it("cannot be upgraded by the dataset, model or conformal flags: only the backend state counts", () => {
    const h = H("UNVERIFIED_DATA", { dataset: { loaded: true, verified: true, rows: 500, participants: 50, note: "" }, model: { trained: true, note: "" }, conformal: { calibrated: true } });
    expect(researchStatus(h)).toBe("UNVERIFIED DATA");
    expect(statusLines(h).results).toBe("NOT AVAILABLE — REAL RESEARCH DATA REQUIRED");
    expect(statusLines(h).model).toBe("TRAINED ON UNVERIFIED DATA — NOT RESEARCH VALIDATED");     // described truthfully, but never as TRAINED research
    expect(statusLines(h).conformal).toBe("CALIBRATED ON UNVERIFIED DATA — NOT RESEARCH VALIDATED");
  });
  it("synthetic software-test data that was trained and calibrated is described as exactly that", () => {
    const l = statusLines(H("SOFTWARE_TEST_DATA", { dataset: { loaded: true, verified: false, rows: 1440, participants: 180, note: "" }, model: { trained: true, note: "" }, conformal: { calibrated: true } }));
    expect(l.model).toBe("TRAINED ON SYNTHETIC TEST DATA — NOT RESEARCH VALIDATED");
    expect(l.conformal).toBe("CALIBRATED ON SYNTHETIC TEST DATA — NOT RESEARCH VALIDATED");
    expect(l.results).toBe("NOT AVAILABLE — REAL RESEARCH DATA REQUIRED");
  });
  it("a missing or unknown backend status is never shown as better than UNVERIFIED", () => {
    expect(researchStatus(H(undefined))).toBe("UNVERIFIED DATA");
    expect(researchStatus({ ...H("NO_DATA"), research_status: { state: "SOMETHING_NEW" as ResearchState, label: "", results_allowed: true, verified_data: true, failed_checks: [] } })).toBe("UNVERIFIED DATA");
  });
  it("only a RESEARCH_RESULTS state reports evaluated results", () => {
    const ok = H("RESEARCH_RESULTS", { model: { trained: true, note: "" }, conformal: { calibrated: true }, dataset: { loaded: true, verified: true, rows: 90, participants: 30, note: "" } });
    const l = statusLines(ok);
    expect(l.model).toBe("TRAINED"); expect(l.conformal).toBe("CALIBRATED"); expect(l.results).toMatch(/^EVALUATED/);
    expect(l.data).toMatch(/^VERIFIED RESEARCH DATA/);
    expect(statusLines(H("VERIFIED_RESEARCH_DATA")).results).toBe("NOT EVALUATED");
  });
  it("the empty project shows the not-trained / not-calibrated / not-evaluated lines", () => {
    const l = statusLines(H("NO_DATA"));
    expect(l.model).toBe("NOT TRAINED"); expect(l.conformal).toBe("NOT CALIBRATED"); expect(l.results).toBe("NOT AVAILABLE — REAL RESEARCH DATA REQUIRED");
    expect(l.hardware).toMatch(/^NOT TESTED/); expect(l.data).toMatch(/^NO RESEARCH DATA/);
  });
});
