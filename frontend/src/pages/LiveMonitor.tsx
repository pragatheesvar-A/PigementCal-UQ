import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { CircleSlash, Circle, Download, Square, Loader2, Pause, Play, Plug, RotateCcw, TriangleAlert, Upload, Video, XCircle } from "lucide-react";
import { Badge, Term } from "../components/ui";
import { RingBuffer, parseRecording, recordingToCsv, toWindow, type Recording, type Sample } from "../lib/acquisition";
import { SessionRecorder, connectionLabel, serialErrorMessage } from "../lib/session";
import { CameraSource, ReplaySource, SerialSource, type Frame, type SerialPortLike } from "../lib/sources";
import { analyzeLive, type LiveResult } from "../lib/liveApi";
import { predict, ValidationFailed, type Assessment, type State } from "../lib/reliabilityApi";
import type { PigmentSummary } from "../lib/pigmentApi";
import type { SignalSummary } from "../lib/signalApi";
import { SCENARIOS, SCENARIO_IDS, VIRTUAL_BANNER, VIRTUAL_DEVICE, VIRTUAL_META, VirtualSerialPort, paramsFor, type MotionLevel, type NoiseLevel, type ScenarioId } from "../lib/virtualSensor";

type SourceId = "esp32" | "virtual" | "camera" | "file";
type Phase = "idle" | "connecting" | "streaming" | "paused" | "ended" | "error";

interface LiveConfig {
  window_seconds: number; min_window_seconds: number; analysis_interval_s: number;
  invert_default: Record<SourceId, boolean>;
}
const DEFAULT_CFG: LiveConfig = { window_seconds: 10, min_window_seconds: 6, analysis_interval_s: 1, invert_default: { esp32: true, virtual: true, camera: true, file: false } };
const DEVICE: Record<SourceId, string> = { esp32: "ESP32 + MAX30102", virtual: VIRTUAL_DEVICE, camera: "Phone camera", file: "Recorded file" };
const Q_TEXT = { GOOD: "text-emerald-600", MODERATE: "text-amber-600", POOR: "text-rose-600" } as const;
const REL_TEXT: Record<State, string> = { GREEN: "text-emerald-600", AMBER: "text-amber-600", RED: "text-rose-600", ABSTAIN: "text-slate-600" };
const SEV: Record<string, string> = { info: "bg-emerald-500", warning: "bg-amber-500", critical: "bg-rose-500" };

const serialApi = () => (navigator as unknown as { serial?: { requestPort(): Promise<SerialPortLike> } }).serial;

function Metric({ label, value, sub, tone }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="card p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${tone ?? "text-navy-900"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function Seg<T extends string>({ value, options, onChange, disabled }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div role="group" className="inline-grid grid-flow-col auto-cols-fr gap-1 rounded-xl bg-slate-100 p-1">
      {options.map((o) => (
        <button key={o.id} type="button" disabled={disabled} aria-pressed={value === o.id} onClick={() => onChange(o.id)}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-all disabled:opacity-60 ${value === o.id ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>{o.label}</button>
      ))}
    </div>
  );
}

const btn = "flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold disabled:opacity-50";
const btnPrimary = `${btn} bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-md hover:brightness-110`;
const btnGhost = `${btn} border border-slate-200 bg-white text-slate-700 hover:border-indigo-300 hover:text-indigo-700`;

