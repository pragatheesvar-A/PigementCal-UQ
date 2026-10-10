import { useEffect, useState } from "react";
import { Badge } from "../components/ui";
import { SafetyNote } from "../components/Safety";
import Limitations from "../components/Limitations";
import type { Health } from "../lib/api";
import { STATUS_TONE, researchStatus, statusLines } from "../lib/status";
import { fetchValidation, fmt, type Loaded, type ValidationReport } from "../lib/validationApi";

const NE = "NOT EVALUATED";
const FLOW = ["PPG", "signal quality", "SpO₂ / PI", "objective ITA", "feature engineering", "Ridge + LightGBM", "CQR", "ITA × PI Mondrian calibration", "reliability / abstention"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="card p-5"><h3 className="font-bold text-navy-900">{title}</h3><div className="mt-2 space-y-2 text-sm text-slate-700">{children}</div></section>;
}

export default function Summary({ health }: { health: Health | null }) {
  const [r, setR] = useState<Loaded<ValidationReport> | null>(null);
  useEffect(() => { fetchValidation().then(setR); }, []);
  const rep = r?.ok ? r.data : null;
  const lines = statusLines(health), st = researchStatus(health);
  const get = (rows: { metric: string; estimate: number | null }[] | undefined, m: string) => rows?.find((x) => x.metric === m)?.estimate ?? null;
  const cf = rep?.conformal.available ? rep.conformal : null;
  return (
    <div className="space-y-5">
      <h1 className="sr-only">Research Summary</h1>
      <div className="flex flex-wrap items-center gap-2"><Badge tone={STATUS_TONE[st]} dot>{st}</Badge></div>
      <Section title="Problem"><p>Pulse oximetry may have reliability limitations under varying pigmentation and perfusion conditions. A single displayed number gives no signal about when it should not be trusted.</p></Section>
      <Section title="Research question"><p>Can a conformal reliability layer provide empirically calibrated uncertainty across objective pigmentation × perfusion subgroups? (The layer accepts a device identifier; cross-device generalization has not been evaluated.)</p></Section>
      <Section title="Method">
        <ol className="flex flex-wrap items-center gap-1 text-xs" aria-label="Method pipeline">
          {FLOW.map((s, i) => <li key={s} className="flex items-center gap-1"><span className="rounded-lg bg-indigo-50 px-2.5 py-1.5 text-indigo-700">{s}</span>{i < FLOW.length - 1 && <span aria-hidden className="text-slate-300">→</span>}</li>)}
        </ol>
        <p>Pigmentation is measured objectively (ITA from L*, a*, b*), never inferred from race. Models are tuned by participant-grouped cross-validation on the training split; conformal calibration uses a separate calibration split; all reported results use the held-out test split with participant-level bootstrap confidence intervals.</p>
      </Section>
      <Section title="Novelty"><p>The proposed contribution is reliability bounds that are calibrated within subgroups of objective pigmentation and perfusion, with abstention when the evidence is insufficient. This is the intended method: no real-data validation of it has been performed yet, and the work does not claim to eliminate bias.</p></Section>
      <Section title="Research status">
        <dl className="grid gap-2 sm:grid-cols-2">
          {([["Data", lines.data], ["Model", lines.model], ["Conformal", lines.conformal], ["Research validation", lines.results], ["Hardware", lines.hardware]] as const).map(([k, v]) => (
            <div key={k} className="rounded-xl bg-slate-50 px-3 py-2"><dt className="text-[11px] font-semibold uppercase text-slate-500">{k}</dt><dd className="font-bold text-navy-900">{v}</dd></div>
          ))}
        </dl>
      </Section>
      <Section title="Results">
        {rep ? (
          <ul className="list-disc space-y-1 pl-5">
            {!health?.research_status?.results_allowed && <li><strong>{lines.data}.</strong> The numbers below describe the loaded dataset only and are not a research result.</li>}
            <li>MAE on the held-out test split: raw SpO₂ {fmt(get(rep.overall.spo2_as_is, "MAE"))}, Ridge {fmt(get(rep.overall.ridge, "MAE"))}, LightGBM {fmt(get(rep.overall.lightgbm, "MAE"))} percentage points (confidence intervals: Research Results).</li>
            <li>Conformal coverage on test (stated target {cf ? `${(cf.target_coverage * 100).toFixed(0)}%` : "—"}): {cf ? fmt(get(cf.overall.metrics, "Coverage"), 3) : NE}.</li>
            <li>These describe this dataset only. They do not establish fairness, bias elimination or clinical performance.</li>
          </ul>
        ) : <p><strong>{NE}.</strong> {r && !r.ok ? r.message : ""} No numbers are shown because no real data has been trained and calibrated.</p>}
      </Section>
      <Section title="Limitations"><Limitations /></Section>
      <Section title="Future work"><p>Real data collection with ESP32 + MAX30102, reference SaO₂ and objective L*a*b*/ITA, matched by participant and session; then training, calibration and prospective validation in an approved study.</p></Section>
      <SafetyNote />
    </div>
  );
}
