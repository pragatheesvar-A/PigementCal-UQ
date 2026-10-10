import { ShieldAlert } from "lucide-react";
import { notAResult, useResearchStatus } from "../lib/researchContext";

export const SAFETY = "Not a diagnostic device. Not clinically validated.";
export const NO_CLAIMS = "Nothing here claims bias elimination, clinical effectiveness, guaranteed fairness or guaranteed accuracy.";

/** Shown wherever models or intervals are displayed while the backend gate says they are not research results. */
export function NotAResultBanner({ compact }: { compact?: boolean }) {
  const s = useResearchStatus();
  if (!notAResult(s)) return null;
  return (
    <div role="status" className={compact ? "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-800" : "rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-800"}>
      {s!.label}. These numbers do not count as research results.
    </div>
  );
}

export function SafetyNote() {
  return (
    <p className="flex items-start gap-2 rounded-xl bg-amber-50 px-4 py-3 text-xs text-amber-900">
      <ShieldAlert size={14} className="mt-0.5 shrink-0" />
      <span><strong>{SAFETY}</strong> {NO_CLAIMS}</span>
    </p>
  );
}

export function Unavailable({ title, message }: { title: string; message: string }) {
  return (
    <section className="card p-6" aria-label={`${title} not available`}>
      <h3 className="font-bold text-navy-900">{title}: not available</h3>
      <p className="mt-2 text-sm text-slate-600">{message}</p>
      <p className="mt-1 text-xs text-slate-500">Nothing is shown until real, verified project data has been loaded, split, and the models trained and calibrated. No placeholder numbers are displayed.</p>
    </section>
  );
}
