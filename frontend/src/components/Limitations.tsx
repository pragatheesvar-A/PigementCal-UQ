import { useResearchStatus } from "../lib/researchContext";

/** Statements that depend on the project state; shown only while they are true (decided by the backend gate). */
export const STATE_LIMITATIONS = {
  noData: "No verified research dataset is currently available.",
  noResults: "No model has been trained and conformally calibrated on verified research data, so no research results exist.",
};

export const LIMITATIONS = [
  "The MAX30102 hardware is not clinically validated and has not been hardware-tested by the authors of this repository.",
  "Small-subgroup risk: groups with few participants are reported as INSUFFICIENT DATA, and the remaining ones may have wide confidence intervals.",
  "Conformal coverage holds only under the calibration assumptions (calibration and future data being exchangeable) and is not a probability for an individual reading.",
  "Device variability: results from one sensor or oximeter do not transfer automatically to another.",
  "Motion and low perfusion degrade the signal; the system reports this and abstains rather than guessing.",
  "Prospective validation against reference SaO₂ in a properly approved study is required before any further claim.",
];

export default function Limitations({ compact }: { compact?: boolean }) {
  const rs = useResearchStatus();
  const lines = [...(rs?.verified_data ? [] : [STATE_LIMITATIONS.noData]), ...(rs?.results_allowed ? [] : [STATE_LIMITATIONS.noResults]), ...LIMITATIONS];
  return (
    <ul className={`list-disc space-y-1 pl-5 text-slate-700 ${compact ? "text-xs" : "text-sm"}`}>
      {lines.map((l) => <li key={l}>{l}</li>)}
    </ul>
  );
}
