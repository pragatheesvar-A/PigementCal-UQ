import { type ReactNode, useEffect, useRef, useState } from "react";
import { Menu, ShieldCheck, X } from "lucide-react";
import { NAV } from "../lib/nav";
import type { Health } from "../lib/api";
import { Badge } from "./ui";
import { STATUS_TONE, researchStatus } from "../lib/status";

interface Props {
  active: string;
  onNavigate: (id: string) => void;
  health: Health | null;
  backendDown: boolean;
  children: ReactNode;
}

const GROUPS = Array.from(new Set(NAV.map((n) => n.group)));

export default function Shell({ active, onNavigate, health, backendDown, children }: Props) {
  const [open, setOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const current = NAV.find((n) => n.id === active) ?? NAV[0];
  const status = researchStatus(health);

  // New page: scroll to the top, move focus to the content for keyboard and screen-reader users, close the drawer.
  useEffect(() => {
    window.scrollTo({ top: 0 });
    mainRef.current?.focus({ preventScroll: true });
    setOpen(false);
  }, [active]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col bg-navy-900 text-slate-300">
      <a href="#overview" className="flex items-center gap-3 px-5 pb-5 pt-6">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-base font-extrabold text-white shadow-lg shadow-indigo-900/40">P</span>
        <span>
          <span className="block text-[15px] font-bold leading-tight text-white">PigmentCal-UQ</span>
          <span className="block text-[11px] text-slate-400">Can you trust this number?</span>
        </span>
      </a>
      <div className="flex-1 overflow-y-auto px-3 pb-4">
        {GROUPS.map((g) => (
          <div key={g} className="mb-3">
            <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{g}</div>
            <ul className="space-y-0.5">
              {NAV.filter((n) => n.group === g).map((n) => {
                const Icon = n.icon;
                const on = n.id === active;
                return (
                  <li key={n.id}>
                    <button
                      onClick={() => onNavigate(n.id)}
                      aria-current={on ? "page" : undefined}
                      className={`group relative flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-[13px] font-medium transition-all duration-150 ${
                        on ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"
                      }`}
                    >
                      {on && <span aria-hidden className="absolute -left-3 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r bg-violet-400" />}
                      <Icon size={16} className={`shrink-0 transition-colors ${on ? "text-violet-300" : "text-slate-500 group-hover:text-slate-300"}`} />
                      <span className="flex-1 truncate">{n.label}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
      <div className="m-3 flex gap-2 rounded-xl bg-white/5 p-3 text-[11px] leading-relaxed text-slate-400">
        <ShieldCheck size={14} className="mt-0.5 shrink-0 text-slate-500" />
        <span>Not a diagnostic device and not clinically validated.<br />Independent project by Pragatheesvar.</span>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[264px_1fr]">
      <a href="#main" onClick={(e) => { e.preventDefault(); mainRef.current?.focus(); }} className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:shadow-lg">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen lg:block">{sidebar}</aside>

      <div className={`fixed inset-0 z-40 lg:hidden ${open ? "" : "pointer-events-none"}`} aria-hidden={!open}>
        <div className={`absolute inset-0 bg-slate-900/50 backdrop-blur-sm transition-opacity duration-200 ${open ? "opacity-100" : "opacity-0"}`} onClick={() => setOpen(false)} />
        <aside className={`absolute inset-y-0 left-0 w-72 shadow-2xl transition-transform duration-200 ease-out ${open ? "translate-x-0" : "-translate-x-full"}`}>{sidebar}</aside>
      </div>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/80 backdrop-blur-md">
          <div className="flex items-center gap-3 px-4 py-3 sm:px-8">
            <button className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden" onClick={() => setOpen((o) => !o)} aria-label={open ? "Close navigation" : "Open navigation"} aria-expanded={open}>
              {open ? <X size={20} /> : <Menu size={20} />}
            </button>
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-sm font-semibold text-slate-800">{current.label}</h2>
              <p className="hidden truncate text-xs text-slate-500 sm:block">{current.blurb}</p>
            </div>
            <Badge tone={STATUS_TONE[status]} dot>{status}</Badge>
            <span className="hidden sm:inline-flex">
              <Badge tone={backendDown ? "red" : health ? "green" : "slate"} dot>
                {backendDown ? "API offline" : health ? `API v${health.version}` : "Connecting…"}
              </Badge>
            </span>
          </div>
        </header>
        <main id="main" ref={mainRef} tabIndex={-1} className="page-enter mx-auto max-w-6xl px-4 py-8 outline-none sm:px-8">
          {children}
        </main>
        <footer className="mx-auto max-w-6xl px-4 pb-10 pt-2 text-center text-xs text-slate-400 sm:px-8">
          Not a diagnostic device. Not clinically validated. Values come from your sensor, your files or your own entries; the application itself generates no data. Data the gate recognises as software-test data is labelled as such. Independent project by Pragatheesvar.
        </footer>
      </div>
    </div>
  );
}
