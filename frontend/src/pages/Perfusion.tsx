import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowDown, Info, Loader2, TriangleAlert } from "lucide-react";
import { Badge, Term } from "../components/ui";
import { ValidationFailed, type FieldError } from "../lib/reliabilityApi";
import {
  calcAcDc, calcDirect, cell, fetchMatrix,
  type Matrix, type PerfusionResult, type PerfusionSummary,
} from "../lib/perfusionApi";
import type { PigmentSummary } from "../lib/pigmentApi";
import type { SignalSummary } from "../lib/signalApi";

type Mode = "direct" | "acdc" | "ppg";
const SOURCE_LABEL = { manual: "Manual input", ac_dc: "Manual AC/DC input", ppg: "PPG-derived" } as const;
const STATE_STYLE = {
  LOW: { text: "text-amber-600", chip: "bg-amber-100 text-amber-900" },
  NORMAL: { text: "text-emerald-600", chip: "bg-emerald-100 text-emerald-900" },
} as const;

/** PI gauge on a log scale (PI spans orders of magnitude). Zone limits come from the backend configuration. */
function PiGauge({ r }: { r: PerfusionResult }) {
  const MIN = 0.1, MAX = 10;
  const { pi_very_low_below: vl, pi_low_below: lo } = r.thresholds;
  const pos = (v: number) => `${((Math.log10(Math.min(MAX, Math.max(MIN, v))) - Math.log10(MIN)) / (Math.log10(MAX) - Math.log10(MIN))) * 100}%`;
  const w = (a: number, b: number) => `calc(${pos(b)} - ${pos(a)})`;
  const off = r.pi < MIN || r.pi > MAX;
  const st = STATE_STYLE[r.perfusion_state];
  return (
    <div role="img" aria-label={`Perfusion index ${r.pi} percent, ${r.perfusion_state} perfusion`}>
      <div className="relative h-5 overflow-hidden rounded-full bg-slate-100">
        <div className="absolute inset-y-0 bg-orange-300" style={{ left: 0, width: w(MIN, vl) }} />
        <div className="absolute inset-y-0 bg-amber-200" style={{ left: pos(vl), width: w(vl, lo) }} />
        <div className="absolute inset-y-0 bg-emerald-200" style={{ left: pos(lo), width: w(lo, MAX) }} />
      </div>
      <div className="relative -mt-7 h-9">
        <span className={`absolute -top-0.5 h-8 w-1.5 -translate-x-1/2 rounded bg-white shadow ring-2 transition-all duration-500 ${r.perfusion_state === "LOW" ? "ring-amber-600" : "ring-emerald-600"}`}
              style={{ left: pos(r.pi) }} />
      </div>
      <div className="relative mt-1 h-9 text-[11px] text-slate-500">
        {[0.1, 0.3, 1, 3, 10].map((t) => <span key={t} className="absolute -translate-x-1/2" style={{ left: pos(t) }}>{t}%</span>)}
        <span className="absolute top-4 -translate-x-1/2 font-semibold" style={{ left: `${(parseFloat(pos((MIN * vl) ** 0.5)))}%` }}>VERY LOW</span>
        <span className="absolute top-4 -translate-x-1/2 font-semibold" style={{ left: `${(parseFloat(pos((vl * lo) ** 0.5)))}%` }}>LOW</span>
        <span className="absolute top-4 -translate-x-1/2 font-semibold" style={{ left: `${(parseFloat(pos((lo * MAX) ** 0.5)))}%` }}>NORMAL</span>
      </div>
      <p className={`text-[11px] ${off ? "text-amber-700" : "text-slate-400"}`}>
        {off ? `Value is beyond the displayed range (${MIN}%–${MAX}%); the marker is pinned to the edge. ` : "Logarithmic scale. "}
        <span className={st.text}>{r.thresholds.label}</span>
      </p>
    </div>
  );
}

