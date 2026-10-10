import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";

export function PageSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading page">
      <div className="skeleton h-9 w-56" />
      <div className="skeleton h-4 w-96 max-w-full" />
      <div className="grid gap-4 md:grid-cols-3">
        <div className="skeleton h-32" /><div className="skeleton h-32" /><div className="skeleton h-32" />
      </div>
      <div className="skeleton h-64" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}

interface State { error: Error | null }

/** A crash in one page shows a recoverable message instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };
  static getDerivedStateFromError(error: Error): State { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("Page error:", error, info.componentStack); }
  componentDidUpdate(prev: { resetKey?: string }) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="card mx-auto max-w-xl space-y-3 p-8 text-center">
        <TriangleAlert className="mx-auto text-amber-500" size={32} />
        <h2 className="text-lg font-bold text-navy-900">Something went wrong on this page</h2>
        <p className="text-sm text-slate-600">The rest of the app is unaffected. Reload the page, or open another section from the menu.</p>
        <button onClick={() => location.reload()} className="mx-auto inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-500">
          <RefreshCw size={14} /> Reload
        </button>
      </div>
    );
  }
}
