import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { NotAResultBanner, SafetyNote, Unavailable } from "../components/Safety";
import { fetchXai, fmt, type Loaded, type XaiReport } from "../lib/validationApi";

export default function Xai({ embedded = false }: { embedded?: boolean }) {
  const [r, setR] = useState<Loaded<XaiReport> | null>(null);
  useEffect(() => { fetchXai().then(setR); }, []);
  if (!r) return <p className="text-sm text-slate-500">Loading…</p>;
  const heading = embedded ? null : <h1 className="sr-only">Explainability</h1>;
  if (!r.ok) return <div className="space-y-4">{heading}<Unavailable title="Explainable AI" message={r.message} /><SafetyNote /></div>;
  const d = r.data;
  const shap = d.lightgbm.rows.map((x) => ({ name: x.feature, "Mean |SHAP|": +x.mean_abs_shap.toFixed(4), "Gain share": +x.gain_importance.toFixed(4) }));
  return (
    <div className="space-y-5">
      {heading}
      {!embedded && <NotAResultBanner />}
      <p className="rounded-xl bg-indigo-50 px-4 py-3 text-sm font-semibold text-indigo-900">{d.notice}</p>
      <section className="card p-5" aria-label="Feature importance">
        <h3 className="font-bold text-navy-900">LightGBM feature importance</h3>
        <div className="mt-2 h-72"><ResponsiveContainer><BarChart data={shap} layout="vertical" margin={{ left: 60 }}><CartesianGrid strokeDasharray="3 3" /><XAxis type="number" fontSize={11} /><YAxis type="category" dataKey="name" fontSize={11} /><Tooltip /><Legend />
          <Bar dataKey="Mean |SHAP|" fill="#6366f1" /><Bar dataKey="Gain share" fill="#10b981" /></BarChart></ResponsiveContainer></div>
        <p className="text-xs text-slate-500">{d.lightgbm.note} SHAP computed on: {d.lightgbm.shap_data}.</p>
        <table className="mt-2 w-full text-xs"><thead><tr className="text-left uppercase text-slate-500"><th>Feature</th><th>Mean |SHAP|</th><th>Mean SHAP (signed)</th><th>Gain share</th></tr></thead>
          <tbody>{d.lightgbm.rows.map((x) => <tr key={x.feature} className="border-t border-slate-100"><td className="py-1">{x.description} <span className="text-slate-400">({x.feature})</span></td><td>{fmt(x.mean_abs_shap, 3)}</td><td>{fmt(x.mean_shap, 3)}</td><td>{fmt(x.gain_importance, 3)}</td></tr>)}</tbody></table>
      </section>
      <section className="card p-5" aria-label="Ridge coefficients">
        <h3 className="font-bold text-navy-900">Ridge coefficients</h3>
        <p className="text-xs text-slate-500">{d.ridge.note} Intercept {fmt(d.ridge.intercept, 3)}, α = {d.ridge.alpha}.</p>
        <table className="mt-2 w-full text-xs"><thead><tr className="text-left uppercase text-slate-500"><th>Feature</th><th>Standardized</th><th>Per original unit</th><th>Direction</th></tr></thead>
          <tbody>{d.ridge.rows.map((x) => <tr key={x.feature} className="border-t border-slate-100"><td className="py-1">{x.description} <span className="text-slate-400">({x.feature})</span></td><td>{fmt(x.coef_standardized, 3)}</td><td>{fmt(x.coef_per_unit, 4)}</td><td>{x.direction}</td></tr>)}</tbody></table>
      </section>
      {d.interval_models && (
        <section className="card p-5">
          <h3 className="font-bold text-navy-900">Interval (quantile) models: gain share</h3>
          <div className="mt-2 grid gap-4 md:grid-cols-2">{(["lo", "hi"] as const).map((k) => (
            <div key={k}><div className="text-xs font-semibold uppercase text-slate-500">{k === "lo" ? "Lower quantile (5%)" : "Upper quantile (95%)"}</div>
              <ul className="mt-1 text-xs">{d.interval_models![k].map((x) => <li key={x.feature} className="flex justify-between border-t border-slate-100 py-1"><span>{x.description}</span><span>{fmt(x.gain_importance, 3)}</span></li>)}</ul></div>))}</div>
        </section>
      )}
      <p className="text-sm text-slate-700">{d.explanation}</p>
      <SafetyNote />
    </div>
  );
}