function Tile({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: string }) {
  return (
    <div className="rounded-2xl bg-slate-50 p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-bold text-navy-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

const fld = (bad: boolean) =>
  `w-full rounded-xl border bg-white px-3 py-2.5 text-sm font-medium text-navy-900 outline-none focus:ring-2 ${bad ? "border-rose-300 focus:ring-rose-200" : "border-slate-200 focus:border-indigo-400 focus:ring-indigo-100"}`;

export default function Perfusion({ signal, pigment, onSummary, active, embedded = false }: {
  signal: SignalSummary | null; pigment: PigmentSummary | null; onSummary: (s: PerfusionSummary | null) => void; active: boolean; embedded?: boolean;
}) {
  const ppgAvailable = signal !== null && signal.pi_estimate !== null;
  const [mode, setMode] = useState<Mode>(ppgAvailable ? "ppg" : "direct");
  const [directText, setDirectText] = useState("");
  const [acText, setAcText] = useState("");
  const [dcText, setDcText] = useState("");
  const [result, setResult] = useState<PerfusionResult | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [general, setGeneral] = useState("");
  const [ppgNote, setPpgNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [sel, setSel] = useState<{ ita: string; pi: string } | null>(null);
  const seq = useRef(0);

  async function run(m: Mode, d = directText, ac = acText, dc = dcText) {
    const id = ++seq.current;
    setLoading(true); setErrors([]); setGeneral(""); setPpgNote("");
    try {
      let r: PerfusionResult | null = null;
      if (m === "direct") r = await calcDirect(cell(d));
      else if (m === "acdc") r = await calcAcDc(cell(ac), cell(dc));
      else if (signal && signal.pi_estimate !== null) r = await calcAcDc(signal.ac_ir, signal.dc_ir, "ppg");
      else setPpgNote(signal ? `PPG-derived PI is unavailable: the analyzed signal is ${signal.signal_quality} (estimates are withheld for poor signals). Use manual input or reacquire the signal.`
                             : "No PPG signal has been analyzed yet. Analyze one in the Recorded PPG analysis section of Reliability Check, or use manual input.");
      if (id !== seq.current) return;
      setResult(r);
      onSummary(r && r.usable_for_reliability
        ? { pi: r.pi, state: r.perfusion_state, source: r.pi_source, ac_ir: r.ac_ir, dc_ir: r.dc_ir } : null);
    } catch (e) {
      if (id !== seq.current) return;
      setResult(null); onSummary(null);
      if (e instanceof ValidationFailed) setErrors(e.errors); else setGeneral((e as Error).message);
    } finally { if (id === seq.current) setLoading(false); }
  }

  useEffect(() => {
    fetchMatrix().then(setMatrix).catch(() => setMatrix(null));
  }, []);
  // Initial calculation, and re-derive whenever the signal changes while this page is open in PPG mode.
  useEffect(() => { if (active && mode === "ppg") run(mode); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [signal, active]);

  function pickMode(m: Mode) { setMode(m); run(m); }
  const err = (f: string) => errors.find((e) => e.field === f)?.message;

  const curCell = result && pigment ? { ita: pigment.group, pi: result.perfusion_state === "LOW" ? "Low" : "Normal" } : null;
  const selInfo = sel && matrix ? {
    ita: matrix.ita_groups.find((g) => g.id === sel.ita)!, pi: matrix.pi_groups.find((g) => g.id === sel.pi)!,
    current: curCell !== null && curCell.ita === sel.ita && curCell.pi === sel.pi,
  } : null;
  const st = result ? STATE_STYLE[result.perfusion_state] : null;

  return (
    <div className="space-y-6">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          <Badge tone="amber" dot>Configured PI thresholds</Badge>
        </div>
        {embedded ? <h2 className="text-xl font-bold text-navy-900">Perfusion</h2> : <h1 className="text-3xl font-extrabold tracking-tight text-navy-900 sm:text-4xl">Perfusion</h1>}
        <p className="mt-2 max-w-2xl text-slate-600">
          Evaluate whether the observed pulse signal contains adequate perfusion information for reliability assessment.
        </p>
      </header>

      <div className="grid items-start gap-6 xl:grid-cols-[400px_1fr]">
        <div className="card space-y-4 p-6 xl:sticky xl:top-24">
          <div role="group" aria-label="PI input mode" className="grid grid-cols-3 gap-1 rounded-xl bg-slate-100 p-1">
            {([["direct", "Direct PI"], ["acdc", "AC / DC"], ["ppg", "From PPG"]] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={mode === id} onClick={() => pickMode(id)}
                      className={`rounded-lg px-2 py-1.5 text-xs font-bold ${mode === id ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>{label}</button>
            ))}
          </div>

          {mode === "direct" && (
            <form className="space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); run("direct"); }}>
              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <Term label="Perfusion Index (%)" tip="Perfusion Index represents the pulsatile component relative to the baseline component of the infrared PPG signal." />
                </span>
                <input className={fld(!!err("pi"))} inputMode="decimal" value={directText} onChange={(e) => { setDirectText(e.target.value); }} aria-label="PI percent" />
                {err("pi") && <span role="alert" className="mt-1.5 block text-xs font-semibold text-rose-600">{err("pi")}</span>}
              </label>
              <Submit loading={loading} />
            </form>
          )}
          {mode === "acdc" && (
            <form className="space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); run("acdc"); }}>
              {([["ac_ir", "AC_IR (pulsatile)", acText, setAcText], ["dc_ir", "DC_IR (baseline)", dcText, setDcText]] as const).map(([k, label, val, set]) => (
                <label key={k} className="block">
                  <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
                  <input className={fld(!!err(k))} inputMode="decimal" value={val} onChange={(e) => { set(e.target.value); }} aria-label={label} />
                  {err(k) && <span role="alert" className="mt-1.5 block text-xs font-semibold text-rose-600">{err(k)}</span>}
                </label>
              ))}
              <p className="text-xs text-slate-500">PI = (AC_IR / DC_IR) × 100. Any consistent unit works; only the ratio matters.</p>
              <Submit loading={loading} />
            </form>
          )}
          {mode === "ppg" && (
            <div className="space-y-2 text-sm text-slate-600">
              {ppgAvailable ? (
                <p>Using AC and DC derived from the signal analyzed on the <strong>Recorded PPG analysis</strong> section above page
                  ({signal!.source}). No value is typed in or invented.</p>
              ) : (
                <p>{ppgNote || "No PPG-derived PI is available."} Analyse a recording in the Recorded PPG analysis section above.</p>
              )}
              <p className="text-xs text-slate-500">AC = 5th–95th percentile range of the band-passed PPG; DC = mean of the cleaned raw PPG. A rough single-channel estimate, not a calibrated IR measurement.</p>
            </div>
          )}
          <p className="text-[11px] leading-relaxed text-slate-400">Not a diagnostic device — not for medical diagnosis.</p>
        </div>

        <div aria-live="polite" className="min-w-0 space-y-6">
          {loading && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" /> Calculating…</div>}
          {general && <div className="card flex gap-3 border-rose-200 p-5 text-sm text-rose-800"><TriangleAlert size={18} className="shrink-0" /> {general}</div>}
          {errors.length > 0 && (
            <div className="card border-rose-200 p-6">
              <h3 className="flex items-center gap-2 font-bold text-rose-700"><TriangleAlert size={18} /> PI cannot be calculated</h3>
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-rose-800">{errors.map((e) => <li key={e.field + e.code}>{e.message}</li>)}</ul>
              <p className="mt-3 text-xs text-slate-500">Invalid values are never silently corrected.</p>
            </div>
          )}
          {mode === "ppg" && !ppgAvailable && ppgNote && (
            <div className="card flex gap-3 border-amber-200 p-5 text-sm text-amber-900"><Info size={18} className="shrink-0" /> {ppgNote}</div>
          )}

          {!result && !loading && errors.length === 0 && !general && !ppgNote && (
            <div className="card grid place-items-center px-6 py-16 text-center text-sm text-slate-500">
              No perfusion value yet. Enter a PI (or AC and DC) and calculate, or analyze a PPG signal to derive it.
            </div>
          )}

          {result && st && (
            <>
              <section className="card p-6">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <Term label="Perfusion index" tip="PI = (AC_IR / DC_IR) × 100. It is a signal/perfusion feature, not a diagnostic measurement." />
                    </div>
                    <div className="mt-1 flex items-baseline gap-1">
                      <span className="text-5xl font-extrabold text-navy-900">{result.pi < 10 ? result.pi.toFixed(2) : result.pi.toFixed(1)}</span>
                      <span className="text-lg font-medium text-slate-400">%</span>
                    </div>
                    <div className="mt-1"><Badge tone={result.pi_source === "ppg" ? "indigo" : "slate"}>PI source: {SOURCE_LABEL[result.pi_source]}</Badge></div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Perfusion status</div>
                    <span className={`mt-1 inline-block rounded-xl px-4 py-2 text-xl font-extrabold tracking-wide ${st.chip}`}>{result.perfusion_state}</span>
                    {result.very_low && <div className="mt-1 text-xs font-semibold text-orange-700">very low (below {result.thresholds.pi_very_low_below}%)</div>}
                  </div>
                </div>
                <div className="mt-6"><PiGauge r={result} /></div>
              </section>

              {result.ac_ir !== null && result.dc_ir !== null && (
                <section className="grid grid-cols-2 gap-3" aria-label="AC and DC components">
                  <Tile label="AC component (AC_IR)" value={Number(result.ac_ir.toPrecision(5))} sub="pulsatile" />
                  <Tile label="DC component (DC_IR)" value={Number(result.dc_ir.toPrecision(6))} sub="baseline" />
                </section>
              )}

              {result.warnings.length > 0 && (
                <section className="card border-amber-200 p-5" role="status">
                  <h3 className="flex items-center gap-2 text-sm font-bold text-amber-800"><TriangleAlert size={16} /> Check these</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
                </section>
              )}

              <section className="card p-6">
                <h3 className="font-bold text-navy-900">From perfusion to reliability</h3>
                <ol className="mt-3 space-y-1.5 text-sm">
                  <li className="rounded-lg bg-slate-50 px-3 py-2 font-semibold text-navy-900">PI = {result.pi < 10 ? result.pi.toFixed(2) : result.pi.toFixed(1)}%</li>
                  <li className="flex justify-center text-slate-300"><ArrowDown size={16} /></li>
                  <li className={`rounded-lg bg-slate-50 px-3 py-2 font-bold ${st.text}`}>{result.perfusion_state} PERFUSION</li>
                  <li className="flex justify-center text-slate-300"><ArrowDown size={16} /></li>
                  <li className="rounded-lg bg-slate-50 px-3 py-2 text-slate-700">
                    {result.perfusion_state === "LOW" ? "Lower perfusion may reduce signal strength." : result.impact}
                  </li>
                  {result.perfusion_state === "LOW" && (<>
                    <li className="flex justify-center text-slate-300"><ArrowDown size={16} /></li>
                    <li className="rounded-lg bg-slate-50 px-3 py-2 text-slate-700">Reliability uncertainty may increase.</li>
                  </>)}
                </ol>

                <p className="mt-4 text-xs text-slate-500">The full assessment combines this PI with signal quality, motion and objective pigmentation on the <a href="#reliability" className="font-semibold text-indigo-600 underline">Live Reliability Check</a>.</p>
              </section>
            </>
          )}

          {matrix && (
            <section className="card p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-bold text-navy-900">Objective pigmentation × perfusion</h3>
                <Badge tone="amber">Structural preview only</Badge>
              </div>
              <p className="mt-1 text-sm text-slate-600">The six cells of the planned ITA × PI structure. Select a cell to inspect it.</p>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[360px] border-separate border-spacing-2 text-center text-sm">
                  <thead>
                    <tr><th />{matrix.pi_groups.map((g) => <th key={g.id} className="pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{g.id} PI</th>)}</tr>
                  </thead>
                  <tbody>
                    {matrix.ita_groups.map((a) => (
                      <tr key={a.id}>
                        <th scope="row" className="pr-1 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">{a.id}</th>
                        {matrix.pi_groups.map((b) => {
                          const isCur = curCell?.ita === a.id && curCell?.pi === b.id;
                          const isSel = sel?.ita === a.id && sel?.pi === b.id;
                          return (
                            <td key={b.id}>
                              <button onClick={() => setSel({ ita: a.id, pi: b.id })} aria-pressed={isSel}
                                      aria-label={`${a.id} pigmentation, ${b.id} PI${isCur ? " (current input)" : ""}`}
                                      className={`h-14 w-full rounded-xl border-2 text-2xl transition-all ${isSel ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-white hover:border-indigo-300"} ${isCur ? "text-indigo-600" : "text-slate-300"}`}>
                                ●
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-500"><span className="text-indigo-600">●</span> highlighted dot = current input{curCell ? "" : " (no objective pigmentation value yet — measure it on the Objective Pigmentation page)"}.</p>
              {selInfo && (
                <dl className="mt-4 grid gap-3 rounded-xl bg-slate-50 p-4 text-sm sm:grid-cols-2">
                  <div><dt className="text-[11px] font-semibold uppercase text-slate-500">ITA group</dt><dd className="font-bold text-navy-900">{selInfo.ita.id.toUpperCase()} <span className="font-normal text-slate-500">({selInfo.ita.range})</span></dd></div>
                  <div><dt className="text-[11px] font-semibold uppercase text-slate-500">PI group</dt><dd className="font-bold text-navy-900">{selInfo.pi.id.toUpperCase()} <span className="font-normal text-slate-500">({selInfo.pi.range})</span></dd></div>
                  <div><dt className="text-[11px] font-semibold uppercase text-slate-500">Current input</dt>
                    <dd className="text-slate-700">{pigment ? `ITA ${pigment.ita.toFixed(1)}° (${pigment.group})` : "ITA not provided"} · {result ? `PI ${result.pi}% (${result.perfusion_state === "LOW" ? "Low" : "Normal"})` : "PI not available"}</dd></div>
                  <div><dt className="text-[11px] font-semibold uppercase text-slate-500">Cell status</dt>
                    <dd className="text-slate-700">{selInfo.current ? "Current input falls in this cell." : curCell ? "Not the current cell." : "Current cell unknown (ITA or PI missing)."}<br />
                      <span className="text-xs text-slate-500">Calibration data: none loaded. Coverage not computed.</span></dd></div>
                </dl>
              )}
              <p className="mt-3 text-xs font-semibold text-amber-800">{matrix.status} Calibrated subgroup intervals are on the Models page.</p>
            </section>
          )}

          <section className="card p-6">
            <h3 className="font-bold text-navy-900">Why does perfusion matter?</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              Pulse oximetry depends on detecting pulsatile blood-volume changes in the PPG signal. When perfusion is low, the pulsatile
              signal can become weaker and more susceptible to noise. Low perfusion may reduce signal quality and increase measurement
              uncertainty — it does not, on its own, show that a reading is wrong.
            </p>
          </section>

          <section className="card p-6">
            <h3 className="font-bold text-navy-900">How PI is calculated</h3>
            <p className="my-3 rounded-xl bg-slate-50 px-4 py-3 font-mono text-sm text-navy-900">PI = (AC_IR / DC_IR) × 100</p>
            <ul className="space-y-1.5 text-sm text-slate-600">
              <li>• <strong>AC_IR</strong> — the pulsatile (AC) component of the infrared PPG: the size of the beat-to-beat swing.</li>
              <li>• <strong>DC_IR</strong> — the non-pulsatile (DC) component: the steady baseline level of the infrared PPG.</li>
              <li>• <strong>PI</strong> — their ratio in percent; a unit-free measure of pulsatile signal strength.</li>
              <li>• PI is used here as a <strong>signal/perfusion feature</strong> for the reliability assessment, not as a standalone diagnostic measurement.</li>
              <li>• The Low/Normal limits ({result?.thresholds.pi_low_below ?? 1}% and very-low {result?.thresholds.pi_very_low_below ?? 0.5}%) are configured thresholds — not clinically validated.</li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

function Submit({ loading }: { loading: boolean }) {
  return (
    <button type="submit" disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3 text-sm font-bold tracking-wide text-white shadow-md hover:brightness-110 disabled:opacity-60">
      {loading && <Loader2 size={16} className="animate-spin" />} CALCULATE PI
    </button>
  );
}
