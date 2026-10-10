import { describe, expect, it } from "vitest";
import type { ResearchState } from "./api";
import { notAResult, type ResearchStatusInfo } from "./researchContext";
import { labelForState } from "./status";

const S = (state: ResearchState, results_allowed = false): ResearchStatusInfo => ({ state, label: state, results_allowed, verified_data: false, failed_checks: [] });

describe("when the 'not a research result' banner appears", () => {
  it("for every state the backend does not call a result, except 'no data' (nothing is shown then)", () => {
    for (const s of ["SOFTWARE_TEST_DATA", "SIMULATED_HARDWARE_DATA", "UNVERIFIED_EXTERNAL_DATA", "UNVERIFIED_DATA", "VERIFIED_RESEARCH_DATA"] as ResearchState[]) expect(notAResult(S(s))).toBe(true);
    expect(notAResult(S("NO_DATA"))).toBe(false);
  });
  it("never for a real result, and never while the status is still unknown", () => {
    expect(notAResult(S("RESEARCH_RESULTS", true))).toBe(false);
    expect(notAResult(undefined)).toBe(false);
  });
  it("labels come only from the backend state; unknown values fall back to UNVERIFIED DATA", () => {
    expect(labelForState("RESEARCH_RESULTS")).toBe("REAL RESEARCH RESULTS");
    expect(labelForState("UNVERIFIED_DATA")).toBe("UNVERIFIED DATA");
    expect(labelForState("???")).toBe("UNVERIFIED DATA");
    expect(labelForState(undefined)).toBe("UNVERIFIED DATA");
  });
});
