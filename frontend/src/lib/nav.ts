import {
  BarChart3, Database, FileUp, Gauge, Info, LayoutDashboard, Layers, Radio, Search, type LucideIcon,
} from "lucide-react";

export interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  group: string;
  blurb: string;
}

export const NAV: NavItem[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard, group: "Start", blurb: "Summary of the reliability layer and the current state of your data." },
  { id: "live", label: "Live Monitor", icon: Radio, group: "Measure", blurb: "Live sensor stream (analysis about once per second): signal quality, perfusion, motion and reliability." },
  { id: "reliability", label: "Reliability Check", icon: Gauge, group: "Measure", blurb: "Enter or measure SpO₂, signal quality, perfusion and objective ITA, then get a reliability assessment." },
  { id: "data-collection", label: "Data Collection", icon: FileUp, group: "Data", blurb: "Upload PPG, reference SaO₂ and pigmentation data; merge and validate into the research dataset." },
  { id: "dataset", label: "Dataset", icon: Database, group: "Data", blurb: "Validate the research dataset and split it by participant." },
  { id: "models", label: "Models", icon: Layers, group: "Analysis", blurb: "Ridge baseline versus LightGBM comparator, evaluated on held-out participants." },
  { id: "research-results", label: "Results", icon: BarChart3, group: "Analysis", blurb: "Test metrics with participant-level bootstrap CIs, subgroup error and conformal coverage." },
  { id: "xai", label: "Explainability", icon: Search, group: "Analysis", blurb: "What the fitted models rely on (model behavior, not causality)." },
  { id: "research-summary", label: "Research Summary", icon: Info, group: "About", blurb: "Problem, method, results and limitations." },
];

/** Old hash links keep working. */
export const ROUTE_ALIAS: Record<string, string> = {
  results: "research-results", about: "research-summary", judge: "reliability",
  guided: "reliability", signal: "reliability", pigmentation: "reliability", perfusion: "reliability",
};
