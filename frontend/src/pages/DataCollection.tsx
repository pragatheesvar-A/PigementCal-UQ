import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { STATUS_TONE, labelForState } from "../lib/status";
import { useResearchStatus } from "../lib/researchContext";
import { CheckCircle2, Download, Loader2, ShieldAlert, Trash2, TriangleAlert, Upload } from "lucide-react";
import { Badge } from "../components/ui";
import {
  ApiError, buildDataset, fetchReport, fetchStatus, removeUpload, uploadCsv,
  type Kind, type NeedsMapping, type Quality, type Report, type Status, type UploadEntry, type UploadParams,
} from "../lib/collectionApi";

type FieldDef = { key: keyof UploadParams; label: string; placeholder?: string; hint?: string; type?: "text" | "select"; options?: { v: string; l: string }[] };

const SOURCE_OPTIONS = [{ v: "esp32", l: "ESP32 + MAX30102" }, { v: "camera", l: "Phone camera" }, { v: "file", l: "Other (systolic peaks already point up)" }];

const CARDS: { kind: Kind; title: string; blurb: string; fields: FieldDef[] }[] = [
  {
    kind: "ppg", title: "A · PPG / Live Monitor CSV",
    blurb: "The file saved by “Save session CSV” on the Live Monitor (t_s, ir, red, ax, ay, az). One recording = one participant and one session. It is turned into analysis windows with SpO₂ estimate, PI, SQI and motion.",
    fields: [
      { key: "participant_id", label: "Participant ID *", placeholder: "P001" },
      { key: "session_id", label: "Session ID *", placeholder: "P001_S01" },
      { key: "device_id", label: "Device ID", placeholder: "e.g. ESP32-01" },
      { key: "source", label: "Sensor type", type: "select", options: SOURCE_OPTIONS, hint: "sets signal polarity" },
      { key: "fs", label: "Sampling rate (Hz)", placeholder: "only if the file has no time column" },
      { key: "recording_start", label: "Recording start", placeholder: "2026-10-07T10:15:00Z", hint: "only needed if the reference file uses clock times" },
    ],
  },
  {
    kind: "reference", title: "B · Reference SaO₂ CSV",
    blurb: "Arterial reference measurements: participant_id, session_id, timestamp, sao2. SaO₂ must come from an actual reference measurement — it is never generated or estimated.",
    fields: [],
  },
  {
    kind: "pigmentation", title: "C · Pigmentation / ITA CSV",
    blurb: "participant_id, session_id (optional), and either ITA or the colorimeter L*, a*, b* (ITA is then computed by the pigmentation module). Repeated measurements use the median; locations are not mixed.",
    fields: [],
  },
  {
    kind: "combined", title: "D · Combined CSV (all columns already merged)",
    blurb: "participant_id, session_id, timestamp, spo2, sao2, pi, ita (or L, a, b), sqi, motion, device_id. Every record is validated individually.",
    fields: [
      { key: "session_id", label: "Session ID for the whole file", placeholder: "only if the file has no session_id column" },
      { key: "device_id", label: "Device ID for the whole file", placeholder: "only if the file has no device column" },
    ],
  },
];

