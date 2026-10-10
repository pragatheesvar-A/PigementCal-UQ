import { useEffect, useMemo, useState, type ReactNode } from "react";
import { STATUS_TONE, labelForState } from "../lib/status";
import { NotAResultBanner } from "../components/Safety";
import { useResearchStatus } from "../lib/researchContext";
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip as ChartTip, XAxis, YAxis, Legend } from "recharts";
import { Info, Loader2, Play, TriangleAlert } from "lucide-react";
import ConformalPanel from "../components/ConformalPanel";
import { Badge, Term } from "../components/ui";
import { ValidationFailed, type FieldError } from "../lib/reliabilityApi";
import {
  fetchModelMetrics, fetchModelStatus, fetchTestPredictions, predictModel, trainModels,
  type ModelStatus, type PredictionRow, type PredictOut, type SubgroupCell, type TrainResult,
} from "../lib/modelApi";

const f2 = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? "—" : v.toFixed(d));
const cellName = (c: SubgroupCell) => c.group ?? `${c.ita_group} × ${c.pi_group}`;

function Banner({ prov }: { prov: { kind: string; label: string; reason: string } }) {
  const none = prov.kind === "NONE";
  const bad = prov.kind === "MISMATCH" || prov.kind === "UNVERIFIED";
  return (
    <div role="status" className={`card flex gap-3 p-5 ${none ? "border-amber-300 bg-amber-50" : bad ? "border-rose-300 bg-rose-50" : "border-indigo-200"}`}>
      <Info size={20} className={`mt-0.5 shrink-0 ${none ? "text-amber-700" : bad ? "text-rose-700" : "text-indigo-600"}`} />
      <div>
        <div className={`text-lg font-extrabold tracking-wide ${none ? "text-amber-900" : bad ? "text-rose-900" : "text-indigo-900"}`}>{prov.label}</div>
        <p className="mt-1 text-sm text-slate-700">{none ? <>Research results appear only when real collected data has been uploaded and built. <a href="#data-collection" className="font-semibold text-indigo-600 underline">Open Data Collection.</a></> : prov.reason}</p>
      </div>
    </div>
  );
}

