import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { Badge } from "../components/ui";
import { SafetyNote, Unavailable } from "../components/Safety";
import Limitations from "../components/Limitations";
import Xai from "./Xai";
import type { Health } from "../lib/api";
import { STATUS_TONE, researchStatus, statusLines } from "../lib/status";
import { ci, fetchResearchGate, fetchValidation, fmt, type CovGroup, type ResearchGate, type ErrGroup, type Hist, type Loaded, type MetricRow, type ValidationReport } from "../lib/validationApi";

const COLORS = ["#94a3b8", "#6366f1", "#10b981"];
const card = "card p-5";

function MetricTable({ title, rows }: { title: string; rows: Record<string, MetricRow[]> }) {
  const metrics = Object.values(rows)[0]?.map((r) => r.metric) ?? [];
  return (
    <section className={card}>
      <h3 className="font-bold text-navy-900">{title}</h3>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-[11px] uppercase text-slate-500"><th className="py-1 pr-3">Model</th>{metrics.map((m) => <th key={m} className="pr-3">{m} (95% CI)</th>)}<th>n obs / participants</th></tr></thead>
          <tbody>
            {Object.entries(rows).map(([name, r]) => (
              <tr key={name} className="border-t border-slate-100 align-top">
                <td className="py-1.5 pr-3 font-semibold">{name}</td>
                {r.map((m) => <td key={m.metric} className="pr-3"><span className="font-semibold text-navy-900">{fmt(m.estimate)}</span> <span className="text-xs text-slate-500">{ci(m)}</span></td>)}
                <td className="text-xs text-slate-600">{r[0]?.n_obs ?? 0} / {r[0]?.n_participants ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ErrBars({ title, groups }: { title: string; groups: ErrGroup[] }) {
  const data = groups.map((g) => ({ name: g.group, "SpO₂ as-is": g.spo2_as_is[0]?.estimate ?? 0, Ridge: g.ridge[0]?.estimate ?? 0, LightGBM: g.lightgbm[0]?.estimate ?? 0 }));
  return (
    <section className={card} aria-label={title}>
      <h3 className="font-bold text-navy-900">{title}</h3>
      <div className="mt-2 h-56">
        <ResponsiveContainer><BarChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" fontSize={11} /><YAxis fontSize={11} /><Tooltip /><Legend />
          {["SpO₂ as-is", "Ridge", "LightGBM"].map((k, i) => <Bar key={k} dataKey={k} fill={COLORS[i]} />)}</BarChart></ResponsiveContainer>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="text-left uppercase text-slate-500"><th className="py-1">Group</th><th>observations / participants</th><th>Ridge MAE (95% CI)</th><th>LightGBM MAE (95% CI)</th><th>SpO₂ MAE (95% CI)</th></tr></thead>
          <tbody>{groups.map((g) => (
            <tr key={g.group} className="border-t border-slate-100">
              <td className="py-1 font-semibold">{g.group}</td><td>{g.n_obs} / {g.n_participants}</td>
              {g.n_obs === 0 ? <td colSpan={3} className="font-bold text-amber-800">INSUFFICIENT DATA (no test observations)</td>
                : g.status !== "OK" ? <td colSpan={3} className="font-bold text-amber-800">INSUFFICIENT DATA</td>
                : [g.ridge, g.lightgbm, g.spo2_as_is].map((m, i) => <td key={i}>{fmt(m[0]?.estimate)} <span className="text-slate-500">{ci(m[0])}</span></td>)}
            </tr>))}</tbody>
        </table>
      </div>
    </section>
  );
}

function Histo({ title, h, colors }: { title: string; h: Hist; colors: string[] }) {
  const data = h.edges.slice(0, -1).map((e, i) => ({ x: e.toFixed(1), ...Object.fromEntries(Object.entries(h.counts).map(([k, v]) => [k, v[i]])) }));
  return (
    <section className={card} aria-label={title}>
      <h3 className="font-bold text-navy-900">{title}</h3>
      <div className="mt-2 h-56"><ResponsiveContainer><BarChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="x" fontSize={10} /><YAxis fontSize={11} /><Tooltip /><Legend />
        {Object.keys(h.counts).map((k, i) => <Bar key={k} dataKey={k} fill={colors[i % colors.length]} />)}</BarChart></ResponsiveContainer></div>
    </section>
  );
}

function CovBlock({ title, groups, target }: { title: string; groups: CovGroup[]; target: number }) {
  const get = (g: CovGroup, m: string) => g.metrics.find((x) => x.metric === m);
  const cov = groups.map((g) => ({ name: g.group, Coverage: get(g, "Coverage")?.estimate ?? 0, Target: target }));
  const wid = groups.map((g) => ({ name: g.group, Width: get(g, "Mean interval width")?.estimate ?? 0 }));
  return (
    <section className={card} aria-label={title}>
      <h3 className="font-bold text-navy-900">{title}</h3>
      <div className="mt-2 grid gap-4 md:grid-cols-2">
        <div className="h-52"><ResponsiveContainer><BarChart data={cov}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" fontSize={10} /><YAxis domain={[0, 1]} fontSize={11} /><Tooltip /><Legend /><Bar dataKey="Coverage" fill="#6366f1" /><Bar dataKey="Target" fill="#cbd5e1" /></BarChart></ResponsiveContainer></div>
        <div className="h-52"><ResponsiveContainer><BarChart data={wid}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" fontSize={10} /><YAxis fontSize={11} /><Tooltip /><Legend /><Bar dataKey="Width" name="Mean interval width (pts)" fill="#10b981" /></BarChart></ResponsiveContainer></div>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="text-left uppercase text-slate-500"><th className="py-1">Group</th><th>intervals (participants) / abstained</th><th>Coverage (95% CI)</th><th>Width (95% CI)</th><th>Lower-bound violations (95% CI)</th><th>Median width</th></tr></thead>
          <tbody>{groups.map((g) => {
            const empty = g.status !== "OK" || g.metrics.length === 0 || g.metrics[0].n_obs === 0;
            return (
              <tr key={g.group} className="border-t border-slate-100">
                <td className="py-1 font-semibold">{g.group}</td><td>{g.n_obs} ({g.n_participants}) / {g.n_abstained}</td>
                {["Coverage", "Mean interval width", "Lower-bound violation rate"].map((m) => <td key={m}>{empty ? <span className="font-bold text-amber-800">INSUFFICIENT DATA</span> : <>{fmt(get(g, m)?.estimate, 3)} <span className="text-slate-500">{ci(get(g, m), 3)}</span></>}</td>)}
                <td>{empty ? "—" : fmt(g.median_width, 2)}</td>
              </tr>);
          })}</tbody>
        </table>
      </div>
    </section>
  );
}

export default function Results({ health }: { health: Health | null }) {
  const [r, setR] = useState<Loaded<ValidationReport> | null>(null);
  useEffect(() => { fetchValidation().then(setR); }, []);
  const st = researchStatus(health), lines = statusLines(health);
  const [gate, setGate] = useState<ResearchGate | null>(null);
  useEffect(() => { fetchResearchGate().then((g) => g.ok && setGate(g.data)); }, []);
  const d = r?.ok ? r.data : null;
  const cf = d && d.conformal.available ? d.conformal : null;
  return (
    <div className="space-y-6">
      <h1 className="sr-only">Results</h1>
      <div className="flex flex-wrap items-center gap-2"><Badge tone={STATUS_TONE[st]} dot>{st}</Badge></div>

      <section className={card} aria-label="G Research status">
        <h2 className="font-bold text-navy-900">G · Research status</h2>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          {([["Data", lines.data], ["Model", lines.model], ["Conformal", lines.conformal], ["Research validation", lines.results], ["Hardware", lines.hardware]] as const).map(([k, v]) => (
            <div key={k} className="rounded-xl bg-slate-50 px-3 py-2"><dt className="text-[11px] font-semibold uppercase text-slate-500">{k}</dt><dd className="font-bold text-navy-900">{v}</dd></div>
          ))}
        </dl>
        {gate && !gate.results_allowed && (
          <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900" role="status">
            <div className="font-bold">{gate.label}</div>
            <p className="mt-1 text-xs">A result is shown as research only when every backend check passes. The upload confirmation alone never does.</p>
            {gate.checks.filter((c) => !c.passed).length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs">{gate.checks.filter((c) => !c.passed).map((c) => <li key={c.id}><strong>{c.title}:</strong> {c.detail}</li>)}</ul>
            )}
          </div>
        )}
      </section>

      <section className={card} aria-label="A Dataset">
        <h2 className="font-bold text-navy-900">A · Dataset</h2>
        {health?.dataset.loaded && health.dataset.verified
          ? <p className="mt-2 text-sm text-slate-700">{health.dataset.rows} real records from {health.dataset.participants} participants.{d && <> Test split: {d.sample.test_participants} participants, {d.sample.test_observations} observations. {d.split}.</>}</p>
          : health?.dataset.loaded
            ? <p className="mt-2 text-sm text-slate-700"><strong>{lines.data}.</strong> {health.dataset.rows} records from {health.dataset.participants} participants are loaded, but they are not verified real research data. Everything below is a software-test output, not a research result. See Data Collection.</p>
            : <p className="mt-2 text-sm text-slate-700">NO RESEARCH DATA. Nothing is shown until real, verified data has been collected, split by participant and used for training. See Data Collection.</p>}
      </section>

      {!d ? (
        <Unavailable title="Model performance, subgroup performance, conformal reliability and XAI" message={`MODEL: NOT TRAINED · CONFORMAL: NOT CALIBRATED · RESULTS: NOT EVALUATED. ${r && !r.ok ? r.message : "Loading…"}`} />
      ) : (
        <>
          {d.stale && <Badge tone="amber" dot>Data changed since training — retrain</Badge>}
          <p className="text-xs text-slate-500">{d.bootstrap.method}, {d.bootstrap.replicates} replicates, {Math.round(d.bootstrap.level * 100)}% percentile CI; a CI is shown only when at least {d.bootstrap.min_participants_for_ci} participants contribute. {d.error_definition}</p>
          {d.research_status && !d.research_status.results_allowed && (
            <div role="status" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-800">{d.research_status.label}. The numbers below do not count as research results.</div>
          )}
          <h2 className="font-bold text-navy-900">B · Model performance</h2>
          <MetricTable title="Overall test performance (raw SpO₂ vs Ridge vs LightGBM)" rows={{ "SpO₂ as-is": d.overall.spo2_as_is, Ridge: d.overall.ridge, LightGBM: d.overall.lightgbm }} />
          <section className={card} aria-label="SpO2 vs SaO2">
            <h3 className="font-bold text-navy-900">SpO₂ vs SaO₂ (test)</h3>
            <div className="mt-2 h-72"><ResponsiveContainer><ScatterChart><CartesianGrid strokeDasharray="3 3" /><XAxis type="number" dataKey="sao2" name="SaO₂" domain={["auto", "auto"]} fontSize={11} /><YAxis type="number" dataKey="y" name="Estimate" domain={["auto", "auto"]} fontSize={11} /><Tooltip /><Legend />
              <Scatter name="SpO₂ reading" data={d.plots.scatter.map((p) => ({ sao2: p.sao2, y: p.spo2 }))} fill={COLORS[0]} />
              <Scatter name="Ridge" data={d.plots.scatter.map((p) => ({ sao2: p.sao2, y: p.ridge }))} fill={COLORS[1]} />
              <Scatter name="LightGBM" data={d.plots.scatter.map((p) => ({ sao2: p.sao2, y: p.lightgbm }))} fill={COLORS[2]} /></ScatterChart></ResponsiveContainer></div>
          </section>
          <Histo title="Prediction error distribution (prediction − SaO₂)" h={d.plots.error_hist} colors={COLORS} />
          <h2 className="font-bold text-navy-900">C · Subgroup performance</h2>
          <ErrBars title="ITA subgroup error (MAE)" groups={d.subgroups.ita} />
          <ErrBars title="PI subgroup error (MAE)" groups={d.subgroups.pi} />
          <ErrBars title="ITA × PI error (MAE)" groups={d.subgroups.ita_x_pi} />
          <h2 className="font-bold text-navy-900">D · Conformal reliability</h2>
          {cf ? (
            <>
              <MetricTable title="Conformal coverage overall" rows={{ "All test readings (intervals only)": cf.overall.metrics }} />
              <p className="text-xs text-slate-600">Median interval width (overall): {fmt(cf.overall.median_width, 2)} points.</p>
              <CovBlock title="By ITA group" groups={cf.ita} target={cf.target_coverage} />
              <CovBlock title="By PI group" groups={cf.pi} target={cf.target_coverage} />
              <CovBlock title="By ITA × PI cell" groups={cf.ita_x_pi} target={cf.target_coverage} />
              {d.plots.width_hist && <Histo title="Interval width distribution" h={d.plots.width_hist} colors={["#10b981"]} />}
              <p className="text-xs text-slate-600">{cf.wording}</p>
            </>
          ) : <Unavailable title="Conformal results" message="CONFORMAL MODEL NOT AVAILABLE. Coverage is NOT EVALUATED until the conformal layer is calibrated on real data." />}
          <h2 className="font-bold text-navy-900">E · Explainable AI</h2>
          <Xai embedded />
        </>
      )}

      <section className={card} aria-label="F Limitations">
        <h2 className="font-bold text-navy-900">F · Limitations</h2>
        <div className="mt-2"><Limitations /></div>
      </section>
      <SafetyNote />
    </div>
  );
}
