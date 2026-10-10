import { Suspense, lazy, useMemo, useState, type ReactNode } from "react";
import { Loader2, Play, TriangleAlert } from "lucide-react";
import ResultPanel from "../components/reliability/ResultPanel";
import { Badge, Term } from "../components/ui";
import type { SignalSummary } from "../lib/signalApi";
import type { PigmentSummary } from "../lib/pigmentApi";
import type { PerfusionSummary } from "../lib/perfusionApi";
import { VIRTUAL_BANNER, VIRTUAL_DEVICE } from "../lib/virtualSensor";
import { predictConformal, type ConformalResult } from "../lib/conformalApi";
import { DEVICES, predict, ValidationFailed, type Assessment, type FieldError, type Inputs } from "../lib/reliabilityApi";

interface Form { spo2: string; pi: string; ita: string; signal_quality: string; motion: string; device: string; sqi: string; motion_score: string }

// Nothing is pre-filled: a value either comes from a module / sensor or from the person using the page.
const EMPTY: Form = { spo2: "", pi: "", ita: "", signal_quality: "", motion: "", device: "", sqi: "", motion_score: "" };

/** Empty -> null (reported as missing); numeric text -> number; other text is sent as typed so the server explains why it is invalid. */
const toNum = (s: string): number | null => {
  if (s.trim() === "") return null;
  const n = Number(s);
  return Number.isNaN(n) ? (s.trim() as unknown as number) : n;
};

function Field({ label, error, children, hint }: { label: ReactNode; error?: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      {children}
      {error ? <span role="alert" className="mt-1.5 block text-xs font-semibold text-rose-600">{error}</span>
             : hint && <span className="mt-1.5 block text-xs text-slate-400">{hint}</span>}
    </label>
  );
}

const inputCls = (bad: boolean) =>
  `w-full rounded-xl border bg-white px-3 py-2.5 text-sm font-medium text-navy-900 outline-none transition-colors focus:ring-2 read-only:bg-slate-50 ${
    bad ? "border-rose-300 focus:ring-rose-200" : "border-slate-200 focus:border-indigo-400 focus:ring-indigo-100"}`;

function Segmented({ value, options, onChange, locked }: { value: string; options: string[]; onChange: (v: string) => void; locked?: boolean }) {
  return (
    <div className="grid grid-flow-col auto-cols-fr gap-1 rounded-xl bg-slate-100 p-1">
      {options.map((o) => (
        <button key={o} type="button" disabled={locked} onClick={() => onChange(o)} aria-pressed={value === o}
                className={`rounded-lg px-2 py-2 text-xs font-bold transition-all ${
                  value === o ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-800"} ${locked ? "cursor-not-allowed opacity-70" : ""}`}>
          {o}
        </button>
      ))}
    </div>
  );
}

function ModuleBanner({ title, on, onToggle, children, offLabel, onLabel }: { title: string; on: boolean; onToggle: () => void; children: ReactNode; offLabel: string; onLabel: string }) {
  return (
    <div className="rounded-xl bg-indigo-50 px-3 py-2.5 text-xs text-indigo-900">
      <div className="font-bold">{on ? title : "Manual entry"}</div>
      <div className="mt-0.5">{children}</div>
      <button type="button" className="mt-1 font-semibold underline" onClick={onToggle}>{on ? offLabel : onLabel}</button>
    </div>
  );
}

const SignalQuality = lazy(() => import("./SignalQuality"));
const Pigmentation = lazy(() => import("./Pigmentation"));
const Perfusion = lazy(() => import("./Perfusion"));

interface Props {
  signal: SignalSummary | null; pigment: PigmentSummary | null; perfusion: PerfusionSummary | null;
  onSignal: (s: SignalSummary | null) => void; onPigment: (s: PigmentSummary | null) => void; onPerfusion: (s: PerfusionSummary | null) => void;
}