function Table({ head, children, caption }: { head: string[]; children: ReactNode; caption?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[460px] text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500">
          <tr>{head.map((h, i) => <th key={h} className={`pb-2 ${i > 0 ? "text-right" : ""}`}>{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}

function SubgroupTable({ title, cells, note }: { title: string; cells: SubgroupCell[]; note?: string }) {
  const best = (c: SubgroupCell) => {
    const r = c.models.ridge.mae, l = c.models.lightgbm.mae;
    return r === null || l === null ? null : r <= l ? "ridge" : "lightgbm";
  };
  return (
    <div>
      <h4 className="mb-2 text-sm font-bold text-navy-900">{title}</h4>
      <Table head={["Subgroup", "Obs.", "Participants", "Ridge MAE", "LightGBM MAE", "SpO₂ as-is MAE"]} caption={title}>
        {cells.map((c) => {
          const empty = c.n_obs === 0;
          const b = best(c);
          return (
            <tr key={cellName(c)} className={empty ? "text-slate-400" : ""}>
              <td className="py-2 font-semibold">{cellName(c).toUpperCase()}</td>
              <td className="text-right">{c.n_obs}</td>
              <td className="text-right">
                {c.n_participants}
                
              </td>
              {empty ? <td colSpan={3} className="text-right text-xs">No test observations</td> : !c.sufficient ? <td colSpan={3} className="text-right text-xs font-bold text-amber-800">INSUFFICIENT DATA</td> : (<>
                <td className={`text-right ${b === "ridge" ? "font-bold text-navy-900" : ""}`}>{f2(c.models.ridge.mae)}</td>
                <td className={`text-right ${b === "lightgbm" ? "font-bold text-navy-900" : ""}`}>{f2(c.models.lightgbm.mae)}</td>
                <td className="text-right text-slate-500">{f2(c.models.spo2_as_is.mae)}</td>
              </>)}
            </tr>
          );
        })}
      </Table>
      {note && <p className="mt-1 text-xs text-slate-500">{note}</p>}
    </div>
  );
}

function PredictionChart({ rows }: { rows: PredictionRow[] }) {
  const data = useMemo(() => ({
    ridge: rows.map((r) => ({ actual: r.sao2, predicted: r.ridge_prediction })),
    lgbm: rows.map((r) => ({ actual: r.sao2, predicted: r.lightgbm_prediction })),
    lo: Math.floor(Math.min(...rows.map((r) => Math.min(r.sao2, r.ridge_prediction, r.lightgbm_prediction)))),
    hi: Math.ceil(Math.max(...rows.map((r) => Math.max(r.sao2, r.ridge_prediction, r.lightgbm_prediction)))),
  }), [rows]);
  return (
    <div className="h-80 w-full" role="img" aria-label="Scatter plot of predicted versus measured SaO2 on the test set">
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
          <XAxis type="number" dataKey="actual" name="SaO₂" domain={[data.lo, data.hi]} tick={{ fontSize: 11 }}
                 label={{ value: "Measured SaO₂ (test set)", position: "insideBottom", offset: -12, fontSize: 11 }} />
          <YAxis type="number" dataKey="predicted" name="Predicted" domain={[data.lo, data.hi]} tick={{ fontSize: 11 }} width={44} />
          <ChartTip formatter={(v) => Number(v).toFixed(2)} cursor={{ strokeDasharray: "3 3" }} />
          <Legend verticalAlign="top" height={28} />
          <ReferenceLine segment={[{ x: data.lo, y: data.lo }, { x: data.hi, y: data.hi }]} stroke="#94a3b8" strokeDasharray="4 4" />
          <Scatter name="Ridge" data={data.ridge} fill="#4f46e5" fillOpacity={0.65} isAnimationActive={false} />
          <Scatter name="LightGBM" data={data.lgbm} fill="#f59e0b" fillOpacity={0.65} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

const EMPTY_PRED = { spo2: "", pi: "", ita: "", sqi: "", motion: "" };

export default function Models() {
  const rs = useResearchStatus();
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [res, setRes] = useState<TrainResult | null>(null);
  const [preds, setPreds] = useState<PredictionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [general, setGeneral] = useState("");
  const [form, setForm] = useState(EMPTY_PRED);
  const [pOut, setPOut] = useState<PredictOut | null>(null);
  const [pErr, setPErr] = useState<FieldError[]>([]);

  async function refresh() {
    setLoading(true); setGeneral("");
    try {
      const s = await fetchModelStatus();
      setStatus(s);
      if (s.trained) {
        const [m, p] = await Promise.all([fetchModelMetrics(), fetchTestPredictions()]);
        setRes(m); setPreds(p.rows);
      } else { setRes(null); setPreds([]); }
    } catch (e) {
      setGeneral((e as Error).message);
    } finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);

  async function train() {
    setTraining(true); setErrors([]); setGeneral(""); setPOut(null);
    try {
      await trainModels();
      await refresh();
    } catch (e) {
      if (e instanceof ValidationFailed) setErrors(e.errors); else setGeneral((e as Error).message);
    } finally { setTraining(false); }
  }

  async function predict(e: React.FormEvent) {
    e.preventDefault(); setPErr([]); setPOut(null);
    const num = (s: string) => (s.trim() === "" ? null : Number.isFinite(Number(s)) ? Number(s) : s.trim());
    try {
      const body: Record<string, unknown> = { spo2: num(form.spo2), pi: num(form.pi), ita: num(form.ita) };
      if (res?.features.includes("sqi")) body.sqi = num(form.sqi);
      if (res?.features.includes("motion")) body.motion = num(form.motion);
      setPOut(await predictModel(body));
    } catch (err) {
      if (err instanceof ValidationFailed) setPErr(err.errors); else setPErr([{ field: "model", code: "x", message: (err as Error).message }]);
    }
  }

  const prov = res?.data_provenance ?? status?.data_provenance ?? status?.current_data_provenance;
  const best = res?.best_model;
  const sp = res?.dataset.splits;
  const rows: [string, "ridge" | "lightgbm"][] = [["Ridge", "ridge"], ["LightGBM", "lightgbm"]];

  return (
    <div className="space-y-6">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          {(status?.research_status ?? rs) && <Badge tone={STATUS_TONE[labelForState((status?.research_status ?? rs)!.state)]} dot>{labelForState((status?.research_status ?? rs)!.state)}</Badge>}
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight text-navy-900 sm:text-4xl">Models</h1>
        <p className="mt-2 max-w-2xl text-slate-600">
          Interpretable baseline versus nonlinear comparator for estimating SaO₂ from the pulse-oximeter reading and its context, evaluated on held-out participants.
        </p>
      </header>

      {prov && <Banner prov={prov} />}
      <NotAResultBanner />
      {general && <div className="card flex gap-3 border-rose-200 p-5 text-sm text-rose-800"><TriangleAlert size={18} className="shrink-0" /> {general}</div>}
      {errors.length > 0 && (
        <div className="card border-rose-200 p-6" role="alert">
          <h3 className="flex items-center gap-2 font-bold text-rose-700"><TriangleAlert size={18} /> Training could not run</h3>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-rose-800">{errors.map((e) => <li key={e.field + e.code}>{e.message}</li>)}</ul>
        </div>
      )}

      <section className="card p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-bold text-navy-900">Training status</h2>
            {loading ? <p className="mt-2 flex items-center gap-2 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> Loading…</p> : (
              <p className="mt-2 text-sm text-slate-600">
                {status && (status.trained ? <>Trained <strong>{new Date(status.trained_at!).toLocaleString()}</strong>.</> : <><strong>MODEL NOT TRAINED.</strong> Real research data required.</>)}
                {status && !status.processed_data_available && <span className="ml-1 text-amber-800"> Processed data not found — build the research dataset and run Validate &amp; split first.</span>}
                {status && !status.lightgbm_available && <span className="ml-1 text-rose-700"> LightGBM is not installed (<code>pip install lightgbm</code>).</span>}
              </p>
            )}
            {status?.stale && <p className="mt-1 text-sm font-semibold text-amber-800">{status.stale_reason}</p>}
          </div>
          <button onClick={train} disabled={training || loading || status?.processed_data_available === false || status?.lightgbm_available === false || status?.current_data_provenance.kind !== "LOADED" || status?.research_data.blocked === true || status?.readiness.status !== "READY FOR TRAINING"}
                  className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-5 py-3 text-sm font-bold tracking-wide text-white shadow-md hover:brightness-110 disabled:opacity-50">
            {training ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} {status?.trained ? "RETRAIN MODELS" : "TRAIN MODELS"}
          </button>
        </div>
        {status && (
          <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm" aria-label="Dataset status">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Dataset status</div>
            <div className={`mt-1 text-sm font-extrabold ${status.readiness.status === "READY FOR TRAINING" ? "text-emerald-600" : "text-rose-700"}`}>{status.readiness.status}</div>
            <div className="mt-1 text-lg font-extrabold text-slate-700">{status.research_data.records} valid records</div>
            <div className="text-slate-600">Participants: {status.research_data.participants} · Sessions: {status.research_data.sessions}</div>
            {status.readiness.status !== "READY FOR TRAINING" && <p className="mt-2 font-semibold text-rose-800">Training unavailable — real research dataset is not ready.</p>}
            {status.research_data.blocked && (
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-amber-900">{status.research_data.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            )}
          </div>
        )}
        {sp && (
          <dl className="mt-5 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            {[["Dataset used", res!.data_provenance.file ?? "loaded dataset"],
              ["Training participants", `${sp.train.participants} (${sp.train.rows} rows)`],
              ["Calibration participants", `${sp.calibration.participants} — not used here`],
              ["Test participants", `${sp.test.participants} (${sp.test.rows} rows)`]].map(([k, v]) => (
              <div key={k} className="rounded-xl bg-slate-50 px-3 py-2.5">
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{k}</dt>
                <dd className="mt-0.5 font-semibold text-navy-900">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <ConformalPanel />

      {res && best && (
        <>
          <section className="card p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-bold text-navy-900">Model comparison <span className="text-sm font-normal text-slate-500">(test set only)</span></h2>
              <Badge tone="indigo">Empirical evaluation on the loaded dataset</Badge>
            </div>
            <Table head={["Model", "MAE", "RMSE", "Bias", "R²"]} caption="Model comparison on the test set">
              {rows.map(([label, k]) => {
                const m = res.models[k].metrics;
                const isBest = best.name === k;
                return (
                  <tr key={k} className={isBest ? "bg-indigo-50/60" : ""}>
                    <td className="py-2.5 font-semibold text-navy-900">{label}{isBest && <span className="ml-2 rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-bold text-indigo-800">LOWEST MAE</span>}
                      <div className="text-[11px] font-normal text-slate-500">{res.models[k].label}</div></td>
                    <td className="text-right font-mono">{f2(m.mae)}</td><td className="text-right font-mono">{f2(m.rmse)}</td>
                    <td className="text-right font-mono">{f2(m.bias)}</td><td className="text-right font-mono">{f2(m.r2)}</td>
                  </tr>
                );
              })}
              <tr className="text-slate-500">
                <td className="py-2.5">SpO₂ reading as-is<div className="text-[11px]">reference, no model</div></td>
                <td className="text-right font-mono">{f2(res.reference.metrics.mae)}</td><td className="text-right font-mono">{f2(res.reference.metrics.rmse)}</td>
                <td className="text-right font-mono">{f2(res.reference.metrics.bias)}</td><td className="text-right font-mono">{f2(res.reference.metrics.r2)}</td>
              </tr>
            </Table>
            <div className="mt-4 rounded-xl bg-slate-50 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Best performing model (by test MAE)</div>
              <div className="mt-1 text-xl font-extrabold text-navy-900">{best.name === "ridge" ? "Ridge regression" : "LightGBM"}</div>
              <p className="mt-1 text-sm text-slate-600">
                MAE {f2(best.mae)} vs {f2(best.other_mae)} for the other model (difference {f2(best.mae_difference)}). {best.note}
              </p>
              {res.reference.metrics.mae !== null && res.reference.metrics.mae <= best.mae && (
                <p className="mt-2 text-sm font-semibold text-amber-900">Reading the SpO₂ value as-is has an equal or lower MAE ({f2(res.reference.metrics.mae)}) than either model on this dataset.</p>
              )}
            </div>
            <p className="mt-3 text-xs text-slate-500">
              {res.models.ridge.metrics.n_obs} test observations from {res.models.ridge.metrics.n_participants} participants. {res.error_definition}. MAE = mean absolute error, RMSE = root mean squared error, Bias = mean error, R² = variance explained.
            </p>
          </section>

          <section className="card space-y-6 p-6">
            <div>
              <h2 className="font-bold text-navy-900">Subgroup error <span className="text-sm font-normal text-slate-500">(test-set MAE)</span></h2>
              <p className="mt-1 text-sm text-slate-600">
                Errors split by <Term label="objective pigmentation (ITA)" tip="ITA groups are an objective colorimetric category, not race. Cut-offs are configured values." /> and perfusion (PI).
                {" "}{res.subgroups.note}
              </p>
            </div>
            <SubgroupTable title="By objective pigmentation (ITA)" cells={res.subgroups.ita} />
            <SubgroupTable title="By perfusion (PI)" cells={res.subgroups.pi} />
            <SubgroupTable title="By ITA × PI" cells={res.subgroups.ita_x_pi}
                           note={`LOW n = fewer than ${res.subgroups.min_participants} test participants. Empty cells are shown as empty, never filled in.`} />
          </section>

          {preds.length > 0 && (
            <section className="card p-6">
              <h2 className="font-bold text-navy-900">Prediction comparison</h2>
              <p className="mb-3 mt-1 text-sm text-slate-600">Each dot is one test observation. Points on the dashed line would be perfect predictions.</p>
              <PredictionChart rows={preds} />
              <div className="mt-4">
                <Table head={["Participant", "SpO₂", "SaO₂", "Ridge", "LightGBM", "Ridge error", "LightGBM error"]} caption="First test predictions">
                  {preds.slice(0, 8).map((r, i) => (
                    <tr key={i} className="font-mono text-xs">
                      <td className="py-1.5 font-sans font-semibold">{r.participant_id}</td>
                      <td className="text-right">{f2(r.spo2, 2)}</td><td className="text-right">{f2(r.sao2, 2)}</td>
                      <td className="text-right">{f2(r.ridge_prediction, 2)}</td><td className="text-right">{f2(r.lightgbm_prediction, 2)}</td>
                      <td className="text-right">{f2(r.ridge_error, 2)}</td><td className="text-right">{f2(r.lightgbm_error, 2)}</td>
                    </tr>
                  ))}
                </Table>
                <p className="mt-1 text-xs text-slate-500">Showing 8 of {preds.length}. All rows are saved in results/test_predictions.csv.</p>
              </div>
            </section>
          )}

          <section className="card p-6">
            <h2 className="font-bold text-navy-900">Try a prediction</h2>
            <p className="mt-1 text-sm text-slate-600">Inputs use the same scales as the loaded training data. Only the inputs the trained models use are asked for; nothing is pre-filled.</p>
            <form onSubmit={predict} noValidate className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5">
              {(["spo2", "pi", "ita", "sqi", "motion"] as const).filter((k) => k === "spo2" || k === "pi" || k === "ita" || res.features.includes(k)).map((k) => {
                const er = pErr.find((e) => e.field === k)?.message;
                return (
                  <label key={k} className="block">
                    <span className="mb-1 block text-[11px] font-semibold uppercase text-slate-500">{k}</span>
                    <input value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} inputMode="decimal" aria-label={k}
                           className={`w-full rounded-lg border px-2.5 py-2 text-sm font-medium outline-none focus:ring-2 ${er ? "border-rose-300 focus:ring-rose-200" : "border-slate-200 focus:border-indigo-400 focus:ring-indigo-100"}`} />
                    {er && <span role="alert" className="mt-1 block text-xs font-semibold text-rose-600">{er}</span>}
                  </label>
                );
              })}
              <div className="col-span-2 md:col-span-5"><button className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:brightness-110">PREDICT</button></div>
            </form>
            {pErr.some((e) => e.field === "model" || !["spo2", "pi", "ita", "sqi", "motion"].includes(e.field)) && (
              <p role="alert" className="mt-2 text-sm font-semibold text-rose-700">{pErr.find((e) => !["spo2", "pi", "ita", "sqi", "motion"].includes(e.field))?.message}</p>
            )}
            {pOut && (
              <div className="mt-4 rounded-xl bg-slate-50 p-4">
                <div className="flex flex-wrap gap-6">
                  {(["ridge", "lightgbm"] as const).map((k) => pOut.predictions[k] !== undefined && (
                    <div key={k}><div className="text-[11px] font-semibold uppercase text-slate-500">{k === "ridge" ? "Ridge" : "LightGBM"} estimate</div>
                      <div className="text-2xl font-bold text-navy-900">{f2(pOut.predictions[k], 2)}<span className="text-sm text-slate-400"> %</span></div></div>
                  ))}
                </div>
                {pOut.warnings.map((w) => <p key={w} className="mt-2 text-xs font-semibold text-amber-800">{w}</p>)}
                <p className="mt-2 text-xs text-slate-500">{pOut.disclaimer}</p>
              </div>
            )}
          </section>

          <section className="card p-6">
            <h2 className="font-bold text-navy-900">Method and reproducibility</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
              <li>Predictors: {res.features.join(", ")}. Target: {res.target}. Participant ID and the target are never predictors.{Object.entries(res.excluded_features).map(([k, v]) => ` ${k} was not used (${v}).`).join("")}</li>
              <li>Both models are fitted on the training split only. Hyperparameters are chosen by participant-grouped cross-validation inside the training split (Ridge α = {String(res.models.ridge.best_params["ridge__alpha"])}; LightGBM leaves = {String(res.models.lightgbm.best_params["num_leaves"])}, trees = {String(res.models.lightgbm.best_params["n_estimators"])}).</li>
              <li>The test split is used once, after fitting, for evaluation. The calibration split is reserved for conformal calibration.</li>
              <li>Software: scikit-learn {res.software.scikit_learn}, LightGBM {res.software.lightgbm}, pandas {res.software.pandas}, Python {res.software.python}. Artifacts: models/ridge_model.joblib, models/lightgbm_model.joblib, results/model_metrics.json.</li>
              <li>This is an empirical evaluation of model performance. It makes no claim of clinical accuracy, bias elimination, or fairness.</li>
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