function Tile({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: string; tone?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2.5">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-0.5 text-xl font-bold ${tone ?? "text-navy-900"}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

function MappingEditor({ needs, mapping, onChange, onApply, busy }: { needs: NeedsMapping; mapping: Record<string, string>; onChange: (m: Record<string, string>) => void; onApply: () => void; busy: boolean }) {
  return (
    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4" aria-label="Column mapping">
      <div className="text-sm font-bold text-amber-900">Confirm the column mapping</div>
      <p className="mt-1 text-sm text-amber-900">{needs.message}</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {needs.fields.map((f) => (
          <label key={f.id} className="block">
            <span className="mb-1 block text-xs font-semibold text-slate-600">{f.label}{f.required ? " *" : ""}</span>
            <select value={mapping[f.id] ?? ""} onChange={(e) => onChange({ ...mapping, [f.id]: e.target.value })} aria-label={f.label}
                    className={`w-full rounded-lg border bg-white px-2.5 py-2 text-sm ${needs.missing_fields.includes(f.id) && !mapping[f.id] ? "border-rose-300" : "border-slate-200"}`}>
              <option value="">{f.required ? "— choose a column —" : "— not in my file —"}</option>
              {needs.detected_columns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        ))}
      </div>
      <button onClick={onApply} disabled={busy} className="mt-3 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:brightness-110 disabled:opacity-50">Apply mapping and upload</button>
    </div>
  );
}

function UploadCard({ def, attested, onDone }: { def: (typeof CARDS)[number]; attested: boolean; onDone: () => void }) {
  const [params, setParams] = useState<UploadParams>({ source: "esp32" });
  const [file, setFile] = useState<File | null>(null);
  const [needs, setNeeds] = useState<NeedsMapping | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const ref = useRef<HTMLInputElement>(null);

  async function send(f: File, m?: Record<string, string>) {
    setBusy(true); setMsg(null);
    try {
      const r = await uploadCsv(def.kind, f, params, m);
      if ("needs" in r) { setNeeds(r.needs); setMapping({ ...r.needs.proposed_mapping, ...(m ?? {}) }); }
      else {
        setNeeds(null);
        const s = r.ok.summary;
        setMsg({ ok: true, text: `Staged ${f.name}: ${def.kind === "ppg" ? `${s.windows} analysis windows from ${s.sessions?.length} session(s)` : `${s.rows} rows`}${s.flagged_rows ? `, ${s.flagged_rows} flagged` : ""}.${r.ignored.length ? ` Ignored personal-data columns: ${r.ignored.join(", ")}.` : ""}` });
        setFile(null);
        onDone();
      }
    } catch (e) { setNeeds(null); setMsg({ ok: false, text: (e as ApiError).message }); }
    finally { setBusy(false); }
  }

  return (
    <section className="card p-6" aria-label={def.title}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="font-bold text-navy-900">{def.title}</h2>
        <a href={`/api/collection/template/${def.kind}`} className="flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:underline"><Download size={13} /> header template</a>
      </div>
      <p className="mt-1 text-sm text-slate-600">{def.blurb}</p>
      {def.fields.length > 0 && (
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {def.fields.map((f) => (
            <label key={f.key} className="block">
              <span className="mb-1 block text-xs font-semibold text-slate-600">{f.label}</span>
              {f.type === "select" ? (
                <select value={params[f.key] ?? ""} onChange={(e) => setParams({ ...params, [f.key]: e.target.value })} aria-label={f.label} className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-sm">
                  {f.options!.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
                </select>
              ) : (
                <input value={params[f.key] ?? ""} onChange={(e) => setParams({ ...params, [f.key]: e.target.value })} placeholder={f.placeholder} aria-label={f.label}
                       className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-sm outline-none focus:border-indigo-400" />
              )}
              {f.hint && <span className="mt-0.5 block text-[11px] text-slate-400">{f.hint}</span>}
            </label>
          ))}
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <input ref={ref} type="file" accept=".csv,.txt,text/csv" className="hidden" aria-label={`${def.title} file`}
               onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); void send(f); } e.target.value = ""; }} />
        <button onClick={() => ref.current?.click()} disabled={!attested || busy} title={attested ? "" : "Confirm that the data is real first"}
                className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 hover:border-indigo-300 hover:text-indigo-700 disabled:opacity-50">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />} Choose CSV and upload
        </button>
        {!attested && <span className="text-xs text-slate-500">Tick the confirmation above first.</span>}
      </div>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`mt-3 flex gap-2 text-sm ${msg.ok ? "text-emerald-700" : "text-rose-700"}`}>{msg.ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <TriangleAlert size={16} className="mt-0.5 shrink-0" />}{msg.text}</p>}
      {needs && file && <MappingEditor needs={needs} mapping={mapping} onChange={setMapping} busy={busy} onApply={() => void send(file, Object.fromEntries(Object.entries(mapping).filter(([, v]) => v)))} />}
    </section>
  );
}

