import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import Shell from "./components/Shell";
import { ErrorBoundary, PageSkeleton } from "./components/Boundary";
import Overview from "./pages/Overview";
import type { SignalSummary } from "./lib/signalApi";
import type { PigmentSummary } from "./lib/pigmentApi";
import type { PerfusionSummary } from "./lib/perfusionApi";
import { NAV, ROUTE_ALIAS } from "./lib/nav";
import { fetchHealth, type Health } from "./lib/api";
import { ResearchStatusContext } from "./lib/researchContext";

// Heavier pages (charts, streaming) load on first visit.
const LiveMonitor = lazy(() => import("./pages/LiveMonitor"));
const ReliabilityCheck = lazy(() => import("./pages/ReliabilityCheck"));
const DataCollection = lazy(() => import("./pages/DataCollection"));
const Dataset = lazy(() => import("./pages/Dataset"));
const Models = lazy(() => import("./pages/Models"));
const Results = lazy(() => import("./pages/Results"));
const Xai = lazy(() => import("./pages/Xai"));
const Summary = lazy(() => import("./pages/Summary"));

const fromHash = () => {
  const raw = location.hash.slice(1);
  const id = ROUTE_ALIAS[raw] ?? raw;
  return NAV.some((n) => n.id === id) ? id : "overview";       // unknown links land on the overview
};

/** Pages that work without the analysis service (the header shows its state); the large notice is for pages that need it. */
const WORKS_OFFLINE = new Set(["overview", "live", "research-summary"]);

export default function App() {
  const [active, setActive] = useState(fromHash);
  const [health, setHealth] = useState<Health | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [apiProblem, setApiProblem] = useState("");
  const wasDown = useRef(false);
  const [epoch, setEpoch] = useState(0);                 // bumps when the service comes back, so pages that failed to load fetch again
  // Latest values from the measurement modules; all are consumed by the Reliability Check.
  const [signal, setSignal] = useState<SignalSummary | null>(null);
  const [pigment, setPigment] = useState<PigmentSummary | null>(null);
  const [perfusion, setPerfusion] = useState<PerfusionSummary | null>(null);

  useEffect(() => {
    const onHash = () => setActive(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const label = NAV.find((n) => n.id === active)?.label ?? "Overview";
    document.title = `${label} · PigmentCal-UQ`;
  }, [active]);

  const refreshHealth = useCallback(() => {
    fetchHealth().then((h) => { if (wasDown.current) setEpoch((n) => n + 1); wasDown.current = false; setHealth(h); setBackendDown(false); setApiProblem(""); }).catch((e: Error) => { wasDown.current = true; setBackendDown(true); setApiProblem(e.message); });
  }, []);
  useEffect(() => { refreshHealth(); }, [refreshHealth, active]);
  useEffect(() => {                                   // while the service is down, keep trying so the page recovers by itself
    if (!backendDown) return;
    const t = window.setInterval(refreshHealth, 10000);
    return () => window.clearInterval(t);
  }, [backendDown, refreshHealth]);

  return (
    <ResearchStatusContext.Provider value={health?.research_status}>
    <Shell active={active} onNavigate={(id) => { location.hash = id; }} health={health} backendDown={backendDown}>
      {backendDown && !WORKS_OFFLINE.has(active) && (
        <div role="alert" className="mb-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {apiProblem.startsWith("A different service")
            ? <><strong>The wrong service is answering.</strong> {apiProblem}</>
            : <><strong>The analysis service is not reachable,</strong> so nothing can be analysed right now. Start the backend as described in README.md; this page retries every few seconds.</>}
        </div>
      )}
      <ErrorBoundary key={epoch} resetKey={active}>
        <Suspense fallback={<PageSkeleton />}>
          {active === "overview" ? <Overview health={health} signal={signal} pigment={pigment} />
            : active === "live" ? <LiveMonitor pigment={pigment} onSummary={setSignal} />
            : active === "reliability" ? <ReliabilityCheck signal={signal} pigment={pigment} perfusion={perfusion} onSignal={setSignal} onPigment={setPigment} onPerfusion={setPerfusion} />
            : active === "models" ? <Models />
            : active === "data-collection" ? <DataCollection onChanged={refreshHealth} />
            : active === "dataset" ? <Dataset onChanged={refreshHealth} />
            : active === "research-results" ? <Results health={health} />
            : active === "xai" ? <Xai />
            : active === "research-summary" ? <Summary health={health} />
            : null}
        </Suspense>
      </ErrorBoundary>
    </Shell>
    </ResearchStatusContext.Provider>
  );
}
