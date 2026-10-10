import { useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, CircleSlash, Info, OctagonAlert } from "lucide-react";
import type { Assessment, State } from "../../lib/reliabilityApi";
import type { ConformalResult } from "../../lib/conformalApi";
import { Badge, Term } from "../ui";
import { NotAResultBanner } from "../Safety";

const STATES: Record<State, { icon: typeof CheckCircle2; text: string; chip: string; bar: string; tip: string }> = {
  GREEN: { icon: CheckCircle2, text: "text-emerald-600", chip: "bg-emerald-500", bar: "from-emerald-400 to-emerald-500",
    tip: "No rule raised a flag: good signal, low motion and adequate perfusion." },
  AMBER: { icon: AlertTriangle, text: "text-amber-600", chip: "bg-amber-500", bar: "from-amber-400 to-amber-500",
    tip: "At least one condition (moderate signal, lower perfusion or some motion) increases uncertainty. Use caution." },
  RED: { icon: OctagonAlert, text: "text-rose-600", chip: "bg-rose-500", bar: "from-rose-400 to-rose-500",
    tip: "Several degrading conditions occur together (their configured points reach the RED threshold)." },
  ABSTAIN: { icon: CircleSlash, text: "text-slate-600", chip: "bg-slate-500", bar: "from-slate-400 to-slate-500",
    tip: "The system declines to assess: poor signal or high motion. It does not try to repair the reading." },
};
const ORDER: State[] = ["GREEN", "AMBER", "RED", "ABSTAIN"];

const SEV: Record<string, string> = { info: "bg-emerald-500", warning: "bg-amber-500", critical: "bg-rose-500" };