/** The measurement modules that feed this check: recorded PPG, objective ITA and perfusion. Mounted once opened, then kept. */
function MeasurementInputs({ signal, pigment, onSignal, onPigment, onPerfusion }: Omit<Props, "perfusion">) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [seen, setSeen] = useState<Record<string, boolean>>({});
  const section = (id: string, title: string, node: ReactNode) => (
    <details className="card p-4" open={!!open[id]} onToggle={(e) => { const o = (e.currentTarget as HTMLDetailsElement).open; setOpen((v) => ({ ...v, [id]: o })); if (o) setSeen((v) => ({ ...v, [id]: true })); }}>
      <summary className="cursor-pointer text-sm font-bold text-navy-900">{title}</summary>
      <div className="mt-4">{seen[id] && <Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}>{node}</Suspense>}</div>
    </details>
  );
  return (
    <section aria-label="Measurement inputs" className="space-y-3">
      <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Measurement inputs</h2>
      {section("signal", "Recorded PPG analysis (filtering, SQI, PI)", <SignalQuality embedded onSummary={onSignal} />)}
      {section("pigment", "Objective pigmentation (ITA from L*, a*, b*)", <Pigmentation embedded onSummary={onPigment} />)}
      {section("perfusion", "Perfusion index (AC / DC or direct PI)", <Perfusion embedded signal={signal} pigment={pigment} onSummary={onPerfusion} active={!!open.perfusion} />)}
    </section>
  );
}

