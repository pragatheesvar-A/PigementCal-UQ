import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Database, Loader2, Play, TriangleAlert } from "lucide-react";
import { Badge } from "../components/ui";
import { ApiError, fetchQuality, fetchStatus, processDataset, type DatasetStatus, type ProcessResult } from "../lib/datasetApi";

export default function Dataset({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<DatasetStatus | null>(null);
  const [quality, setQuality] = useState<ProcessResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [s, q] = await Promise.all([fetchStatus(), fetchQuality()]);
      setStatus(s); setQuality("rows_in" in q ? q : null);
    } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  async function process() {
    setBusy(true); setError("");
    try { setQuality(await processDataset()); await refresh(); onChanged(); }
    catch (e) { setError((e as ApiError).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          <Badge tone={status?.loaded && status.verified ? "green" : "amber"} dot>{!status?.loaded ? "No research data" : status.verified ? "Research data available" : "UNVERIFIED DATA — NOT A RESEARCH RESULT"}</Badge>
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight text-navy-900 sm:text-4xl">Dataset</h1>
        <p className="mt-2 max-w-2xl text-slate-600">
          Validate the research dataset built on the Data Collection page and split it by participant, so nobody appears in more than one of train, calibration and test.
          This step does not train any model.
        </p>
      </header>

      {error && <div role="alert" className="card flex gap-3 border-rose-200 p-5 text-sm text-rose-800"><TriangleAlert size={18} className="shrink-0" /> {error}</div>}

      <section className="card p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 font-bold text-navy-900"><Database size={18} className="text-indigo-600" /> Research dataset</h2>
            {status?.loaded ? (
              <dl className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                {[["Source", status.file], ["Records", status.rows], ["Participants", status.participants], ["Devices", status.devices || "not given"]].map(([k, v]) => (
                  <div key={String(k)} className="rounded-xl bg-slate-50 px-3 py-2.5"><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{k}</dt><dd className="mt-0.5 break-all font-semibold text-navy-900">{String(v)}</dd></div>
                ))}
              </dl>
            ) : (
              <p className="mt-2 text-sm text-slate-600">
                REAL DATA: 0 records. Nothing is generated or simulated. Upload and build your data on the <a href="#data-collection" className="font-semibold text-indigo-600 underline">Data Collection</a> page.
              </p>
            )}
          </div>
          {status?.loaded && (
            <button onClick={process} disabled={busy}
                    className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-2.5 text-sm font-bold text-white shadow-md hover:brightness-110 disabled:opacity-50">
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} {status.processed ? "Re-process" : "Validate & split"}
            </button>
          )}
        </div>
      </section>

      {quality && (
        <section className="card space-y-5 p-6" aria-label="Processing result">
          <h2 className="flex items-center gap-2 font-bold text-navy-900"><CheckCircle2 size={18} className="text-emerald-600" /> Processed</h2>
          <dl className="grid grid-cols-3 gap-3 text-sm">
            {[["Rows in", quality.rows_in], ["Rows kept", quality.rows_kept], ["Rows dropped", quality.rows_dropped]].map(([k, v]) => (
              <div key={String(k)} className="rounded-xl bg-slate-50 px-3 py-2.5"><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{k}</dt><dd className="mt-0.5 text-xl font-bold text-navy-900">{String(v)}</dd></div>
            ))}
          </dl>
          <div>
            <h3 className="mb-2 text-sm font-bold text-navy-900">Dropped rows by reason <span className="font-normal text-slate-500">(each row counted once, under the first rule it breaks)</span></h3>
            <table className="w-full max-w-xl text-sm"><tbody className="divide-y divide-slate-100">
              {Object.entries(quality.dropped_by_reason).map(([k, v]) => (
                <tr key={k} className={v === 0 ? "text-slate-400" : ""}><td className="py-1.5">{k.replace(/_/g, " ")}</td><td className="py-1.5 text-right font-mono font-semibold">{v}</td></tr>
              ))}
            </tbody></table>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-bold text-navy-900">Participant-level split <span className="font-normal text-slate-500">(stratified by ITA tertile; no participant in two splits)</span></h3>
            <table className="w-full max-w-xl text-sm">
              <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="pb-1">Split</th><th className="text-right">Participants</th><th className="text-right">Rows</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {(["train", "calibration", "test"] as const).map((k) => (
                  <tr key={k}><td className="py-1.5 font-semibold capitalize">{k}</td><td className="text-right font-mono">{quality.splits[k].participants}</td><td className="text-right font-mono">{quality.splits[k].rows}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-sm text-slate-600">
            <p><strong>Predictors:</strong> {quality.predictors.join(", ")}.</p>
            {Object.entries(quality.excluded_optional_predictors).map(([k, v]) => <p key={k} className="text-amber-800">Excluded {k}: {v}.</p>)}
          </div>
        </section>
      )}
    </div>
  );
}
