import { useRef, useState, type ReactNode } from "react";
import { Loader2, Plus, TriangleAlert, Trash2, Upload } from "lucide-react";
import { Badge, Term } from "../components/ui";
import { ValidationFailed, type FieldError } from "../lib/reliabilityApi";
import {
  LOCATIONS, NOT_SPECIFIED, parseLabCsv, summarizeParticipant,
  type CsvGroup, type Group, type LabRow, type Measurement, type PigmentResult, type PigmentSummary,
} from "../lib/pigmentApi";

interface Entry { id: string; rows: LabRow[]; res?: PigmentResult; errors?: FieldError[]; failure?: string }

const EMPTY_ROW: LabRow = { L: "", a: "", b: "", location: NOT_SPECIFIED };   // nothing is pre-filled or assumed
const GROUP_STYLE: Record<Group, string> = {
  Light: "bg-indigo-100 text-indigo-800", Medium: "bg-indigo-300 text-indigo-950", Dark: "bg-indigo-900 text-white",
};

/** ITA gauge over a fixed display range; cut-offs come from the backend configuration. */
function Gauge({ res }: { res: PigmentResult }) {
  const MIN = -60, MAX = 70;
  const { dark_at_most: d, light_above: l } = res.thresholds;
  const pos = (v: number) => `${((Math.min(MAX, Math.max(MIN, v)) - MIN) / (MAX - MIN)) * 100}%`;
  const w = (a: number, b: number) => `${((b - a) / (MAX - MIN)) * 100}%`;
  const med = res.median_ita;
  const off = (v: number) => v < MIN || v > MAX;
  return (
    <div role="img" aria-label={med !== null ? `ITA ${med} degrees, ${res.pigmentation_group} objective pigmentation` : "ITA gauge"}>
      <div className="relative h-5 overflow-hidden rounded-full">
        <div className="absolute inset-y-0 bg-indigo-900" style={{ left: 0, width: w(MIN, d) }} />
        <div className="absolute inset-y-0 bg-indigo-400" style={{ left: pos(d), width: w(d, l) }} />
        <div className="absolute inset-y-0 bg-indigo-100" style={{ left: pos(l), width: w(l, MAX) }} />
      </div>
      <div className="relative -mt-7 h-9">
        {res.measurements.map((m) => (
          <span key={m.index} title={`Measurement ${m.index}: ${m.ita}°`}
                className="absolute top-2.5 h-3 w-0.5 -translate-x-1/2 rounded bg-white ring-1 ring-navy-900/40" style={{ left: pos(m.ita) }} />
        ))}
        {med !== null && (
          <span className="absolute -top-0.5 h-8 w-1.5 -translate-x-1/2 rounded bg-white shadow ring-2 ring-navy-900 transition-all duration-300" style={{ left: pos(med) }} />
        )}
      </div>
      <div className="relative mt-1 h-10 text-[11px] text-slate-500">
        <span className="absolute left-0">{MIN}°</span>
        <span className="absolute -translate-x-1/2 text-center" style={{ left: pos(d) }}>{d}°</span>
        <span className="absolute -translate-x-1/2 text-center" style={{ left: pos(l) }}>{l}°</span>
        <span className="absolute right-0">{MAX}°</span>
        <span className="absolute top-4 -translate-x-1/2 font-semibold" style={{ left: `${(((MIN + d) / 2 - MIN) / (MAX - MIN)) * 100}%` }}>DARK</span>
        <span className="absolute top-4 -translate-x-1/2 font-semibold" style={{ left: `${(((d + l) / 2 - MIN) / (MAX - MIN)) * 100}%` }}>MEDIUM</span>
        <span className="absolute top-4 -translate-x-1/2 font-semibold" style={{ left: `${(((l + MAX) / 2 - MIN) / (MAX - MIN)) * 100}%` }}>LIGHT</span>
      </div>
      {(med !== null && off(med)) && <p className="text-[11px] text-amber-700">Value is beyond the displayed range ({MIN}° to {MAX}°); the marker is pinned to the edge.</p>}
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

function Detail({ e, onLocation }: { e: Entry; onLocation: (loc: string) => void }) {
  const r = e.res!;
  const single = r.n_used === 1 && !r.mixed_locations;
  const first: Measurement = r.measurements[0];
  return (
    <div className="space-y-5">
      <section className="card p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {r.n_used > 1 ? <Term label="Median ITA" tip="With repeated measurements the participant-level value is the median of the per-measurement ITA values." /> : "ITA"}
              {e.id !== "Manual entry" && <span className="ml-2 normal-case text-slate-400">· {e.id}</span>}
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-5xl font-extrabold text-navy-900">{r.median_ita !== null ? r.median_ita.toFixed(1) : "—"}</span>
              <span className="text-lg font-medium text-slate-400">°</span>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {r.n_used} measurement{r.n_used > 1 ? "s" : ""} · location: {r.location ?? "mixed — select one"}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Objective pigmentation</div>
            <span className={`mt-1 inline-block rounded-xl px-4 py-2 text-xl font-extrabold tracking-wide ${r.pigmentation_group ? GROUP_STYLE[r.pigmentation_group] : "bg-slate-100 text-slate-500"}`}>
              {r.pigmentation_group?.toUpperCase() ?? "NOT DETERMINED"}
            </span>
          </div>
        </div>
        <div className="mt-6"><Gauge res={r} /></div>
        <p className="mt-3 text-xs font-semibold text-indigo-800">{r.label}</p>
      </section>

      {single && (
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Measured values">
          <Tile label="L*" value={first.L} sub="lightness" />
          <Tile label="a*" value={first.a} sub="green–red" />
          <Tile label="b*" value={first.b} sub="blue–yellow" />
          <Tile label="ITA" value={`${first.ita.toFixed(1)}°`} sub={first.pigmentation_group.toUpperCase()} />
        </section>
      )}

      {r.mixed_locations && (
        <section className="card border-amber-200 p-6">
          <h3 className="font-bold text-navy-900">Measurements from different locations</h3>
          <p className="mt-1 text-sm text-slate-600">Locations are not interchangeable, so they are not combined. Choose the location to use as the participant-level value.</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {Object.entries(r.by_location).map(([loc, v]) => (
              <div key={loc} className="rounded-xl bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase text-slate-500">{loc} · n = {v.n}</div>
                <div className="mt-1 font-bold text-navy-900">Median ITA {v.median_ita.toFixed(1)}° · {v.pigmentation_group.toUpperCase()}</div>
                <button onClick={() => onLocation(loc)} className="mt-2 text-xs font-bold text-indigo-600 underline">Use this location</button>
              </div>
            ))}
          </div>
        </section>
      )}

      {r.n > 1 && (
        <section className="card overflow-x-auto p-6">
          <h3 className="mb-3 font-bold text-navy-900">Individual measurements</h3>
          <table className="w-full min-w-[480px] text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr><th className="pb-2">#</th><th>L*</th><th>a*</th><th>b*</th><th>ITA</th><th>Category</th><th>Location</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {r.measurements.map((m) => (
                <tr key={m.index} className={r.location && m.location !== r.location ? "text-slate-400" : ""}>
                  <td className="py-2">{m.index}</td><td>{m.L}</td><td>{m.a}</td><td>{m.b}</td>
                  <td className="font-semibold">{m.ita.toFixed(1)}°</td><td>{m.pigmentation_group.toUpperCase()}</td><td>{m.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">Participant-level ITA is the median of these values{r.location ? ` (location: ${r.location})` : ""}.</p>
        </section>
      )}

      {(r.warnings.length > 0 || r.measurements.some((m) => m.warnings.length)) && (
        <section className="card border-amber-200 p-5" role="status">
          <h3 className="flex items-center gap-2 text-sm font-bold text-amber-800"><TriangleAlert size={16} /> Check these</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">
            {[...r.warnings, ...r.measurements.flatMap((m) => m.warnings.map((w) => `Measurement ${m.index}: ${w}`))].map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}

const field = (bad: boolean) =>
  `w-full rounded-lg border bg-white px-2.5 py-2 text-sm font-medium text-navy-900 outline-none focus:ring-2 ${bad ? "border-rose-300 focus:ring-rose-200" : "border-slate-200 focus:border-indigo-400 focus:ring-indigo-100"}`;

export default function Pigmentation({ onSummary, embedded = false }: { onSummary: (s: PigmentSummary | null) => void; embedded?: boolean }) {
  const [mode, setMode] = useState<"manual" | "csv">("manual");
  const [rows, setRows] = useState<LabRow[]>([EMPTY_ROW]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(false);
  const [csvNote, setCsvNote] = useState("");
  const [general, setGeneral] = useState("");
  const [filters, setFilters] = useState<Record<string, string | null>>({});
  const fileRef = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  async function compute(groups: CsvGroup[], flt: Record<string, string | null>, sel = 0) {
    const id = ++seq.current;
    setLoading(true); setGeneral("");
    const out: Entry[] = await Promise.all(groups.map(async (g) => {
      try {
        return { ...g, res: await summarizeParticipant(g.rows, flt[g.id] ?? null) };
      } catch (e) {
        return e instanceof ValidationFailed ? { ...g, errors: e.errors } : { ...g, failure: (e as Error).message };
      }
    }));
    if (id !== seq.current) return;
    setEntries(out); setSelected(Math.min(sel, out.length - 1)); setLoading(false);
    publish(out[Math.min(sel, out.length - 1)]);
  }

  /** Send the selected participant to the Live Reliability Check — only when a single usable ITA exists. */
  function publish(e: Entry | undefined) {
    const r = e?.res;
    if (r && r.median_ita !== null && r.pigmentation_group && r.usable_for_reliability) {
      onSummary({ ita: r.median_ita, group: r.pigmentation_group, n: r.n_used, location: r.location ?? NOT_SPECIFIED,
        source: e!.id === "Manual entry" ? "manual L*a*b* entry" : `CSV: ${e!.id}` });
    } else onSummary(null);
  }


  const setRow = (i: number, k: keyof LabRow, v: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  async function onFile(file: File | undefined) {
    if (!file) return;
    try {
      const groups = parseLabCsv(await file.text());
      setCsvNote(`Read ${groups.reduce((n, g) => n + g.rows.length, 0)} measurement(s) for ${groups.length} participant(s) from ${file.name}.`);
      setFilters({});
      await compute(groups, {});
    } catch (e) {
      setCsvNote(""); setEntries([]); onSummary(null); setGeneral((e as Error).message);
    }
  }

  function pick(i: number) { setSelected(i); publish(entries[i]); }

  async function chooseLocation(loc: string) {
    const e = entries[selected];
    const next = { ...filters, [e.id]: loc };
    setFilters(next);
    await compute(entries.map(({ id, rows: rs }) => ({ id, rows: rs })), next, selected);
  }

  const cur = entries[selected];
  const errFor = (i: number, k: string) => cur?.errors?.find((e) => e.field === `measurements[${i}].${k}`)?.message;

  return (
    <div className="space-y-6">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          <Badge tone="indigo">Objective pigmentation — not race</Badge>
        </div>
        {embedded ? <h2 className="text-xl font-bold text-navy-900">Objective Pigmentation</h2> : <h1 className="text-3xl font-extrabold tracking-tight text-navy-900 sm:text-4xl">Objective Pigmentation</h1>}
        <p className="mt-2 max-w-2xl text-slate-600">Measure pigmentation objectively instead of using race as a model input.</p>
      </header>

      <div className="grid items-start gap-6 xl:grid-cols-[420px_1fr]">
        <div className="card space-y-4 p-6 xl:sticky xl:top-24">
          <div role="group" aria-label="Input method" className="inline-grid grid-flow-col auto-cols-fr gap-1 rounded-xl bg-slate-100 p-1">
            {([["manual", "Manual entry"], ["csv", "Upload CSV"]] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={mode === id} onClick={() => setMode(id)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-bold ${mode === id ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500"}`}>{label}</button>
            ))}
          </div>

          {mode === "manual" ? (
            <form onSubmit={(e) => { e.preventDefault(); compute([{ id: "Manual entry", rows }], {}); }} noValidate className="space-y-3">
              <p className="text-xs text-slate-500">Enter one row per measurement of the same participant. With several rows the <strong>median ITA</strong> is used.</p>
              {rows.map((r, i) => (
                <div key={i} className="rounded-xl bg-slate-50 p-3">
                  <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                    Measurement {i + 1}
                    {rows.length > 1 && <button type="button" aria-label={`Remove measurement ${i + 1}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} className="text-slate-400 hover:text-rose-600"><Trash2 size={14} /></button>}
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {(["L", "a", "b"] as const).map((k) => (
                      <label key={k} className="block">
                        <span className="mb-1 block text-[11px] font-semibold text-slate-500">{k}*</span>
                        <input aria-label={`${k}* measurement ${i + 1}`} className={field(!!errFor(i, k))} inputMode="decimal" value={r[k]} onChange={(e) => setRow(i, k, e.target.value)} />
                      </label>
                    ))}
                  </div>
                  {(["L", "a", "b"] as const).map((k) => errFor(i, k) && <p key={k} role="alert" className="mt-1.5 text-xs font-semibold text-rose-600">{errFor(i, k)!.replace(/^Measurement \d+: /, "")}</p>)}
                  <label className="mt-2 block">
                    <span className="mb-1 block text-[11px] font-semibold text-slate-500">Measurement location (optional)</span>
                    <select className={field(false)} value={r.location} onChange={(e) => setRow(i, "location", e.target.value)}>
                      {[NOT_SPECIFIED, ...LOCATIONS].map((l) => <option key={l}>{l}</option>)}
                    </select>
                  </label>
                </div>
              ))}
              <button type="button" onClick={() => setRows((rs) => [...rs, { ...rs[rs.length - 1] }])}
                      className="flex items-center gap-1.5 text-xs font-bold text-indigo-600"><Plus size={14} /> Add repeated measurement</button>
              <button type="submit" disabled={loading}
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3 text-sm font-bold tracking-wide text-white shadow-md hover:brightness-110 disabled:opacity-60">
                {loading && <Loader2 size={16} className="animate-spin" />} CALCULATE ITA
              </button>
            </form>
          ) : (
            <div className="space-y-3">
              <input ref={fileRef} type="file" accept=".csv,.txt,text/csv" className="hidden" onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
              <button onClick={() => fileRef.current?.click()} className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:border-indigo-300 hover:text-indigo-700">
                <Upload size={16} /> Choose CSV file
              </button>
              <p className="text-xs text-slate-500">
                Columns: <code>participant_id</code> (optional), <code>L</code>, <code>a</code>, <code>b</code>, <code>location</code> (optional). Several rows with the same participant_id are treated as repeated measurements. Without a header: exactly three columns L, a, b. Later, hardware can supply these values.
              </p>
              {csvNote && <p className="text-xs font-semibold text-indigo-700">{csvNote}</p>}
            </div>
          )}
          <p className="text-[11px] leading-relaxed text-slate-400">Not a diagnostic device — not for medical diagnosis. Values are never replaced: missing or invalid entries are reported.</p>
        </div>

        <div aria-live="polite" className="min-w-0 space-y-6">
          {loading && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" /> Calculating…</div>}
          {!loading && entries.length === 0 && !general && (
            <div className="card grid place-items-center px-6 py-16 text-center text-sm text-slate-500">
              No measurement yet. Enter L*, a*, b* from your colorimeter (or upload a CSV) and press <strong className="mx-1 text-slate-700">Calculate ITA</strong>.
            </div>
          )}
          {general && <div className="card flex gap-3 border-rose-200 p-5 text-sm text-rose-800"><TriangleAlert size={18} className="shrink-0" /> {general}</div>}

          {entries.length > 1 && (
            <section className="card overflow-x-auto p-6">
              <h3 className="mb-3 font-bold text-navy-900">Participants ({entries.length})</h3>
              <table className="w-full min-w-[420px] text-sm">
                <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="pb-2">Participant</th><th>n</th><th>Median ITA</th><th>Objective pigmentation</th><th /></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {entries.map((e, i) => (
                    <tr key={e.id} className={i === selected ? "bg-indigo-50/60" : ""}>
                      <td className="py-2 font-semibold">{e.id}</td>
                      <td>{e.res?.n ?? "—"}</td>
                      <td>{e.res?.median_ita != null ? `${e.res.median_ita.toFixed(1)}°` : e.errors ? <span className="text-rose-600">invalid</span> : "—"}</td>
                      <td>{e.res?.pigmentation_group?.toUpperCase() ?? (e.res?.mixed_locations ? "choose location" : "—")}</td>
                      <td><button onClick={() => pick(i)} className="text-xs font-bold text-indigo-600 underline">{i === selected ? "Selected" : "View"}</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {cur?.failure && <div className="card flex gap-3 border-rose-200 p-5 text-sm text-rose-800"><TriangleAlert size={18} className="shrink-0" /> {cur.failure}</div>}
          {cur?.errors && (
            <div className="card border-rose-200 p-6">
              <h3 className="flex items-center gap-2 font-bold text-rose-700"><TriangleAlert size={18} /> Measurements cannot be used</h3>
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-rose-800">{cur.errors.map((e) => <li key={e.field + e.code}>{e.message}</li>)}</ul>
              <p className="mt-3 text-xs text-slate-500">Nothing was dropped or replaced. Fix the listed values and calculate again.</p>
            </div>
          )}
          {cur?.res && <Detail e={cur} onLocation={chooseLocation} />}

          {cur?.res && (
            <section className="card p-6">
              <h3 className="font-bold text-navy-900">Connection to the reliability assessment</h3>
              {cur.res.median_ita !== null && cur.res.usable_for_reliability ? (
                <p className="mt-2 text-sm text-slate-600">
                  ITA {cur.res.median_ita.toFixed(1)}° → <strong>{cur.res.pigmentation_group?.toUpperCase()}</strong> objective pigmentation →{" "}
                  now used by the <a href="#reliability" className="font-semibold text-indigo-600 underline">Live Reliability Check</a>.
                </p>
              ) : (
                <p className="mt-2 text-sm text-amber-800">No single usable ITA is available for the Live Reliability Check yet (see the notes above). It keeps using manual ITA entry.</p>
              )}
              <ol className="mt-4 flex flex-wrap items-center gap-x-1 gap-y-2 text-xs font-medium">
                {["L*, a*, b*", "ITA = arctan((L* − 50) / b*)", "Median per participant", "Objective category", "Reliability assessment"].map((s, i, a) => (
                  <li key={s} className="flex items-center gap-1"><span className="rounded-lg bg-indigo-50 px-2.5 py-1.5 text-indigo-700">{s}</span>{i < a.length - 1 && <span aria-hidden className="text-slate-300">→</span>}</li>
                ))}
              </ol>
            </section>
          )}

          <section className="card p-6">
            <h3 className="font-bold text-navy-900">What is ITA?</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              ITA (Individual Typology Angle) is an objective colorimetric descriptor derived from L*, a* and b* measurements:
            </p>
            <p className="my-3 rounded-xl bg-slate-50 px-4 py-3 font-mono text-sm text-navy-900">ITA = arctan((L* − 50) / b*) × 180 / π</p>
            <ul className="space-y-1.5 text-sm text-slate-600">
              <li>• <strong>Race and pigmentation are not equivalent.</strong> This system uses objective color measurement and never uses race or ethnicity as an input.</li>
              <li>• Higher ITA means lighter measured skin color. Configured cut-offs: Light above {cur?.res?.thresholds.light_above ?? 41}°, Dark at or below {cur?.res?.thresholds.dark_at_most ?? 10}°, Medium in between. These are not clinically validated.</li>
              <li>• This is the standard arctan form, range (−90°, 90°). b* = 0 gives +90° (L* &gt; 50) or −90° (L* &lt; 50); L* = 50 with b* = 0 is undefined and rejected.</li>
              <li>• Light / Medium / Dark are only labels for these configured ITA bands. They are not the standard ITA skin-tone categories, and “Dark” (ITA ≤ 10°) does not mean the darkest skin.</li>
              <li>• Location matters: measurements from different body sites are kept separate, not mixed.</li>
            </ul>
            <p className="mt-3 text-xs font-semibold text-indigo-800">Objective pigmentation category — not race or ethnicity.</p>
          </section>
        </div>
      </div>
    </div>
  );
}