function List({ title, rows, extra }: { title: string; rows: { label: string; reason: string }[]; extra: number }) {
  return (
    <details className="rounded-xl border border-slate-200 p-3">
      <summary className="cursor-pointer text-sm font-semibold text-navy-900">{title} <span className="text-slate-500">({rows.length + extra})</span></summary>
      {rows.length === 0 ? <p className="mt-2 text-sm text-slate-500">None.</p> : (
        <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-xs text-slate-600">
          {rows.slice(0, 50).map((r, i) => <li key={i}><strong>{r.label}</strong> — {r.reason}</li>)}
          {rows.length > 50 && <li className="text-slate-400">… and {rows.length - 50} more (first 200 are saved in merge_report.json)</li>}
          {extra > 0 && <li className="text-slate-400">+ {extra} more not listed (counts are complete)</li>}
        </ul>
      )}
    </details>
  );
}

export default function DataCollection({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [attested, setAttested] = useState(false);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const s = await fetchStatus();
      setStatus(s);
      const r = s.built ? await fetchReport() : null;
      setReport(r && !("available" in r) ? r : null);
    } catch (e) { setError((e as Error).message); }
    onChanged();
  }, [onChanged]);
  useEffect(() => { void refresh(); }, [refresh]);

  async function build() {
    setBuilding(true); setError("");
    try { await buildDataset(); await refresh(); } catch (e) { setError((e as ApiError).message); } finally { setBuilding(false); }
  }
  async function remove(u: UploadEntry) {
    try { await removeUpload(u.id); await refresh(); } catch (e) { setError((e as ApiError).message); }
  }

  const q: Quality | null = status?.last_build ?? null;
  const real = status?.real_data;
  const rs = useResearchStatus();

  return (
    <div className="space-y-6">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          <Badge tone="slate" dot>{real?.label ?? "REAL DATA: 0 records"}</Badge>
          {rs && <Badge tone={STATUS_TONE[labelForState(rs.state)]} dot>{labelForState(rs.state)}</Badge>}
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight text-navy-900 sm:text-4xl">Data Collection</h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Bring in your own collected data: PPG recordings from the Live Monitor, reference SaO₂, and objective pigmentation. They are matched by participant and
          session, every record is validated, and nothing unmatched is discarded silently.
        </p>
      </header>

      <div role="note" className="card flex gap-3 border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <ShieldAlert size={18} className="mt-0.5 shrink-0" />
        <p><strong>{status?.consent_notice ?? "Store participant data securely and obtain appropriate consent/ethics approval before real human data collection."}</strong>{" "}
          Use anonymous participant IDs (P001, P002…). Do not upload names, phone numbers, e-mail addresses or home addresses — such columns are ignored and never stored.</p>
      </div>

      {error && <div role="alert" className="card flex gap-3 border-rose-200 p-4 text-sm text-rose-800"><TriangleAlert size={18} className="shrink-0" /> {error}</div>}

      <section className="card p-6" aria-label="Data status">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Research data</div>
            <div className="mt-1 text-3xl font-extrabold text-slate-700">{real?.label ?? "REAL DATA: 0 records"}</div>
            <div className="mt-1 text-sm text-slate-600">Participants: <strong>{real?.participants ?? 0}</strong> · Sessions: <strong>{real?.sessions ?? 0}</strong></div>
            {status?.test_data && <div className="mt-2 text-sm font-semibold text-amber-700">{status.test_data.label}: {status.test_data.participants} participants, {status.test_data.sessions} sessions. For software testing only.</div>}
            <p className="mt-2 max-w-xl text-xs text-slate-500">Only valid, merged records from files you uploaded count as research data. Staged files are not research data until you build the dataset.</p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
            <Tile label="PPG windows" value={status?.staged.ppg_windows ?? 0} sub="staged" />
            <Tile label="Reference rows" value={status?.staged.reference_rows ?? 0} sub="staged" />
            <Tile label="Pigmentation rows" value={status?.staged.pigmentation_rows ?? 0} sub="staged" />
            <Tile label="Combined rows" value={status?.staged.combined_rows ?? 0} sub="staged" />
          </div>
        </div>
        {status?.stale && <p className="mt-3 rounded-lg bg-amber-100 px-3 py-2 text-sm font-semibold text-amber-900">The uploads changed since the last build — build again to update the research dataset.</p>}
      </section>

      <label className="card flex cursor-pointer items-start gap-3 p-4 text-sm text-slate-700">
        <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} className="mt-1 h-4 w-4" aria-label="Confirm real data" />
        <span><strong>I confirm that the files I upload contain real data collected from participants with appropriate consent / ethics approval — not simulated, generated or example data.</strong>
          This confirmation is stored with each upload.</span>
      </label>

      <div className="grid gap-6 xl:grid-cols-2">{CARDS.map((c) => <UploadCard key={c.kind} def={c} attested={attested} onDone={() => void refresh()} />)}</div>

      <section className="card p-6" aria-label="Staged uploads">
        <h2 className="font-bold text-navy-900">Staged uploads</h2>
        {status && status.uploads.length > 0 ? (
          <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[560px] text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="pb-2">ID</th><th>Kind</th><th>File</th><th className="text-right">Rows</th><th className="pl-4">Detail</th><th /></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {status.uploads.map((u) => (
                <tr key={u.id}>
                  <td className="py-2 font-mono text-xs">{u.id}</td><td className="capitalize">{u.kind}</td><td className="max-w-[200px] truncate" title={u.filename}>{u.filename}</td>
                  <td className="text-right font-mono">{u.staged_rows}</td>
                  <td className="pl-4 text-xs text-slate-500">
                    {u.kind === "ppg" ? `${u.summary.sessions?.map((s) => s.session_id).join(", ")} · ${u.summary.spo2_from}` : u.summary.flagged_rows ? `${u.summary.flagged_rows} flagged` : "ok"}
                    {u.ignored_personal_columns.length > 0 && <span className="text-amber-700"> · ignored: {u.ignored_personal_columns.join(", ")}</span>}
                  </td>
                  <td><button aria-label={`Remove ${u.id}`} onClick={() => void remove(u)} className="text-slate-400 hover:text-rose-600"><Trash2 size={15} /></button></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        ) : <p className="mt-2 text-sm text-slate-500">Nothing uploaded yet. No data is assumed or generated.</p>}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button onClick={() => void build()} disabled={building || !status || status.uploads.length === 0}
                  className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-5 py-2.5 text-sm font-bold text-white shadow-md hover:brightness-110 disabled:opacity-50">
            {building && <Loader2 size={16} className="animate-spin" />} BUILD RESEARCH DATASET
          </button>
          <span className="text-xs text-slate-500">PPG windows {status?.settings.window_s} s every {status?.settings.hop_s} s · a reference SaO₂ is paired with the nearest window within ±{status?.settings.match_tolerance_s} s.</span>
        </div>
      </section>

      {q && (
        <section className="card space-y-5 p-6" aria-label="Data quality report">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold text-navy-900">Data quality report</h2>
            <div className="flex flex-wrap gap-2">
              <Badge tone={q.readiness.status === "READY FOR TRAINING" ? "green" : "red"} dot>{q.readiness.status}</Badge>
              <Badge tone={rs ? STATUS_TONE[labelForState(rs.state)] : "amber"} dot>{rs ? labelForState(rs.state) : q.label}</Badge>
            </div>
          </div>
          {q.readiness.reasons.length > 0 && <ul className="list-disc pl-5 text-sm text-rose-800">{q.readiness.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
          {q.readiness.status === "READY FOR TRAINING" && <p className="text-xs text-slate-600">Every valid record has SpO₂, SaO₂, ITA, PI, participant ID and session ID. Training is still started manually on the Models page.</p>}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Tile label="Total records" value={q.total_records} />
            <Tile label="Valid" value={q.valid_records} tone="text-emerald-600" />
            <Tile label="Invalid" value={q.invalid_records} tone={q.invalid_records ? "text-amber-600" : undefined} />
            <Tile label="Participants" value={q.participants} sub="with valid records" />
            <Tile label="Sessions" value={q.sessions} sub="with valid records" />
            <Tile label="Matched" value={q.matching.matched_records} sub="SpO₂ ↔ SaO₂" />
            <Tile label="Missing SpO₂" value={q.missing_spo2} /><Tile label="Missing SaO₂" value={q.missing_sao2} /><Tile label="Missing ITA" value={q.missing_ita} />
            <Tile label="Missing PI" value={q.missing_pi} /><Tile label="Missing SQI" value={q.missing_sqi} /><Tile label="Missing motion" value={q.missing_motion} />
          </div>
          <div className="space-y-2" aria-label="Subgroup counts">
            <p className="text-xs text-slate-600">Devices: {q.devices.length ? `${q.devices.length} (${q.devices.join(", ")})` : "0"}. A group needs at least {q.subgroups.min_participants} participants and {q.subgroups.min_records} records; smaller groups are shown as INSUFFICIENT DATA, never balanced or filled in.</p>
            <div className="grid gap-3 md:grid-cols-3">
              {([["ITA group", q.subgroups.ita], ["PI group", q.subgroups.pi], ["ITA × PI", q.subgroups.cells]] as const).map(([title, rows]) => (
                <div key={title} className="rounded-xl bg-slate-50 p-3 text-xs">
                  <div className="mb-1 font-bold uppercase tracking-wide text-slate-500">{title}</div>
                  {rows.map((r) => (
                    <div key={r.label} className="flex justify-between gap-2 border-t border-slate-200 py-1">
                      <span className="font-semibold text-navy-900">{r.label}</span>
                      <span className={r.status === "OK" ? "text-slate-700" : "font-semibold text-amber-800"}>{r.records} rec · {r.participants} part.{r.status === "OK" ? "" : " · INSUFFICIENT DATA"}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-bold text-navy-900">Unmatched records <span className="font-normal text-slate-500">(kept and listed, never discarded)</span></h3>
            <div className="grid gap-3 lg:grid-cols-3">
              <List title="Unmatched PPG records" extra={report?.truncated.ppg ?? 0} rows={(report?.unmatched_ppg ?? []).map((r) => ({ label: `${r.participant_id} / ${r.session_id} @ ${r.timestamp}`, reason: r.reason }))} />
              <List title="Unmatched SaO₂ records" extra={report?.truncated.sao2 ?? 0} rows={(report?.unmatched_sao2 ?? []).map((r) => ({ label: `${r.participant_id} / ${r.session_id}${r.timestamp ? ` @ ${r.timestamp}` : ""} (SaO₂ ${r.sao2 || "—"})`, reason: r.reason }))} />
              <List title="Unmatched pigmentation records" extra={report?.truncated.pigmentation ?? 0} rows={(report?.unmatched_pigmentation ?? []).map((r) => ({ label: `${r.participant_id}${r.session_id ? ` / ${r.session_id}` : ""}`, reason: r.reason }))} />
            </div>
            <p className="mt-2 text-xs text-slate-500">Counts: PPG {q.unmatched.ppg_records} · SaO₂ {q.unmatched.sao2_records} · pigmentation {q.unmatched.pigmentation_records}.</p>
          </div>
          {Object.keys(q.invalid_reasons).length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-bold text-navy-900">Why records are invalid</h3>
              <table className="w-full max-w-2xl text-sm"><tbody className="divide-y divide-slate-100">
                {Object.entries(q.invalid_reasons).map(([k, v]) => <tr key={k}><td className="py-1.5 text-slate-600">{k}</td><td className="py-1.5 text-right font-mono font-semibold">{v}</td></tr>)}
              </tbody></table>
            </div>
          )}
          <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
            <div className="font-bold text-navy-900">Model training: {q.model_training.blocked ? "BLOCKED" : "not blocked by data volume"}</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">{q.model_training.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            <p className="mt-2 text-xs text-slate-500">Outputs: <code>data/processed/research_dataset.csv</code>, <code>research_dataset_invalid.csv</code>, <code>research_data_quality.json</code>, <code>merge_report.json</code>. Next: validate and split on the <a href="#dataset" className="font-semibold text-indigo-600 underline">Dataset</a> page.</p>
          </div>
        </section>
      )}
    </div>
  );
}
