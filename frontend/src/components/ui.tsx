import { type ReactNode, useState } from "react";
import { HelpCircle } from "lucide-react";

type Tone = "indigo" | "amber" | "green" | "red" | "slate" | "violet";
const TONES: Record<Tone, string> = {
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  slate: "bg-slate-100 text-slate-600 ring-slate-200",
};

export function Badge({ tone = "slate", children, dot }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${TONES[tone]}`}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

/** Accessible hover/focus tooltip for plain-language explanations of technical terms. */
export function Term({ label, tip }: { label: string; tip: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex items-center gap-1">
      {label}
      <button
        type="button"
        aria-label={`What is ${label}?`}
        onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        className="text-slate-400 hover:text-indigo-600 focus:text-indigo-600 outline-none"
      >
        <HelpCircle size={14} />
      </button>
      {open && (
        <span role="tooltip" className="absolute left-0 top-full z-20 mt-2 w-64 rounded-xl bg-navy-900 p-3 text-xs font-normal normal-case leading-relaxed tracking-normal text-slate-100 shadow-xl">
          {tip}
        </span>
      )}
    </span>
  );
}
