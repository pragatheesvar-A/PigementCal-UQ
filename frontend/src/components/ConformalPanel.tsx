import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Loader2, Play, ShieldCheck, TriangleAlert } from "lucide-react";
import { Badge, Term } from "./ui";
import {
  ApiError, fetchConformalStatus, fetchCoverage, fitConformal,
  type CalibrationCell, type ConformalStatus, type CoverageReport, type CoverageResponse, type GroupCoverage,
} from "../lib/conformalApi";

const pct = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null, d = 2) => (v === null ? "—" : v.toFixed(d));

const CHIP: Record<string, string> = { CALIBRATED: "bg-emerald-100 text-emerald-800", MERGED: "bg-amber-100 text-amber-900", INSUFFICIENT: "bg-rose-100 text-rose-800" };

function CoverageTable({ title, rows, target, label }: { title: string; rows: GroupCoverage[]; target: number; label: (g: GroupCoverage) => string }) {
  return (
    <div>
      <h4 className="mb-2 text-sm font-bold text-navy-900">{title}</h4>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">{title}</caption>
          <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500">
            <tr><th className="pb-2">Group</th><th className="text-right">Test readings</th><th className="text-right">Participants</th><th className="text-right">Coverage</th><th className="text-right">Mean width</th><th className="text-right">Lower-bound violations</th><th className="text-right">Abstained</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((g) => {
              const none = g.n_obs === 0;
              return (
                <tr key={label(g)} className={none ? "text-slate-400" : ""}>
                  <td className="py-2 font-semibold">{label(g)}</td>
                  <td className="text-right">{g.n_obs}</td>
                  <td className="text-right">{g.n_participants}{!none && g.low_n && <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-800" title="Too few test participants to interpret">LOW n</span>}</td>
                  {none ? <td colSpan={3} className="text-right text-xs">{g.n_total > 0 ? "No intervals produced" : "No test readings"}</td> : (<>
                    <td className={`text-right font-semibold ${g.coverage !== null && g.coverage < target - 0.05 ? "text-amber-700" : "text-navy-900"}`}>{pct(g.coverage)}</td>
                    <td className="text-right">{num(g.mean_width)}</td>
                    <td className="text-right">{pct(g.lower_bound_violation_rate)}</td>
                  </>)}
                  <td className="text-right">{g.n_abstained}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Compare({ cov }: { cov: CoverageResponse }) {
  const rows: [string, string, CoverageReport][] = [
    ["Mondrian CQR (ITA × PI cells)", "the proposed calibration", cov.mondrian],
    ["Marginal CQR (one pooled Q)", "no subgroup calibration", cov.marginal],
    ["Raw quantiles (no calibration)", "before conformal correction", cov.uncalibrated_quantiles],
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[460px] text-sm">
        <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="pb-2">Method</th><th className="text-right">Coverage</th><th className="text-right">Mean width</th><th className="text-right">Lower-bound violations</th></tr></thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map(([name, sub, r]) => (
            <tr key={name}><td className="py-2 font-semibold text-navy-900">{name}<div className="text-[11px] font-normal text-slate-500">{sub}</div></td>
              <td className="text-right font-mono">{pct(r.overall.coverage)}</td><td className="text-right font-mono">{num(r.overall.mean_width)}</td><td className="text-right font-mono">{pct(r.overall.lower_bound_violation_rate)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Box({ children }: { children: ReactNode }) { return <div className="rounded-xl bg-slate-50 p-4 text-sm">{children}</div>; }

export default function ConformalPanel() {
  const [status, setStatus] = useState<ConformalStatus | null>(null);
  const [cov, setCov] = useState<CoverageResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const s = await fetchConformalStatus();
      setStatus(s);
      setCov(s.fitted ? await fetchCoverage() : null);
    } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  async function fit() {
    setBusy(true); setError("");
    try { await fitConformal(); await refresh(); } catch (e) { setError((e as ApiError).message); } finally { setBusy(false); }
  }

  const target = status?.target_coverage ?? 0.9;
  const cells: CalibrationCell[] = cov ? Object.values(cov.calibration.cells) : [];

  return (
    <section className="card space-y-5 p-6" aria-label="Conformal reliability">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 font-bold text-navy-900"><ShieldCheck size={18} className="text-indigo-600" /> Conformal reliability <span className="text-sm font-normal text-slate-500">(CQR + ITA × PI Mondrian calibration)</span></h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Quantile models are fitted on the training split, the interval is calibrated on the calibration split, and coverage is evaluated on the test split only.
            Target coverage <strong>{pct(target)}</strong>. Nothing here is fitted automatically.
          </p>
        </div>
        <button onClick={fit} disabled={busy || !status?.can_fit}
                className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-5 py-2.5 text-sm font-bold text-white shadow-md hover:brightness-110 disabled:opacity-50">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} {status?.fitted ? "REFIT & RECALIBRATE" : "FIT & CALIBRATE"}
        </button>
      </div>

      {error && <div role="alert" className="flex gap-2 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-800"><TriangleAlert size={16} className="mt-0.5 shrink-0" /> {error}</div>}

      {status && !status.fitted && (
        <Box>
          <div className="font-bold text-navy-900">CONFORMAL MODEL NOT AVAILABLE <span className="ml-1 text-xs font-semibold text-slate-500">· NOT EVALUATED</span></div>
          <p className="mt-1 text-slate-600">No conformal interval exists yet, so the Reliability page shows no calibrated range and abstains where it would need one.</p>
          {status.blockers.length > 0 && <ul className="mt-2 list-disc space-y-0.5 pl-5 text-amber-900">{status.blockers.map((b) => <li key={b}>{b}</li>)}</ul>}
        </Box>
      )}
      {status?.stale && <p className="rounded-lg bg-amber-100 px-3 py-2 text-sm font-semibold text-amber-900">The data changed after this calibration — refit and recalibrate.</p>}

      {cov && status?.fitted && (
        <>
          <div>
            <h3 className="mb-2 text-sm font-bold text-navy-900">Calibration cells <span className="font-normal text-slate-500">(ITA group × PI group; rule: {cov.calibration.min_cell_participants} participants and {cov.calibration.min_cell_rows} readings per cell)</span></h3>
            <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-sm">
              <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="pb-2">Cell</th><th>Status</th><th className="text-right">Cal. participants</th><th className="text-right">Cal. readings</th><th className="text-right">Q (points)</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {cells.map((c) => (
                  <tr key={c.label}>
                    <td className="py-2 font-semibold">{c.label.toUpperCase()}</td>
                    <td><span className={`rounded px-2 py-0.5 text-[11px] font-bold ${CHIP[c.status]}`}>{c.status === "INSUFFICIENT" ? "INSUFFICIENT CALIBRATION DATA" : c.status}</span>
                      {c.status === "MERGED" && <div className="mt-0.5 text-[11px] text-slate-500">{c.source}</div>}</td>
                    <td className="text-right">{c.n_participants}</td><td className="text-right">{c.n_rows}</td><td className="text-right font-mono">{num(c.q)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
            <p className="mt-2 text-xs text-slate-500">
              Cells without enough calibration participants are merged only by one documented rule (pool the two PI cells of the same ITA group — flagged MERGED, not a per-cell guarantee),
              otherwise they stay <strong>INSUFFICIENT CALIBRATION DATA</strong>: no interval is produced and the reliability state abstains. No data are invented.
            </p>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-bold text-navy-900">Test-set coverage <span className="font-normal text-slate-500">(target {pct(cov.target_coverage)}; test split only)</span></h3>
            <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              {[["Overall coverage", pct(cov.mondrian.overall.coverage), `target ${pct(cov.target_coverage)}`], ["Mean interval width", `${num(cov.mondrian.overall.mean_width)} pts`, "SaO₂ percentage points"],
                ["Lower-bound violations", pct(cov.mondrian.overall.lower_bound_violation_rate), "SaO₂ below the conformal lower bound"], ["Abstained readings", String(cov.mondrian.overall.n_abstained), `of ${cov.mondrian.overall.n_total} test readings`]].map(([k, v, s]) => (
                <div key={k} className="rounded-xl bg-slate-50 px-3 py-2.5"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{k}</div><div className="mt-0.5 text-xl font-bold text-navy-900">{v}</div><div className="text-[11px] text-slate-500">{s}</div></div>
              ))}
            </div>
            <div className="space-y-6">
              <CoverageTable title="By objective pigmentation (ITA group)" rows={cov.mondrian.ita} target={cov.target_coverage} label={(g) => (g.group ?? "").toUpperCase()} />
              <CoverageTable title="By perfusion (PI group)" rows={cov.mondrian.pi} target={cov.target_coverage} label={(g) => (g.group ?? "").toUpperCase()} />
              <CoverageTable title="By ITA × PI cell" rows={cov.mondrian.ita_x_pi} target={cov.target_coverage} label={(g) => (g.label ?? "").toUpperCase()} />
            </div>
            <p className="mt-2 text-xs text-slate-500">Coverage is the share of test readings whose measured SaO₂ fell inside the interval. Groups with few test participants are flagged LOW n and should not be over-read.</p>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-bold text-navy-900">Does subgroup calibration change coverage? <span className="font-normal text-slate-500">(same test readings)</span></h3>
            <Compare cov={cov} />
          </div>

          <Box>
            <div className="font-bold text-navy-900"><Term label="How to read this" tip="Split-conformal procedures give coverage on average over the calibration draw, assuming calibration and new readings are exchangeable within the cell." /></div>
            <p className="mt-1 text-slate-600">{cov.wording}</p>
          </Box>
        </>
      )}
      
    </section>
  );
}
