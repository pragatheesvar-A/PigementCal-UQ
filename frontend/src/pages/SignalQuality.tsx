import { useMemo, useRef, useState, type ReactNode } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip as ChartTip, XAxis, YAxis } from "recharts";
import { CircleSlash, Loader2, TriangleAlert, Upload } from "lucide-react";
import { Badge, Term } from "../components/ui";
import { ValidationFailed, type FieldError } from "../lib/reliabilityApi";
import {
  analyzeSignal, parsePpgCsv,
  type Motion, type Quality, type SignalAnalysis, type SignalSummary,
} from "../lib/signalApi";

interface Source { ppg: (number | null)[]; fs: number | null; label: string }
type View = "raw" | "filtered" | "both";

const Q_STYLE: Record<Quality, { text: string; chip: string }> = {
  GOOD: { text: "text-emerald-600", chip: "bg-emerald-500" },
  MODERATE: { text: "text-amber-600", chip: "bg-amber-500" },
  POOR: { text: "text-rose-600", chip: "bg-rose-500" },
};
const SEV: Record<string, string> = { info: "bg-emerald-500", warning: "bg-amber-500", critical: "bg-rose-500" };
const HINT_TEXT: Record<string, string> = { GREEN: "text-emerald-600", AMBER: "text-amber-600", ABSTAIN: "text-slate-600" };

