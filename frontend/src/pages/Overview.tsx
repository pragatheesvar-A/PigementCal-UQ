import type { ReactNode } from "react";
import { ArrowRight, Database, Layers, Palette, Radio } from "lucide-react";
import type { Health } from "../lib/api";
import type { SignalSummary } from "../lib/signalApi";
import type { PigmentSummary } from "../lib/pigmentApi";
import { Badge, Term } from "../components/ui";

const Q_TEXT = { GOOD: "text-emerald-600", MODERATE: "text-amber-600", POOR: "text-rose-600" } as const;

function Card({ icon, title, status, tone, children, href, cta }: {
  icon: ReactNode; title: string; status: string; tone: "green" | "slate" | "amber"; children: ReactNode; href: string; cta: string;
}) {
  return (
    <div className="card flex flex-col p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-bold text-navy-900"><span className="text-indigo-600">{icon}</span>{title}</div>
        <Badge tone={tone} dot>{status}</Badge>
      </div>
      <div className="mt-3 flex-1 text-sm text-slate-600">{children}</div>
      <a href={href} className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-indigo-600 hover:underline">{cta} <ArrowRight size={14} /></a>
    </div>
  );
}

export default function Overview({ health, signal, pigment }: { health: Health | null; signal: SignalSummary | null; pigment: PigmentSummary | null }) {
  return (
    <div className="space-y-8">
      <section className="relative isolate overflow-hidden rounded-3xl bg-gradient-to-br from-navy-900 via-navy-800 to-indigo-900 p-8 text-white shadow-xl shadow-indigo-900/20 sm:p-10">
        <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 -z-10 h-80 w-80 rounded-full bg-violet-500/30 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-32 left-1/3 -z-10 h-72 w-72 rounded-full bg-indigo-400/20 blur-3xl" />
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-300">
          Pigmentation- and perfusion-conditional conformal reliability bounds
        </p>
        <h1 className="mt-3 text-3xl font-extrabold tracking-tight sm:text-5xl">CAN YOU TRUST THIS NUMBER?</h1>
        <p className="mt-3 max-w-2xl text-base text-slate-300 sm:text-lg">
          An uncertainty-aware reliability layer for pulse oximetry. It does not replace the reading — it says how much that reading can be trusted.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <a href="#live" className="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-bold text-navy-900 shadow-lg shadow-black/10 hover:-translate-y-0.5 hover:bg-slate-100">
            <Radio size={16} /> Open the Live Monitor
          </a>
          <a href="#reliability" className="inline-flex items-center gap-2 rounded-xl border border-white/25 bg-white/10 px-5 py-3 text-sm font-bold text-white backdrop-blur hover:bg-white/20">
            Check a reading <ArrowRight size={16} />
          </a>
        </div>
      </section>

      <section aria-labelledby="state" className="space-y-3">
        <h2 id="state" className="text-lg font-bold text-navy-900">Current state</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Card icon={<Radio size={16} />} title="Sensor / signal" status={signal ? (signal.live ? "Live" : "Recording analyzed") : "No signal"} tone={signal ? "green" : "slate"}
                href={signal?.live ? "#live" : "#live"} cta={signal ? "Open Live Monitor" : "Connect a sensor"}>
            {signal ? (
              <ul className="space-y-1">
                <li>Signal quality <strong className={Q_TEXT[signal.signal_quality]}>{signal.signal_quality}</strong> (SQI {signal.sqi.toFixed(0)})</li>
                <li>Motion <strong>{signal.motion_state}</strong></li>
                <li><Term label="PI" tip="Perfusion index = AC/DC × 100 of the infrared signal." /> {signal.pi_estimate !== null ? `${signal.pi_estimate.toFixed(2)}%` : "withheld (poor signal)"}</li>
                {signal.spo2_estimate !== null && <li>SpO₂ estimate {signal.spo2_estimate}% <span className="text-xs text-slate-400">(uncalibrated)</span></li>}
              </ul>
            ) : "Nothing has been measured yet. Stream an ESP32 + MAX30102, use the phone camera, or replay a recording."}
          </Card>
          <Card icon={<Palette size={16} />} title="Objective pigmentation" status={pigment ? pigment.group : "Not measured"} tone={pigment ? "green" : "slate"}
                href="#reliability" cta={pigment ? "Open pigmentation" : "Enter L*, a*, b*"}>
            {pigment ? <>ITA <strong>{pigment.ita.toFixed(1)}°</strong> → <strong>{pigment.group.toUpperCase()}</strong> ({pigment.n > 1 ? `median of ${pigment.n}` : "single measurement"}).</>
                     : "No objective skin-colour measurement yet. ITA is computed from colorimeter L*, a*, b* values — never from race."}
          </Card>
          <Card icon={<Database size={16} />} title="Research dataset" status={health?.dataset.loaded ? "Loaded" : "None"} tone={health?.dataset.loaded ? "green" : "amber"}
                href="#data-collection" cta={health?.dataset.loaded ? "Open data collection" : "Add your data"}>
            {health?.dataset.loaded ? <>{health.dataset.participants} participants, {health.dataset.rows} rows.</>
                                    : "REAL DATA: 0 records. Nothing with arterial SaO₂ ground truth has been collected yet, so no models, calibration or subgroup results exist."}
          </Card>
          <Card icon={<Layers size={16} />} title="Models" status={health?.model.trained ? (health.research_status?.verified_data ? "Trained" : "Trained · not research") : "Not trained"} tone={health?.model.trained ? "green" : "slate"}
                href="#models" cta="Open models">
            {health?.model.trained ? (health.research_status?.verified_data ? "Ridge and LightGBM were trained on the loaded dataset." : "Ridge and LightGBM were fitted on a dataset that is not verified research data (see the status badge). Pipeline test only; not a research result.") : "Models are trained only on a loaded research dataset."}
          </Card>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="card p-6">
          <h3 className="font-bold text-navy-900">What this system does</h3>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            It adds a post-hoc reliability layer to a pulse-oximeter reading. From the live signal it measures signal quality, motion and
            perfusion; from a colorimeter it takes objective pigmentation (ITA); a transparent rule engine then reports a reliability state and
            the reasons — or abstains when the signal is not good enough.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge tone="indigo">Records the device used</Badge><Badge tone="indigo">Live, about 1 s updates</Badge>
            <Badge tone="violet">Objective ITA, not race</Badge><Badge tone="violet">Abstains on poor signal</Badge>
          </div>
        </div>
        <div className="card p-6">
          <h3 className="font-bold text-navy-900">What is and is not available</h3>
          <ul className="mt-3 space-y-2 text-sm text-slate-600">
            <li>• <strong>Available:</strong> live acquisition, signal quality, perfusion index, motion, pulse rate, objective pigmentation, reliability state.</li>
            <li>• <strong>Needs your dataset:</strong> trained models, calibrated uncertainty ranges (conformal), subgroup results.</li>
            <li>• <strong>Always:</strong> the SpO₂ estimate from a raw red/infrared sensor is uncalibrated; this is not a diagnostic device.</li>
          </ul>
        </div>
      </section>
    </div>
  );
}