export default function ReliabilityCheck({ signal, pigment, perfusion, onSignal, onPigment, onPerfusion }: Props) {
  const [form, setForm] = useState<Form>(EMPTY);
  const [result, setResult] = useState<Assessment | null>(null);
  const [conformal, setConformal] = useState<ConformalResult | { unavailable: string } | null>(null);
  const [ranFor, setRanFor] = useState("");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [general, setGeneral] = useState("");
  const [loading, setLoading] = useState(false);
  const [useSignal, setUseSignal] = useState(true);
  const [usePigment, setUsePigment] = useState(true);
  const [usePerfusion, setUsePerfusion] = useState(true);

  const sig = useSignal ? signal : null;
  const pig = usePigment ? pigment : null;
  // PI: an explicit perfusion-module value wins; otherwise the PI estimated from the signal itself.
  const perf = usePerfusion ? perfusion : null;
  const sigPi = sig && sig.pi_estimate !== null ? sig.pi_estimate : null;
  const piFromModule = perf ? { pi: perf.pi, source: perf.source } : sigPi !== null ? { pi: sigPi, source: "ppg" as const } : null;
  const spo2FromSensor = sig && sig.spo2_estimate !== null ? sig.spo2_estimate : null;

  const effective: Form = {
    ...form,
    ...(piFromModule ? { pi: String(Number(piFromModule.pi.toFixed(4))) } : {}),
    ...(spo2FromSensor !== null ? { spo2: String(spo2FromSensor) } : {}),
    ...(sig ? { signal_quality: sig.signal_quality, motion: sig.motion_state, device: sig.device, sqi: String(sig.sqi), motion_score: String(sig.motion_score) } : {}),
    ...(pig ? { ita: String(pig.ita) } : {}),
  };
  const key = JSON.stringify([effective, sig?.sqi ?? null, pig?.ita ?? null, piFromModule?.source ?? null]);
  const stale = result !== null && key !== ranFor;
  const err = useMemo(() => Object.fromEntries(errors.map((e) => [e.field, e.message])), [errors]);

  async function run() {
    setLoading(true); setErrors([]); setGeneral("");
    const body: Inputs = {
      spo2: toNum(effective.spo2), pi: toNum(effective.pi), ita: toNum(effective.ita),
      signal_quality: effective.signal_quality, motion: effective.motion, device: effective.device,
      ...(sig ? { signal_source: "signal_module" as const } : {}),
      ...(effective.sqi.trim() !== "" ? { sqi: toNum(effective.sqi) } : {}),
      ...(pig ? { ita_source: "pigmentation_module" as const } : {}),
      ...(piFromModule ? { pi_source: piFromModule.source } : {}),
    };
    try {
      setResult(await predict(body));
      setRanFor(key);
      try {
        setConformal(await predictConformal({ spo2: body.spo2, pi: body.pi, ita: body.ita, signal_quality: body.signal_quality, motion: body.motion,
                                              device: body.device, sqi: toNum(effective.sqi), motion_score: toNum(effective.motion_score) }));
      } catch (e) {
        setConformal({ unavailable: e instanceof ValidationFailed ? e.errors.map((x) => x.message).join(" ") : "The calibrated assessment could not be computed." });
      }
    } catch (e) {
      setResult(null); setConformal(null);     // never leave a previous result next to an invalid input
      if (e instanceof ValidationFailed) setErrors(e.errors); else setGeneral((e as Error).message);
    } finally { setLoading(false); }
  }

  const set = (k: keyof Form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div className="space-y-6">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          {signal?.live && <Badge tone="green" dot>Live sensor connected</Badge>}
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight text-navy-900 sm:text-4xl">Reliability Check</h1>
        <p className="mt-2 max-w-2xl text-slate-600">
          Evaluate the reliability of a pulse-oximeter reading using pigmentation, perfusion and signal-quality information.
          Values come from the live sensor, a recorded file or the measurement pages whenever those have produced them; anything else you enter yourself.
        </p>
      </header>

      <div className="grid items-start gap-6 xl:grid-cols-[380px_1fr]">
        <form className="card space-y-5 p-6 xl:sticky xl:top-24" onSubmit={(e) => { e.preventDefault(); void run(); }} noValidate>
          <h2 className="font-bold text-navy-900">Input conditions</h2>

          {signal && (
            <ModuleBanner title={signal.live ? "Using the live sensor" : "Using the analyzed recording"} on={useSignal} onToggle={() => setUseSignal((u) => !u)}
                          offLabel="Enter signal values manually" onLabel="Use signal values">
              {signal.source}: <strong>{signal.signal_quality}</strong>, motion <strong>{signal.motion_state}</strong>, SQI {signal.sqi.toFixed(0)}
              {signal.pi_estimate !== null && <>, PI {signal.pi_estimate.toFixed(2)}%</>}
              {signal.spo2_estimate !== null && <>, SpO₂ estimate {signal.spo2_estimate}% (uncalibrated)</>}.
            </ModuleBanner>
          )}

          <Field label="SpO₂ reading to assess (%)" error={err.spo2}
                 hint={spo2FromSensor !== null ? "Uncalibrated estimate from the live red/infrared sensor (read-only)." : "The value your oximeter shows. Supported range 70–100."}>
            <input className={inputCls(!!err.spo2)} inputMode="decimal" value={effective.spo2} readOnly={spo2FromSensor !== null}
                   onChange={(e) => set("spo2")(e.target.value)} aria-label="SpO2" />
          </Field>

          <Field label={<Term label="Perfusion Index (%)" tip="PI = (AC/DC of infrared signal) × 100. Low perfusion may reduce signal strength and increase measurement uncertainty." />}
                 error={err.pi} hint={piFromModule ? `From the ${piFromModule.source === "ppg" ? "PPG signal" : "perfusion module"} (read-only).` : "Must be greater than 0. Below 1.0% is treated as low (configured threshold)."}>
            <input className={inputCls(!!err.pi)} inputMode="decimal" value={effective.pi} readOnly={!!piFromModule}
                   onChange={(e) => set("pi")(e.target.value)} aria-label="PI" />
          </Field>
          {perfusion && (
            <ModuleBanner title="Using the perfusion module" on={usePerfusion} onToggle={() => setUsePerfusion((u) => !u)} offLabel="Do not use it" onLabel="Use perfusion-module value">
              PI <strong>{perfusion.pi}%</strong> → <strong>{perfusion.state} PERFUSION</strong> ({perfusion.source === "ppg" ? "PPG-derived" : perfusion.source === "ac_dc" ? "from AC/DC input" : "manual input"}).
            </ModuleBanner>
          )}

          <Field label={<Term label="ITA (°)" tip="ITA is an objective colorimetric descriptor of pigmentation. It is not race." />}
                 error={err.ita} hint={pig ? "From the objective pigmentation module (read-only)." : "Objective pigmentation measurement (from L*, a*, b*), entered here or on the Pigmentation page."}>
            <input className={inputCls(!!err.ita)} inputMode="decimal" value={effective.ita} readOnly={!!pig}
                   onChange={(e) => set("ita")(e.target.value)} aria-label="ITA" />
          </Field>
          {pigment && (
            <ModuleBanner title="Using the objective pigmentation module" on={usePigment} onToggle={() => setUsePigment((u) => !u)} offLabel="Enter ITA manually" onLabel="Use pigmentation-module value">
              ITA <strong>{pigment.ita.toFixed(1)}°</strong> → <strong>{pigment.group.toUpperCase()}</strong> ({pigment.n > 1 ? `median of ${pigment.n}` : "single measurement"}, {pigment.location}).
            </ModuleBanner>
          )}

          <Field label="Signal quality" error={err.signal_quality}>
            <Segmented locked={!!sig} value={effective.signal_quality} options={["GOOD", "MODERATE", "POOR"]} onChange={set("signal_quality")} />
          </Field>
          <Field label="Motion" error={err.motion}>
            <Segmented locked={!!sig} value={effective.motion} options={["LOW", "MEDIUM", "HIGH"]} onChange={set("motion")} />
          </Field>
          {!sig && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="SQI (0–100)" error={err.sqi} hint="Optional. Used by the calibrated model.">
                <input className={inputCls(!!err.sqi)} inputMode="decimal" value={effective.sqi} onChange={(e) => set("sqi")(e.target.value)} aria-label="SQI" />
              </Field>
              <Field label="Motion score (0–100)" hint="Optional. Used by the calibrated model.">
                <input className={inputCls(false)} inputMode="decimal" value={effective.motion_score} onChange={(e) => set("motion_score")(e.target.value)} aria-label="Motion score" />
              </Field>
            </div>
          )}
          <Field label="Device / source" error={err.device}>
            <select className={inputCls(!!err.device)} value={effective.device} disabled={!!sig} onChange={(e) => set("device")(e.target.value)} aria-label="Device">
              <option value="">Select…</option>
              {DEVICES.map((d) => <option key={d}>{d}</option>)}
            </select>
          </Field>
          {effective.device === VIRTUAL_DEVICE && <p role="note" className="rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">{VIRTUAL_BANNER}</p>}

          <button type="submit" disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3 text-sm font-bold tracking-wide text-white shadow-md transition hover:brightness-110 disabled:opacity-60">
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
            RUN RELIABILITY ASSESSMENT
          </button>
          <p className="text-[11px] leading-relaxed text-slate-400">Not a diagnostic device — not for medical diagnosis.</p>
        </form>

        <div aria-live="polite">
          {general && (
            <div className="card flex gap-3 border-rose-200 p-5 text-sm text-rose-800"><TriangleAlert size={18} className="shrink-0" /> {general}</div>
          )}
          {errors.length > 0 && (
            <div className="card border-rose-200 p-6">
              <h3 className="flex items-center gap-2 font-bold text-rose-700"><TriangleAlert size={18} /> Input cannot be assessed</h3>
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-rose-800">{errors.map((e) => <li key={e.field + e.code}>{e.message}</li>)}</ul>
              <p className="mt-3 text-xs text-slate-500">Invalid or missing values are never silently accepted, filled in or corrected.</p>
            </div>
          )}
          {!result && !general && errors.length === 0 && !loading && (
            <div className="card grid place-items-center px-6 py-24 text-center text-sm text-slate-500">
              Provide the conditions (or connect a sensor on the Live Monitor) and press <strong className="mx-1 text-slate-700">Run reliability assessment</strong>.
            </div>
          )}
          {result && <ResultPanel r={result} stale={stale} conformal={conformal} />}
        </div>
      </div>
      <MeasurementInputs signal={signal} pigment={pigment} onSignal={onSignal} onPigment={onPigment} onPerfusion={onPerfusion} />
    </div>
  );
}