function Metric({ label, value, sub, big }: { label: ReactNode; value: ReactNode; sub?: string; big?: boolean }) {
  return (
    <div className="rounded-2xl bg-slate-50 p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 font-bold text-navy-900 ${big ? "text-4xl" : "text-2xl"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function Scale({ current }: { current: State }) {
  return (
    <div>
      <div className="grid grid-cols-4 gap-2" role="list" aria-label="Reliability scale">
        {ORDER.map((s) => {
          const on = s === current;
          return (
            <div key={s} role="listitem" tabIndex={0} aria-current={on ? "true" : undefined} className="group relative outline-none">
              <div className={`rounded-xl px-2 py-2.5 text-center text-xs font-bold tracking-wide transition-all duration-300 ${
                on ? `${STATES[s].chip} scale-105 text-white shadow-md` : "bg-slate-100 text-slate-400"}`}>
                {s}
              </div>
              <span role="tooltip" className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-56 -translate-x-1/2 rounded-xl bg-navy-900 p-3 text-xs leading-relaxed text-slate-100 shadow-xl group-hover:block group-focus:block">
                {STATES[s].tip}
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-slate-500">Current: <strong>{current}</strong> — {STATES[current].tip}</p>
    </div>
  );
}

function Pipeline() {
  const steps = ["Inputs", "Feature engineering", "Rule engine", "Reliability state", "Explanation"];
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-xs font-medium text-slate-600">
      {steps.map((s, i) => (
        <li key={s} className="flex items-center gap-1">
          <span className="rounded-lg bg-indigo-50 px-2.5 py-1.5 text-indigo-700">{s}</span>
          {i < steps.length - 1 && <span aria-hidden className="text-slate-300">→</span>}
        </li>
      ))}
    </ol>
  );
}

const CELL_CHIP: Record<string, string> = { CALIBRATED: "bg-emerald-100 text-emerald-800", MERGED: "bg-amber-100 text-amber-900", INSUFFICIENT: "bg-rose-100 text-rose-800" };

export function ConformalCard({ c }: { c: ConformalResult | { unavailable: string } }) {
  if ("unavailable" in c) {
    return (
      <section className="card p-6" aria-label="Calibrated reliability">
        <h3 className="font-bold text-navy-900">Calibrated reliability (conformal)</h3>
        <p className="mt-2 text-sm font-bold text-slate-700">CONFORMAL MODEL NOT AVAILABLE</p>
        <p className="mt-1 text-sm text-slate-600">{c.unavailable}</p>
        <p className="mt-1 text-xs text-slate-500">Conformal model not available — real research calibration required. No predicted SaO₂, interval or lower bound is shown; the state below comes from the rule engine only.</p>
      </section>
    );
  }
  const st = STATES[c.reliability_state];
  const Icon = st.icon;
  const tiles: [string, ReactNode, string?][] = [
    ["Observed SpO₂", `${c.spo2}%`],
    ["Predicted SaO₂", c.predicted_sao2 === null ? "—" : `${c.predicted_sao2}%`, "model median"],
    ["Calibrated interval", c.interval ? `${c.interval.lower}–${c.interval.upper}%` : "—", c.interval ? `width ${c.interval.width} pts` : undefined],
    ["Lower bound", c.lower_bound === null ? "—" : `${c.lower_bound}%`, "conservative signal"],
    ["Perfusion index", c.pi.toFixed(2), `${c.pi_group.toUpperCase()} PI group`],
    ["Signal quality", c.signal_quality ?? "—"],
    ["Motion", c.motion ?? "—"],
    ["ITA", `${c.ita.toFixed(1)}°`, `${c.ita_group.toUpperCase()} group`],
  ];
  return (
    <section className="card overflow-hidden" aria-label="Calibrated reliability">
      <div className={`h-1.5 bg-gradient-to-r ${st.bar}`} />
      <div className="space-y-4 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-bold text-navy-900">Calibrated reliability (conformal)</h3>
            <p className="text-xs text-slate-500">{c.method} · target coverage {(c.target_coverage * 100).toFixed(0)}%</p>
          </div>
          <div className="text-right">
            <div className={`flex items-center justify-end gap-2 text-3xl font-bold ${st.text}`}><Icon size={28} /> {c.reliability_state}</div>
            <div className={`text-sm font-bold ${st.text}`}>{c.status}</div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {tiles.map(([k, v, sub]) => (
            <div key={k} className="rounded-xl bg-slate-50 px-3 py-2.5">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{k}</div>
              <div className="mt-0.5 text-xl font-bold text-navy-900">{v}</div>
              {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Calibration cell</span>
          <span className="font-semibold text-navy-900">{c.cell.label.toUpperCase()}</span>
          <span className={`rounded px-2 py-0.5 text-[11px] font-bold ${CELL_CHIP[c.cell.status]}`}>{c.cell.status === "INSUFFICIENT" ? "INSUFFICIENT CALIBRATION DATA" : c.cell.status}</span>
          <span className="text-xs text-slate-500">{c.cell.n_participants} calibration participants</span>
        </div>
        <div>
          <div className="text-sm font-bold text-navy-900">Reason</div>
          <ul className="mt-2 space-y-2.5">
            {c.reasons.map((x) => (
              <li key={x.code} className="flex gap-3 text-sm">
                <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${SEV[x.severity]}`} />
                <span><strong className="text-navy-900">{x.title}.</strong> <span className="text-slate-600">{x.text}</span></span>
              </li>
            ))}
          </ul>
        </div>
        <NotAResultBanner compact />
        <p className="rounded-xl bg-slate-50 px-3 py-2.5 text-xs text-slate-600">{c.wording}</p>
      </div>
    </section>
  );
}

export default function ResultPanel({ r, stale, conformal }: { r: Assessment; stale: boolean; conformal?: ConformalResult | { unavailable: string } | null }) {
  const [tech, setTech] = useState(false);
  const st = STATES[r.reliability_state];
  const Icon = st.icon;
  const f = r.features;
  return (
    <div className={`space-y-5 transition-opacity duration-300 ${stale ? "opacity-60" : ""}`}>
      {stale && <Badge tone="amber" dot>Inputs changed — run the assessment again</Badge>}

      {conformal && <ConformalCard c={conformal} />}

      <section className="card overflow-hidden" aria-label="Reliability result">
        <div className={`h-1.5 bg-gradient-to-r ${st.bar}`} />
        <div className="p-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <Metric label="Observed SpO₂" value={<>{r.spo2}<span className="text-xl text-slate-400">%</span></>} big />
            <div className="rounded-2xl bg-slate-50 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Rule-based reliability</div>
              <div className={`mt-1 flex items-center gap-2 text-4xl font-bold ${st.text}`}>
                <Icon size={32} /> {r.reliability_state}
              </div>
              <div className={`mt-1 text-sm font-bold ${st.text}`}>{r.status}</div>
            </div>
            <Metric label={<Term label="Perfusion" tip="PI = (AC/DC of infrared signal) × 100. Thresholds are configurable and not clinically validated." />}
                    value={`${r.pi}%`} sub={`${r.perfusion_state} PERFUSION`} />
            <Metric label={<Term label="Objective pigmentation" tip="ITA is an objective colorimetric descriptor of pigmentation. It is not race." />}
                    value={r.pigmentation_group.toUpperCase()} sub={`ITA ${r.ita}°`} />
          </div>
          <div className="mt-4 flex items-start gap-2 rounded-xl bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
            <Info size={14} className="mt-0.5 shrink-0" />
            <span><strong>Uncertainty range: not available.</strong> {r.uncertainty_note} Reliability assessment only — not a diagnosis.</span>
          </div>
        </div>
      </section>

      <section className="card p-6">
        <h3 className="mb-3 font-bold text-navy-900">Reliability scale</h3>
        <Scale current={r.reliability_state} />
      </section>

      <section className="card p-6">
        <h3 className="font-bold text-navy-900">Why this reliability state?</h3>
        <ul className="mt-3 space-y-3">
          {r.reasons.map((x) => (
            <li key={x.code} className="flex gap-3 text-sm">
              <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${SEV[x.severity]}`} />
              <span><strong className="text-navy-900">{x.title}.</strong> <span className="text-slate-600">{x.text}</span></span>
            </li>
          ))}
        </ul>
        {r.points !== null && <p className="mt-3 text-xs text-slate-500">Degradation points: {r.points} (configured rule weights; not learned).</p>}
      </section>

      <section className="card p-6">
        <h3 className="mb-3 font-bold text-navy-900">Input summary</h3>
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {[
            ["SpO₂", `${r.spo2}%`],
            [<Term key="pi" label="PI" tip="Perfusion index: strength of the pulsatile PPG signal." />, `${r.pi}% (${r.perfusion_state})${r.pi_source !== "manual" ? ` · ${r.pi_source === "ppg" ? "PPG-derived" : "AC/DC"}` : ""}`],
            [<Term key="ita" label="ITA" tip="ITA is an objective colorimetric descriptor of pigmentation." />, `${r.ita}°${r.ita_source === "pigmentation_module" ? " (pigmentation module)" : ""}`],
            ["Objective pigmentation", r.pigmentation_group.toUpperCase()],
            ["SQI / signal quality", r.sqi != null ? `${r.signal_quality} (${r.sqi.toFixed(0)})` : r.signal_quality],
            ["Signal source", r.signal_source === "signal_module" ? "Sensor / recording" : "Manual"],
            ["Motion", r.motion],
            ["Device", r.device],
          ].map(([k, v], i) => (
            <div key={i} className="rounded-xl bg-slate-50 px-3 py-2">
              <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{k}</dt>
              <dd className="mt-0.5 font-semibold text-navy-900">{v}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 flex items-start gap-2 text-xs text-slate-500">
          <Info size={14} className="mt-0.5 shrink-0" />
          Perfusion and pigmentation thresholds are configurable settings, not clinically validated. The device is recorded but does not change the rules.
        </p>
      </section>

      <section className="card p-6">
        <button onClick={() => setTech((t) => !t)} aria-expanded={tech} className="flex w-full items-center justify-between text-left font-bold text-navy-900">
          Technical features
          <ChevronDown size={18} className={`transition-transform ${tech ? "rotate-180" : ""}`} />
        </button>
        {tech && (
          <table className="mt-4 w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {[["d = 100 − SpO₂", f.d], ["log(PI)", f.log_pi], ["ITA × d", f.ita_x_d], ["log(PI) × d", f.log_pi_x_d], ["ITA × log(PI)", f.ita_x_log_pi]].map(([k, v]) => (
                <tr key={k as string}>
                  <td className="py-2 text-slate-600">{k}</td>
                  <td className="py-2 text-right font-mono font-semibold text-navy-900">{(v as number).toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card p-6">
        <h3 className="mb-3 font-bold text-navy-900">Pipeline</h3>
        <Pipeline />
        <p className="mt-3 text-xs text-slate-500">
          Conformal calibration (CQR, ITA × PI Mondrian) is not part of this assessment until a real dataset has been loaded and calibrated.
        </p>
      </section>
    </div>
  );
}