function Metric({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: string }) {
  return (
    <div className="card p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-bold text-navy-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="inline-grid grid-flow-col auto-cols-fr gap-1 rounded-xl bg-slate-100 p-1">
      {options.map((o) => (
        <button key={o.id} type="button" aria-pressed={value === o.id} onClick={() => onChange(o.id)}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-all ${value === o.id ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Downsample for display only (analysis always uses every sample); peaks are always kept. */
function chartRows(r: SignalAnalysis, view: View) {
  const fs = r.sampling_rate;
  const n = r.raw_ppg.length;
  const mean = r.raw_ppg.reduce((a, b) => a + b, 0) / n;
  const peaks = new Set(r.peaks);
  const k = Math.max(1, Math.ceil(n / 2500));
  const rows: { t: number; raw?: number; filtered?: number; peak?: number | null }[] = [];
  for (let i = 0; i < n; i += 1) {
    if (i % k !== 0 && !peaks.has(i)) continue;
    const row: { t: number; raw?: number; filtered?: number; peak?: number | null } = { t: +(i / fs).toFixed(3) };
    if (view !== "filtered") row.raw = view === "both" ? r.raw_ppg[i] - mean : r.raw_ppg[i];
    if (view !== "raw") row.filtered = r.filtered_ppg[i];
    row.peak = peaks.has(i) ? (view === "raw" ? row.raw! : row.filtered!) : null;
    rows.push(row);
  }
  return rows;
}

function PpgChart({ r, view }: { r: SignalAnalysis; view: View }) {
  const rows = useMemo(() => chartRows(r, view), [r, view]);
  return (
    <div className="h-80 w-full" role="img" aria-label="PPG waveform chart with detected pulse peaks">
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(v) => `${v}s`} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} width={52} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(1)} />
          <ChartTip formatter={(v, name) => [Number(v).toFixed(3), String(name)]} labelFormatter={(l) => `t = ${l}s`} />
          {view !== "filtered" && <Line dataKey="raw" name={view === "both" ? "Raw (mean removed)" : "Raw"} stroke="#94a3b8" strokeWidth={1.4} dot={false} isAnimationActive={false} />}
          {view !== "raw" && <Line dataKey="filtered" name="Filtered" stroke="#4f46e5" strokeWidth={2} dot={false} isAnimationActive={false} />}
          <Line dataKey="peak" name="Detected peak" stroke="none" dot={{ r: 4, fill: "#7c3aed", stroke: "#fff", strokeWidth: 1.5 }}
                activeDot={false} isAnimationActive={false} connectNulls={false} legendType="none" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function SqiBar({ r }: { r: SignalAnalysis }) {
  const { sqi_good_min: g, sqi_moderate_min: m } = r.thresholds;
  return (
    <div>
      <div className="relative h-3 rounded-full bg-gradient-to-r from-rose-300 via-amber-300 to-emerald-400">
        {[m, g].map((t) => <span key={t} className="absolute inset-y-0 w-px bg-white/90" style={{ left: `${t}%` }} />)}
        <span className="absolute -top-1.5 h-6 w-1.5 -translate-x-1/2 rounded bg-navy-900 transition-all duration-300" style={{ left: `${r.sqi}%` }} />
      </div>
      <div className="relative mt-1 h-4 text-[11px] text-slate-500">
        <span className="absolute left-0">0</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${m}%` }}>{m}</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${g}%` }}>{g}</span>
        <span className="absolute right-0">100</span>
      </div>
    </div>
  );
}

const PIPE = ["Raw PPG", "Invalid-value handling", "Band-pass filter", "Filtered PPG", "Signal statistics", "SQI + motion", "Signal-quality state", "Reliability impact"];

export default function SignalQuality({ onSummary, embedded = false }: { onSummary: (s: SignalSummary) => void; embedded?: boolean }) {
  const [source, setSource] = useState<Source | null>(null);
  const [motion, setMotion] = useState<"AUTO" | Motion>("AUTO");
  const [view, setView] = useState<View>("both");
  const [fsText, setFsText] = useState("");   // must be entered: it is never guessed
  const [result, setResult] = useState<SignalAnalysis | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [general, setGeneral] = useState("");
  const [loading, setLoading] = useState(false);
  const [csvNote, setCsvNote] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  async function analyze(src: Source, m: "AUTO" | Motion) {
    const id = ++seq.current;
    setLoading(true); setErrors([]); setGeneral("");
    try {
      const r = await analyzeSignal(src.ppg, src.fs, m === "AUTO" ? null : m);
      if (id !== seq.current) return;
      setResult(r);
      onSummary({ signal_quality: r.signal_quality, motion_state: r.motion_state, sqi: r.sqi, motion_score: r.motion_score, source: src.label,
        pi_estimate: r.pi_estimate, perfusion_state: r.perfusion_state, ac_ir: r.ac_ir, dc_ir: r.dc_ir,
        spo2_estimate: null, device: "Recorded file", live: false });
    } catch (e) {
      if (id !== seq.current) return;
      setResult(null);
      if (e instanceof ValidationFailed) setErrors(e.errors); else setGeneral((e as Error).message);
    } finally { if (id === seq.current) setLoading(false); }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setCsvNote("");
    try {
      const parsed = parsePpgCsv(await file.text());
      const bad = parsed.ppg.filter((v) => v === null).length;
      setCsvNote(`Read ${parsed.rows} rows from "${parsed.column}"${bad ? `; ${bad} non-numeric cell(s) will be reported and interpolated` : ""}.`);
      const fsNum = fsText.trim() === "" || Number.isNaN(Number(fsText)) ? null : Number(fsText);
      const src = { ppg: parsed.ppg, fs: fsNum, label: `Upload: ${file.name}` };
      setSource(src);
      await analyze(src, motion);
    } catch (e) {
      setResult(null); setErrors([]); setGeneral((e as Error).message);
    }
  }

  function reanalyzeUpload() {
    if (!source) return;
    const fsNum = fsText.trim() === "" || Number.isNaN(Number(fsText)) ? null : Number(fsText);
    const src = { ...source, fs: fsNum };
    setSource(src);
    analyze(src, motion);
  }

  function changeMotion(m: "AUTO" | Motion) {
    setMotion(m);
    if (source) analyze(source, m);
  }

  const abstain = result && (result.signal_quality === "POOR" || result.motion_state === "HIGH");

  return (
    <div className="space-y-6">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          <Badge tone="amber" dot>Default SQI thresholds</Badge>
        </div>
        {embedded ? <h2 className="text-xl font-bold text-navy-900">Recorded PPG analysis</h2> : <h1 className="text-3xl font-extrabold tracking-tight text-navy-900 sm:text-4xl">Recorded PPG analysis</h1>}
        <p className="mt-2 max-w-2xl text-slate-600">
          Evaluate whether the pulse signal contains enough usable information for a reliable assessment.
        </p>
      </header>

      <section className="card space-y-4 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-bold text-navy-900">Recorded file</h2>
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-500">
            <Term label="Motion" tip="A recorded PPG file has no accelerometer here: motion is estimated from sudden amplitude bursts in the PPG, or set manually. Live sensors use their accelerometer." />
            <Seg label="Motion" value={motion} onChange={changeMotion}
                 options={[{ id: "AUTO", label: "Auto" }, { id: "LOW", label: "Low" }, { id: "MEDIUM", label: "Medium" }, { id: "HIGH", label: "High" }]} />
          </div>
        </div>

          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-4">
              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">Sampling rate (Hz)</span>
                <input value={fsText} onChange={(e) => setFsText(e.target.value)} inputMode="decimal"
                       className={`w-32 rounded-xl border bg-white px-3 py-2 text-sm font-medium outline-none focus:ring-2 ${errors.some((e) => e.field === "sampling_rate") ? "border-rose-300 focus:ring-rose-200" : "border-slate-200 focus:border-indigo-400 focus:ring-indigo-100"}`} />
              </label>
              <input ref={fileRef} type="file" accept=".csv,.txt,text/csv" className="hidden" onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
              <button onClick={() => fileRef.current?.click()}
                      className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:border-indigo-300 hover:text-indigo-700">
                <Upload size={16} /> Choose CSV file
              </button>
              {source?.label.startsWith("Upload") && (
                <button onClick={reanalyzeUpload} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:brightness-110">Re-analyze</button>
              )}
            </div>
            <p className="text-xs text-slate-500">
              One numeric PPG column (header optional; a column named ppg / ir / signal is preferred; a leading time column is skipped).
              Enter the sampling rate of your recording. Non-numeric cells are counted and interpolated, never silently dropped.
            </p>
            {csvNote && <p className="text-xs font-semibold text-indigo-700">{csvNote}</p>}
          </div>
      </section>

      <div aria-live="polite" className="space-y-6">
        {!result && !loading && !general && errors.length === 0 && (
          <div className="card grid place-items-center px-6 py-16 text-center text-sm text-slate-500">
            No recording analyzed yet. Choose a CSV file with a PPG column and enter its sampling rate. Nothing is simulated.
            For a live sensor use the Live Monitor.
          </div>
        )}
        {loading && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" /> Analyzing signal…</div>}
        {general && (
          <div className="card flex gap-3 border-rose-200 p-5 text-sm text-rose-800"><TriangleAlert size={18} className="shrink-0" /> {general}</div>
        )}
        {errors.length > 0 && (
          <div className="card border-rose-200 p-6">
            <h3 className="flex items-center gap-2 font-bold text-rose-700"><TriangleAlert size={18} /> Signal cannot be analyzed</h3>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-rose-800">{errors.map((e) => <li key={e.field + e.code}>{e.message}</li>)}</ul>
          </div>
        )}

        {result && (
          <>
            {abstain && (
              <div className="card flex gap-4 border-slate-300 bg-slate-50 p-6" role="alert">
                <CircleSlash size={28} className="mt-0.5 shrink-0 text-slate-600" />
                <div>
                  <div className="text-xl font-extrabold text-slate-700">ABSTAIN — REACQUIRE SIGNAL</div>
                  <p className="mt-1 text-sm text-slate-600">
                    Signal quality is insufficient for a reliable assessment. Consider reacquiring the signal.
                    No confidence is manufactured from this signal; the Live Reliability Check will abstain.
                  </p>
                </div>
              </div>
            )}

            <section className="card p-6">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-bold text-navy-900">Raw vs filtered PPG</h2>
                  <p className="text-xs text-slate-500">{source?.label} · band-pass 0.5–5 Hz (zero-phase Butterworth)</p>
                </div>
                <Seg label="Waveform view" value={view} onChange={setView}
                     options={[{ id: "raw", label: "Raw" }, { id: "filtered", label: "Filtered" }, { id: "both", label: "Both" }]} />
              </div>
              <PpgChart r={result} view={view} />
              <p className="mt-2 text-xs text-slate-500">
                {view === "both" && "Raw is shown with its mean removed so both traces share one axis. "}
                Purple dots: detected pulse peaks (signal-processing estimate). Large charts are thinned for display only.
              </p>
            </section>

            <section className="grid gap-4 lg:grid-cols-2">
              <div className="card p-6">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <Term label="Signal quality index" tip="SQI combines pulse-shape skewness, high-frequency noise, beat-to-beat amplitude variability and pulse regularity into a 0–100 score." />
                    </div>
                    <div className="mt-1 flex items-baseline gap-3">
                      <span className="text-5xl font-extrabold text-navy-900">{result.sqi.toFixed(0)}</span>
                      <span className={`text-2xl font-bold ${Q_STYLE[result.signal_quality].text}`}>{result.signal_quality}</span>
                    </div>
                  </div>
                </div>
                <div className="mt-5"><SqiBar r={result} /></div>
                <dl className="mt-5 space-y-2.5">
                  {([["skewness", "Pulse shape (skewness)"], ["noise", "Low high-frequency noise"], ["amplitude", "Amplitude consistency"], ["regularity", "Pulse regularity"]] as const).map(([k, name]) => (
                    <div key={k}>
                      <div className="flex justify-between text-xs"><dt className="text-slate-600">{name}</dt><dd className="font-semibold text-navy-900">{result.sqi_components[k].toFixed(0)}</dd></div>
                      <div className="mt-1 h-1.5 rounded-full bg-slate-100"><div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all duration-300" style={{ width: `${result.sqi_components[k]}%` }} /></div>
                    </div>
                  ))}
                </dl>
                <p className="mt-4 text-[11px] font-semibold text-amber-800">{result.thresholds.label}</p>
              </div>

              <div className="space-y-4">
                <div className="card p-6">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Motion</div>
                  <div className="mt-1 flex items-baseline gap-3">
                    <span className="text-3xl font-bold text-navy-900">{result.motion_score.toFixed(0)}</span>
                    <span className={`text-xl font-bold ${result.motion_state === "LOW" ? "text-emerald-600" : result.motion_state === "MEDIUM" ? "text-amber-600" : "text-rose-600"}`}>{result.motion_state}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    Motion score is estimated from amplitude bursts (no accelerometer). Status source: {result.motion_source}
                    {result.motion_source === "manual" && ` (estimate alone: ${result.estimated_motion_state})`}.
                  </p>
                </div>
                <div className="card p-6">
                  <h3 className="font-bold text-navy-900">Why is the signal {result.signal_quality === "GOOD" ? "good" : result.signal_quality === "MODERATE" ? "only moderate" : "poor"}?</h3>
                  <ul className="mt-3 space-y-2.5">
                    {result.reasons.map((x, i) => (
                      <li key={i} className="flex gap-3 text-sm text-slate-600"><span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${SEV[x.severity]}`} />{x.text}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>

            <section aria-label="Signal metrics" className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <Metric label="Sampling rate" value={`${result.metrics.sampling_rate_hz} Hz`} />
              <Metric label="Samples" value={result.metrics.n_samples} sub={`${result.metrics.invalid_samples} invalid (interpolated)`} />
              <Metric label="Duration" value={`${result.metrics.duration_s} s`} />
              <Metric label="Amplitude range" value={result.metrics.amplitude_range.toFixed(2)} sub={`filtered: ${result.metrics.filtered_amplitude_range.toFixed(2)}`} />
              <Metric label="Mean" value={result.metrics.mean.toFixed(2)} />
              <Metric label="Std. deviation" value={result.metrics.std.toFixed(3)} />
              <Metric label="Detected pulse peaks" value={result.metrics.n_peaks}
                      sub={result.pulse_rate_estimate !== null ? undefined : "estimates withheld (poor/insufficient signal)"} />
              <Metric label="Pulse-rate estimate" value={result.pulse_rate_estimate !== null ? `${result.pulse_rate_estimate} /min` : "—"}
                      sub="Signal-processing estimate — not a clinical heart-rate measurement." />
              <Metric label={<Term label="PI estimate" tip="Rough single-channel estimate of AC/DC × 100 from this recording (band-passed pulsatile range over the mean). Also offered to the Reliability Check." />}
                      value={result.pi_estimate !== null ? `${result.pi_estimate}%` : "—"} sub="Illustrative, uncalibrated" />
              <Metric label="SQI" value={result.sqi.toFixed(1)} sub={result.signal_quality} />
              <Metric label="Motion status" value={result.motion_state} sub={`score ${result.motion_score.toFixed(0)}`} />
            </section>

            <section className="card p-6">
              <h3 className="font-bold text-navy-900">Impact on the reliability assessment</h3>
              <p className={`mt-2 text-lg font-bold ${HINT_TEXT[result.reliability_impact.state_hint]}`}>
                {result.reliability_impact.state_hint === "ABSTAIN" ? "→ ABSTAIN" : result.reliability_impact.state_hint === "AMBER" ? "→ AMBER or worse" : "→ GREEN possible"}
              </p>
              <p className="mt-1 text-sm text-slate-600">{result.reliability_impact.text}</p>
              <p className="mt-3 text-sm text-slate-600">
                This result ({result.signal_quality}, motion {result.motion_state}, SQI {result.sqi.toFixed(0)}) is now used by the{" "}
                <a href="#reliability" className="font-semibold text-indigo-600 underline">Live Reliability Check</a>.
              </p>
            </section>

            <section className="card p-6">
              <h3 className="mb-3 font-bold text-navy-900">Processing pipeline</h3>
              <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-xs font-medium">
                {PIPE.map((s, i) => (
                  <li key={s} className="flex items-center gap-1">
                    <span className="rounded-lg bg-indigo-50 px-2.5 py-1.5 text-indigo-700">{s}</span>
                    {i < PIPE.length - 1 && <span aria-hidden className="text-slate-300">→</span>}
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