export default function LiveMonitor({ pigment, onSummary }: { pigment: PigmentSummary | null; onSummary: (s: SignalSummary | null) => void }) {
  const [cfg, setCfg] = useState<LiveConfig>(DEFAULT_CFG);
  const [source, setSource] = useState<SourceId>("esp32");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [result, setResult] = useState<LiveResult | null>(null);
  const [collecting, setCollecting] = useState<string>("");
  const [analysisError, setAnalysisError] = useState("");
  const [chart, setChart] = useState<{ t: number; y: number }[]>([]);
  const [stats, setStats] = useState({ rate: null as number | null, samples: 0, seconds: 0 });
  // source specific UI
  const [baud, setBaud] = useState(115200);
  const [vScenario, setVScenario] = useState<ScenarioId>("normal");
  const [vHr, setVHr] = useState("72");
  const [vNoise, setVNoise] = useState<NoiseLevel>("low");
  const [vMotion, setVMotion] = useState<MotionLevel>("none");
  const [vSeed, setVSeed] = useState("42");
  const [serialInfo, setSerialInfo] = useState({ lines: 0, rejected: 0, recent: [] as string[], lastError: "" });
  const [frame, setFrame] = useState<Frame | null>(null);
  const [recording, setRecording] = useState<{ rec: Recording; name: string } | null>(null);
  const [fsText, setFsText] = useState("");
  const [progress, setProgress] = useState(0);
  // reliability inputs not supplied by the sensor
  const [itaText, setItaText] = useState("");
  const [spo2Text, setSpo2Text] = useState("");
  const [rel, setRel] = useState<Assessment | null>(null);
  // ESP32 recording session (anonymous IDs only)
  const [participantId, setParticipantId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [sessionMsg, setSessionMsg] = useState("");
  const [wasConnected, setWasConnected] = useState(false);
  const [lastSample, setLastSample] = useState<Sample | null>(null);
  const [dataAge, setDataAge] = useState<number | null>(null);
  const [sess, setSess] = useState({ state: "idle" as "idle" | "recording" | "stopped", samples: 0, duration: 0, dropped: 0 });
  const recorder = useRef(new SessionRecorder());
  const [relMsg, setRelMsg] = useState("");

  const ring = useRef(new RingBuffer(30));
  const all = useRef<Sample[]>([]);
  const srcRef = useRef<SerialSource | CameraSource | ReplaySource | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const inflight = useRef(false);
  const cfgRef = useRef(cfg);
  cfgRef.current = cfg;
  const sourceRef = useRef(source);
  sourceRef.current = source;

  useEffect(() => { fetch("/api/live/config").then((r) => r.json()).then(setCfg).catch(() => { /* defaults */ }); }, []);

  const push = useCallback((batch: Sample[]) => {
    ring.current.push(batch);
    if (all.current.length < 120000) all.current.push(...batch);
    recorder.current.add(batch);
    setLastSample(batch[batch.length - 1]);
  }, []);

  const halt = useCallback(async (next: Phase = "idle") => {
    const s = srcRef.current;
    srcRef.current = null;
    try { if (s instanceof SerialSource) await s.stop(); else s?.stop(); } catch { /* already stopped */ }
    setPhase(next);
    onSummary(null);                 // stale live values must not feed other pages
  }, [onSummary]);

  useEffect(() => () => { void halt(); }, [halt]);

  function resetSession() {
    ring.current.clear(); all.current = []; setLastSample(null); setDataAge(null);
    setResult(null); setRel(null); setRelMsg(""); setCollecting(""); setAnalysisError(""); setChart([]); setProgress(0);
    setStats({ rate: null, samples: 0, seconds: 0 });
  }

  // ---------------------------------------------------------------- starting each source
  async function connectSerial() {
    const api = serialApi();
    if (!api) { setError("Web Serial is not available in this browser. Use Chrome or Edge on desktop (HTTPS or localhost)."); setPhase("error"); return; }
    setError(""); setNotice(""); resetSession(); setPhase("connecting");
    try {
      await openSerial(await api.requestPort(), baud);
    } catch (e) {
      srcRef.current = null;
      const err = e as Error;
      if (err.name === "NotFoundError") setNotice("No port was selected. Choose your sensor's port to connect.");
      else setError(serialErrorMessage(err));
      setPhase(err.name === "NotFoundError" ? "idle" : "error");
    }
  }

  /** Virtual MAX30102: a software port that goes through the SAME SerialSource / parser / buffer / recorder / analysis as a real board. */
  async function startVirtual() {
    const hr = Number(vHr), seed = Number(vSeed);
    if (!Number.isFinite(hr) || hr < 30 || hr > 220) { setError("Heart rate must be between 30 and 220 BPM."); setPhase("error"); return; }
    if (!Number.isInteger(seed) || seed < 0) { setError("Seed must be a whole number (0 or more)."); setPhase("error"); return; }
    setError(""); setNotice(""); resetSession(); setPhase("connecting");
    try { await openSerial(new VirtualSerialPort(paramsFor(vScenario, { hr, noise: vNoise, motion: vMotion, seed }), { autoRun: true }), 115200); }
    catch (e) { srcRef.current = null; setError((e as Error).message); setPhase("error"); }
  }
  function pickScenario(id: ScenarioId) { const sc = SCENARIOS[id]; setVScenario(id); setVHr(String(sc.hr)); setVNoise(sc.noise); setVMotion(sc.motion); }

  async function openSerial(port: SerialPortLike, baudRate: number) {
    {
      let closed = false;                       // the stream may end before start() even returns (port busy, unplugged)
      const src = new SerialSource(port, baudRate, {
        onSamples: push,
        onError: (e) => { setError(`Serial connection lost: ${e.message}. Reconnect the sensor${recorder.current.state === "recording" ? "; the samples recorded so far are kept and can still be saved" : ""}.`); recorder.current.stop(); void halt("error"); },
        onClosed: () => { closed = true; if (recorder.current.state === "recording") { recorder.current.stop(); setSessionMsg("The sensor disconnected, so the session was stopped. The samples recorded so far can still be saved."); } setPhase((p) => (p === "streaming" || p === "connecting" ? "idle" : p)); onSummary(null); },
      });
      srcRef.current = src;
      await src.start();
      await new Promise((r) => setTimeout(r, 250));      // give an immediately-closing port a moment to report it
      if (closed) { srcRef.current = null; setError("The serial port closed immediately. Check that the device is connected and that no other program (e.g. the Arduino Serial Monitor) is using it."); setPhase("error"); }
      else { setWasConnected(true); setPhase("streaming"); }
    }
  }

  async function startCamera() {
    if (!videoRef.current) return;
    setError(""); resetSession(); setPhase("connecting");
    try {
      const src = new CameraSource(videoRef.current, {
        onSamples: push, onFrame: setFrame,
        onError: (e) => { setError(e.message); void halt("error"); },
      });
      srcRef.current = src;
      await src.start();
      setPhase("streaming");
    } catch (e) {
      srcRef.current = null;
      const err = e as Error;
      setError(err.name === "NotAllowedError" ? "Camera permission was denied." : `Could not start the camera: ${err.message}`);
      setPhase("error");
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError("");
    try {
      const rec = parseRecording(await file.text());
      setRecording({ rec, name: file.name });
      setFsText(rec.fs ? String(rec.fs) : "");
    } catch (e) { setRecording(null); setError((e as Error).message); }
  }

  const fsNum = Number(fsText);
  const fsValid = fsText.trim() !== "" && Number.isFinite(fsNum) && fsNum >= 20 && fsNum <= 1000;

  function startReplay() {
    if (!recording || !fsValid) return;
    setError(""); resetSession();
    const src = new ReplaySource(recording.rec, fsNum, {
      onSamples: (b) => { push(b); setProgress(src.progress); },
      onError: (e) => setError(e.message),
      onEnd: () => setPhase("ended"),
    });
    srcRef.current = src;
    src.play();
    setPhase("streaming");
  }

  function togglePause() {
    const s = srcRef.current;
    if (!(s instanceof ReplaySource)) return;
    if (s.playing) { s.pause(); setPhase("paused"); } else { s.play(); setPhase("streaming"); }
  }

  // ---------------------------------------------------------------- display + analysis loops
  useEffect(() => {
    if (phase !== "streaming" && phase !== "paused" && phase !== "ended") return;
    const invert = cfgRef.current.invert_default[sourceRef.current];
    const t = window.setInterval(() => {
      const w = ring.current.last(8);
      if (w.length < 2) return;
      const mean = w.reduce((a, b) => a + b.ir, 0) / w.length;
      const step = Math.max(1, Math.floor(w.length / 600));
      setChart(w.filter((_, i) => i % step === 0).map((x) => ({ t: Number(x.t.toFixed(3)), y: invert ? -(x.ir - mean) : x.ir - mean })));
      setStats({ rate: ring.current.rate, samples: all.current.length, seconds: ring.current.seconds });
      const s = srcRef.current;
      if (s instanceof SerialSource) {
        setSerialInfo({ lines: s.lines, rejected: s.rejected, recent: [...s.recent], lastError: s.lastError });
        setDataAge(s.lastDataAt === null ? null : performance.now() - s.lastDataAt);
      }
      const r = recorder.current;
      setSess({ state: r.state, samples: r.samples, duration: r.duration, dropped: r.dropped });
    }, 150);
    return () => window.clearInterval(t);
  }, [phase]);

  useEffect(() => {
    if (phase !== "streaming" && phase !== "ended") return;
    const run = async () => {
      if (inflight.current) return;
      const c = cfgRef.current;
      const win = ring.current.last(c.window_seconds);
      if (win.length < 10) return;
      inflight.current = true;
      try {
        const r = await analyzeLive(toWindow(win, sourceRef.current));
        setAnalysisError("");
        if (r.status === "collecting") { setCollecting(`Collecting signal: ${r.seconds_collected.toFixed(1)} s of ${r.seconds_needed} s needed…`); return; }
        setCollecting(""); setResult(r);
        onSummary({
          signal_quality: r.signal_quality, motion_state: r.motion_state, sqi: r.sqi, motion_score: r.motion_score, source: `Live ${DEVICE[sourceRef.current]}`,
          pi_estimate: r.pi_estimate, perfusion_state: r.pi_estimate === null ? null : r.pi_estimate < 1 ? "LOW" : "NORMAL",
          ac_ir: r.ac_ir, dc_ir: r.dc_ir, spo2_estimate: r.spo2.estimate, device: r.device, live: true,
        });
      } catch (e) {
        if (e instanceof ValidationFailed) setAnalysisError(e.errors.map((x) => x.message).join(" "));
        else setAnalysisError((e as Error).message);
      } finally { inflight.current = false; }
    };
    const t = window.setInterval(run, cfgRef.current.analysis_interval_s * 1000);
    void run();
    return () => window.clearInterval(t);
  }, [phase, onSummary]);

  // ---------------------------------------------------------------- reliability from live values
  const ita = pigment ? pigment.ita : itaText.trim() === "" ? null : Number(itaText);
  const manualSpo2 = spo2Text.trim() === "" ? null : Number(spo2Text);
  const spo2 = result?.spo2.estimate ?? manualSpo2;
  const abstainNow = result ? result.reliability_impact.state_hint === "ABSTAIN" : false;

  useEffect(() => {
    if (!result) { setRel(null); setRelMsg(""); return; }
    if (abstainNow) { setRel(null); setRelMsg(""); return; }        // the engine abstains; no inputs are needed to say so
    const missing: string[] = [];
    if (ita === null || !Number.isFinite(ita)) missing.push("objective pigmentation (ITA)");
    if (spo2 === null || !Number.isFinite(spo2)) missing.push(result.spo2.available ? "SpO₂" : "the SpO₂ reading to assess");
    if (result.pi_estimate === null) missing.push("a PI estimate");
    if (missing.length) { setRel(null); setRelMsg(`Needed for a reliability assessment: ${missing.join(", ")}.`); return; }
    let cancelled = false;
    predict({ spo2, pi: result.pi_estimate, ita, signal_quality: result.signal_quality, motion: result.motion_state, device: result.device,
              sqi: result.sqi, signal_source: "signal_module", pi_source: "ppg", ita_source: pigment ? "pigmentation_module" : "manual" })
      .then((a) => { if (!cancelled) { setRel(a); setRelMsg(""); } })
      .catch((e) => { if (!cancelled) { setRel(null); setRelMsg(e instanceof ValidationFailed ? e.errors.map((x) => x.message).join(" ") : (e as Error).message); } });
    return () => { cancelled = true; };
  }, [result, abstainNow, ita, spo2, pigment]);

  function startSession() {
    const msg = recorder.current.start(participantId, sessionId, source === "virtual" ? { ...VIRTUAL_META, scenario: vScenario, seed: vSeed } : null);
    setSessionMsg(msg ?? "");
    setSess({ state: recorder.current.state, samples: 0, duration: 0, dropped: 0 });
  }
  function stopSession() { recorder.current.stop(); setSess((x) => ({ ...x, state: "stopped" })); }
  function saveSessionCsv() {
    const r = recorder.current;
    if (!r.hasData) { setSessionMsg("Nothing to save yet: record at least one sample."); return; }
    const url = URL.createObjectURL(new Blob([r.toCsv()], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = r.fileName(); a.click();
    URL.revokeObjectURL(url);
  }

  function downloadRecording() {
    const rows = all.current;
    if (!rows.length) return;
    const { csv, fileStem } = recordingToCsv(rows, source === "esp32" || source === "virtual" ? source : source === "camera" ? "camera" : "file");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = `${fileStem}_${new Date().toISOString().replace(/[:.]/g, "-")}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  const live = phase === "streaming" || phase === "paused" || phase === "ended";
  const chartDomain = useMemo(() => (chart.length ? [chart[0].t, chart[chart.length - 1].t] : [0, 1]), [chart]);
  const noSerial = typeof navigator !== "undefined" && !serialApi();
  const conn = connectionLabel({ supported: !noSerial || source === "virtual", connected: live && (source === "esp32" || source === "virtual"), wasConnected, lastDataAgeMs: dataAge });
  const CONN_TONE = { CONNECTED: "green", DISCONNECTED: "slate", "RECONNECT REQUIRED": "amber", "UNSUPPORTED BROWSER": "red" } as const;
  const stalled = conn.label === "CONNECTED" && conn.note.startsWith("The sensor stopped");
  const lab = "text-[11px] font-semibold uppercase text-slate-500";
  const inp = "mt-1 block rounded-lg border border-slate-300 px-3 py-1.5 text-sm";
  const sensorPanel = (
    <div className="space-y-3 rounded-xl bg-slate-50 p-4" aria-label="Live sensor status">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={CONN_TONE[conn.label]} dot>{conn.label}</Badge>
        <span className={`text-xs ${stalled ? "font-semibold text-amber-800" : "text-slate-600"}`}>{conn.note}</span>
      </div>
      {live && (source === "esp32" || source === "virtual") && (
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div><div className={lab}>IR</div><div className="font-bold text-navy-900">{lastSample ? lastSample.ir : "—"}</div></div>
          <div><div className={lab}>Red</div><div className="font-bold text-navy-900">{lastSample?.red ?? "—"}</div></div>
          <div><div className={lab}>Samples received</div><div className="font-bold text-navy-900">{serialInfo.lines}</div></div>
          <div><div className={lab}>Rejected packets</div><div className="font-bold text-navy-900">{serialInfo.rejected}</div></div>
        </div>
      )}
      {serialInfo.lastError && live && <p className="text-xs text-amber-800">Last rejected packet: {serialInfo.lastError}.</p>}
      <div className="space-y-2 border-t border-slate-200 pt-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recording session (anonymous IDs only: no names, phone numbers or addresses)</div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block text-xs text-slate-600">Participant ID
            <input value={participantId} disabled={sess.state === "recording"} onChange={(e) => setParticipantId(e.target.value)} placeholder="P001" aria-label="Participant ID" className={`${inp} w-32`} />
          </label>
          <label className="block text-xs text-slate-600">Session ID
            <input value={sessionId} disabled={sess.state === "recording"} onChange={(e) => setSessionId(e.target.value)} placeholder="P001_S01" aria-label="Session ID" className={`${inp} w-36`} />
          </label>
          <button onClick={startSession} disabled={!live || (source !== "esp32" && source !== "virtual") || sess.state === "recording"} className={btnPrimary}><Circle size={14} /> Start session</button>
          <button onClick={stopSession} disabled={sess.state !== "recording"} className={btnGhost}><Square size={14} /> Stop session</button>
          <button onClick={saveSessionCsv} disabled={sess.samples === 0} className={btnGhost}><Download size={14} /> Save session CSV</button>
        </div>
        {sess.state === "recording" && <p className="text-sm font-bold text-rose-700">● LIVE RECORDING · Samples: {sess.samples} · Duration: {sess.duration.toFixed(0)} seconds · Sensor: {DEVICE[source === "virtual" ? "virtual" : "esp32"]}</p>}
        {sess.state === "stopped" && <p className="text-sm text-slate-700">Session stopped · Samples: {sess.samples} · Duration: {sess.duration.toFixed(0)} s. Save the CSV, then add the reference SaO₂ and ITA in Data Collection.</p>}
        {sess.dropped > 0 && <p className="text-xs text-amber-800">{sess.dropped} duplicate or out-of-order sample(s) were not recorded.</p>}
        {!live && sess.state === "idle" && <p className="text-xs text-slate-500">Connect the sensor to start a session.</p>}
        {sessionMsg && <p role="alert" className="text-xs font-semibold text-rose-700">{sessionMsg}</p>}
        <p className="text-xs text-slate-500">The CSV holds only what the sensor measured. SaO₂ and ITA are never added automatically; they come from real reference measurements.</p>
      </div>
      <p className="text-xs font-semibold text-amber-900">Not a medical device. Do not use for diagnosis. The MAX30102 is not claimed to be clinically accurate.</p>
    </div>
  );
  const fingerHint = frame ? (frame.r > 120 && frame.g < frame.r * 0.7 ? "Finger detected" : "Cover the lens (and flash) completely with a fingertip") : "";

  return (
    <div className="space-y-6">
      <header>
        <div className="mb-3 flex flex-wrap gap-2">
          {live && <Badge tone="green" dot>{phase === "ended" ? "Recording finished" : phase === "paused" ? "Paused" : "Live"} · {DEVICE[source]}</Badge>}
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight text-navy-900 sm:text-4xl">Live Monitor</h1>
        <p className="mt-2 max-w-2xl text-slate-600">
          Stream a real sensor signal and see, second by second, how much the reading can be trusted: signal quality, perfusion, motion and a reliability state.
        </p>
      </header>

      <section className="card space-y-4 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Seg value={source} disabled={live || phase === "connecting"} onChange={(s) => { setSource(s); setError(""); setPhase("idle"); resetSession(); }}
               options={[{ id: "esp32", label: "ESP32 + MAX30102" }, { id: "virtual", label: "Virtual MAX30102" }, { id: "camera", label: "Phone camera" }, { id: "file", label: "Replay recording" }]} />
          {live && <button onClick={() => void halt()} className={btnGhost}><XCircle size={16} /> {source === "esp32" ? "Disconnect" : source === "virtual" ? "Stop simulation" : "Stop"}</button>}
        </div>

        {source === "esp32" && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Baud rate</span>
                <select value={baud} disabled={live} onChange={(e) => setBaud(Number(e.target.value))} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium">
                  {[115200, 230400, 460800, 921600].map((b) => <option key={b}>{b}</option>)}
                </select>
              </label>
              <button onClick={connectSerial} disabled={live || phase === "connecting" || noSerial} className={btnPrimary}>
                {phase === "connecting" ? <Loader2 size={16} className="animate-spin" /> : <Plug size={16} />} Connect sensor
              </button>
            </div>
            <p className="text-xs text-slate-500">
              Flash <code>hardware/esp32_max30102/esp32_max30102.ino</code> to the ESP32, plug it in over USB, then choose its serial port. It streams
              <code> {'{"timestamp":ms,"red":n,"ir":n}'}</code> lines (one JSON object per line). Requires Chrome or Edge (Web Serial).
            </p>
            {sensorPanel}
            {live && (
              <p className="text-xs text-slate-600">
                Measured {stats.rate ? `${stats.rate.toFixed(1)} Hz` : "—"} · {serialInfo.lines} lines accepted · {serialInfo.rejected} rejected
                {serialInfo.recent.length > 0 && <span className="block truncate font-mono text-[11px] text-slate-400">last: {serialInfo.recent[serialInfo.recent.length - 1]}</span>}
              </p>
            )}
          </div>
        )}

        {source === "virtual" && (
          <div className="space-y-3">
            <div role="note" className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm font-bold text-amber-900">{VIRTUAL_BANNER}</div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="block text-xs text-slate-600">Scenario
                <select aria-label="Scenario" value={vScenario} disabled={live} onChange={(e) => pickScenario(e.target.value as ScenarioId)} className={`${inp} w-48`}>
                  {SCENARIO_IDS.map((id) => <option key={id} value={id}>{SCENARIOS[id].label}</option>)}
                </select>
              </label>
              <label className="block text-xs text-slate-600">Heart rate (BPM)
                <input aria-label="Heart rate" inputMode="numeric" value={vHr} disabled={live} onChange={(e) => setVHr(e.target.value)} className={`${inp} w-24`} />
              </label>
              <label className="block text-xs text-slate-600">Noise
                <select aria-label="Noise" value={vNoise} disabled={live} onChange={(e) => setVNoise(e.target.value as NoiseLevel)} className={`${inp} w-28`}>
                  <option value="low">Low</option><option value="intermediate">Intermediate</option><option value="medium">Medium</option><option value="high">High</option>
                </select>
              </label>
              <label className="block text-xs text-slate-600">Motion
                <select aria-label="Motion" value={vMotion} disabled={live} onChange={(e) => setVMotion(e.target.value as MotionLevel)} className={`${inp} w-32`}>
                  <option value="none">None</option><option value="moderate">Moderate</option><option value="high">High</option>
                </select>
              </label>
              <label className="block text-xs text-slate-600">Seed
                <input aria-label="Seed" inputMode="numeric" value={vSeed} disabled={live} onChange={(e) => setVSeed(e.target.value)} className={`${inp} w-24`} />
              </label>
              <button onClick={() => void startVirtual()} disabled={live || phase === "connecting"} className={btnPrimary}>
                {phase === "connecting" ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} Start simulation
              </button>
            </div>
            <p className="text-xs text-slate-500">
              A software ESP32 + MAX30102 (I²C 0x57, PART ID 0x15, FIFO, 100 Hz) produces raw RED/IR counts only, one JSON line per sample, through the same
              path as a real board. PI, SQI, SpO₂ and the reliability state are computed by the app from those counts; the simulator never sets them.
              Physical ESP32: not connected · Physical MAX30102: not connected · COM port: not available · Physical hardware validation: NOT TESTED.
              Virtual hardware integration is a software test only. Recorded files are marked <code>dataset_type=virtual_hardware_simulation</code> and
              <code> not_for_research_validation</code>, and cannot be uploaded as research data.
            </p>
            {sensorPanel}
            {live && (
              <p className="text-xs text-slate-600">
                Measured {stats.rate ? `${stats.rate.toFixed(1)} Hz` : "—"} · {serialInfo.lines} lines accepted · {serialInfo.rejected} rejected
              </p>
            )}
          </div>
        )}

        {source === "camera" && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-4">
              <button onClick={startCamera} disabled={live || phase === "connecting"} className={btnPrimary}>
                {phase === "connecting" ? <Loader2 size={16} className="animate-spin" /> : <Video size={16} />} Start camera
              </button>
              <video ref={videoRef} playsInline muted className={`h-20 w-28 rounded-lg bg-slate-900 object-cover ${live ? "" : "hidden"}`} />
              {live && <span className="text-xs font-semibold text-slate-600">{fingerHint}</span>}
            </div>
            <p className="text-xs text-slate-500">
              Place a fingertip gently over the rear camera (and flash). A single camera channel gives pulse waveform, signal quality, PI and pulse rate; it <strong>cannot</strong> provide an SpO₂ estimate.
            </p>
          </div>
        )}

        {source === "file" && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <input ref={fileRef} type="file" accept=".csv,.txt,text/csv" className="hidden" onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
              <button onClick={() => fileRef.current?.click()} disabled={live} className={btnGhost}><Upload size={16} /> Choose recording (CSV)</button>
              {recording && (
                <label className="block">
                  <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Sampling rate (Hz)</span>
                  <input value={fsText} disabled={live} onChange={(e) => setFsText(e.target.value)} inputMode="decimal" aria-label="Sampling rate"
                         className={`w-28 rounded-xl border bg-white px-3 py-2 text-sm font-medium outline-none ${fsValid || fsText === "" ? "border-slate-200" : "border-rose-300"}`} />
                </label>
              )}
              {recording && !live && <button onClick={startReplay} disabled={!fsValid} className={btnPrimary}><Play size={16} /> Start replay</button>}
              {recording && live && (<>
                <button onClick={togglePause} disabled={phase === "ended"} className={btnGhost}>{phase === "paused" ? <Play size={16} /> : <Pause size={16} />}{phase === "paused" ? "Resume" : "Pause"}</button>
                <button onClick={() => { (srcRef.current as ReplaySource)?.restart(); resetSession(); setPhase("streaming"); }} className={btnGhost}><RotateCcw size={16} /> Restart</button>
              </>)}
            </div>
            {recording && (
              <p className="text-xs text-slate-500">
                {recording.name}: {recording.rec.rows} samples · PPG column “{recording.rec.irColumn}”{recording.rec.red ? " · red channel found" : ""}{recording.rec.accel ? " · accelerometer found" : ""}
                {recording.rec.fs ? ` · rate ${recording.rec.fs} Hz from the time column` : " · enter the sampling rate"}
              </p>
            )}
            {recording?.rec.warnings.map((w) => <p key={w} className="text-xs font-semibold text-amber-800">{w}</p>)}
            {live && <div className="h-1.5 rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${progress * 100}%` }} /></div>}
            <p className="text-xs text-slate-500">Replays the recording at its real sampling rate through exactly the same pipeline as a live sensor.</p>
          </div>
        )}

        {error && <div role="alert" className="flex gap-2 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-800"><TriangleAlert size={16} className="mt-0.5 shrink-0" /> {error}</div>}

        {notice && !error && <p className="text-xs text-slate-500">{notice}</p>}
      </section>

      {!live && !error && (
        <div className="card grid place-items-center px-6 py-16 text-center text-sm text-slate-500">
          No signal yet. Connect a sensor, start the camera, or replay a recording. Nothing is simulated.
        </div>
      )}

      {live && (
        <>
          <section className="card p-6">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-bold text-navy-900">Pulse waveform <span className="text-sm font-normal text-slate-500">(last 8 s, mean removed{cfg.invert_default[source] ? ", polarity flipped so beats point up" : ""})</span></h2>
              <button onClick={downloadRecording} disabled={stats.samples === 0} className={btnGhost}><Download size={14} /> Save recording CSV</button>
            </div>
            <div className="h-56 w-full" role="img" aria-label="Live pulse waveform">
              <ResponsiveContainer>
                <LineChart data={chart} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                  <XAxis dataKey="t" type="number" domain={chartDomain} tick={false} height={4} />
                  <YAxis tick={{ fontSize: 10 }} width={48} domain={["auto", "auto"]} tickFormatter={(v: number) => (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(Math.abs(v) < 10 ? 1 : 0))} />
                  <Line dataKey="y" stroke="#4f46e5" strokeWidth={1.8} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-1 text-xs text-slate-500">{stats.samples} samples recorded · {stats.rate ? `${stats.rate.toFixed(1)} Hz` : "measuring rate…"} · {stats.seconds.toFixed(1)} s buffered</p>
          </section>

          {collecting && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> {collecting}</div>}
          {analysisError && <div role="alert" className="card flex gap-2 border-rose-200 p-4 text-sm text-rose-800"><TriangleAlert size={16} className="mt-0.5 shrink-0" /> {analysisError}</div>}

          {result && (
            <>
              {abstainNow && (
                <div className="card flex gap-4 border-slate-300 bg-slate-50 p-6" role="alert">
                  <CircleSlash size={28} className="mt-0.5 shrink-0 text-slate-600" />
                  <div>
                    <div className="text-xl font-extrabold text-slate-700">ABSTAIN — REACQUIRE SIGNAL</div>
                    <p className="mt-1 text-sm text-slate-600">{result.reliability_impact.text} No reading is trusted from this window; estimates are withheld.</p>
                  </div>
                </div>
              )}

              <section className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6" aria-label="Live measurements">
                <Metric label={<Term label="Signal quality" tip="SQI (0–100) from pulse shape, noise, amplitude consistency and rhythm regularity. Thresholds are not clinically validated." />}
                        value={result.sqi.toFixed(0)} tone={Q_TEXT[result.signal_quality]} sub={result.signal_quality} />
                <Metric label="Motion" value={result.motion_state} sub={`score ${result.motion_score.toFixed(0)} · ${result.motion_source}`}
                        tone={result.motion_state === "LOW" ? "text-emerald-600" : result.motion_state === "MEDIUM" ? "text-amber-600" : "text-rose-600"} />
                <Metric label={<Term label="Perfusion index" tip="PI = AC/DC × 100 of the infrared signal. Low perfusion may reduce signal strength and increase measurement uncertainty." />}
                        value={result.pi_estimate !== null ? `${result.pi_estimate.toFixed(2)}%` : "—"} sub={result.pi_estimate === null ? "withheld (poor signal)" : result.pi_estimate < 1 ? "LOW (configured threshold)" : "NORMAL"} />
                <Metric label="Pulse rate" value={result.pulse_rate_estimate !== null ? `${result.pulse_rate_estimate.toFixed(0)}` : "—"} sub="per min · signal-processing estimate" />
                <Metric label={<Term label="SpO₂ estimate" tip="Ratio-of-ratios from red and infrared channels with generic, uncalibrated coefficients. A research estimate, never a measurement." />}
                        value={result.spo2.estimate !== null ? `${result.spo2.estimate.toFixed(1)}%` : "—"}
                        sub={result.spo2.estimate !== null ? `R = ${result.spo2.ratio_r} · uncalibrated` : result.spo2.note} />
                <Metric label="Window" value={`${result.window_seconds.toFixed(0)} s`} sub={`${result.fs_used.toFixed(0)} Hz${result.resampled ? " · resampled" : ""}`} />
              </section>

              <section className="card p-6">
                <h2 className="font-bold text-navy-900">Reliability assessment <span className="text-xs font-normal text-slate-500">· rule engine (signal quality, motion, perfusion); the calibrated CQR/Mondrian assessment is on the Reliability Check page</span></h2>
                {abstainNow ? (
                  <p className="mt-2 text-2xl font-extrabold text-slate-600">ABSTAIN</p>
                ) : rel ? (
                  <>
                    <p className={`mt-2 text-3xl font-extrabold ${REL_TEXT[rel.reliability_state]}`}>{rel.reliability_state}</p>
                    <p className="text-sm font-semibold text-slate-600">{rel.status}</p>
                    <ul className="mt-3 space-y-2 text-sm">
                      {rel.reasons.map((x) => (
                        <li key={x.code} className="flex gap-2.5"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${SEV[x.severity]}`} /><span><strong>{x.title}.</strong> <span className="text-slate-600">{x.text}</span></span></li>
                      ))}
                    </ul>
                    <p className="mt-3 text-xs text-slate-500">{rel.uncertainty_note}</p>
                  </>
                ) : <p className="mt-2 text-sm text-slate-600">{relMsg || "Calculating…"}</p>}

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Objective pigmentation (ITA, °)</span>
                    {pigment ? (
                      <div className="rounded-xl bg-indigo-50 px-3 py-2 text-sm text-indigo-900">{pigment.ita.toFixed(1)}° → <strong>{pigment.group.toUpperCase()}</strong> (from the pigmentation module)</div>
                    ) : (
                      <input value={itaText} onChange={(e) => setItaText(e.target.value)} inputMode="decimal" placeholder="e.g. 28.5 — or measure it on the Pigmentation page"
                             className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-400" aria-label="ITA" />
                    )}
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">SpO₂ reading to assess (%)</span>
                    {result.spo2.estimate !== null ? (
                      <div className="rounded-xl bg-indigo-50 px-3 py-2 text-sm text-indigo-900">{result.spo2.estimate.toFixed(1)}% (live, uncalibrated estimate)</div>
                    ) : (
                      <input value={spo2Text} onChange={(e) => setSpo2Text(e.target.value)} inputMode="decimal" placeholder="enter the value your oximeter shows"
                             className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-400" aria-label="SpO2 reading" />
                    )}
                  </label>
                </div>
              </section>

              <section className="card p-6">
                <h3 className="font-bold text-navy-900">Why this signal quality?</h3>
                <ul className="mt-2 space-y-2">
                  {result.reasons.map((x, i) => <li key={i} className="flex gap-2.5 text-sm text-slate-600"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${SEV[x.severity]}`} />{x.text}</li>)}
                </ul>
                <p className="mt-3 text-xs text-slate-500">{result.spo2.note}</p>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
