import { createContext, useContext } from "react";
import type { Health } from "./api";

export type ResearchStatusInfo = NonNullable<Health["research_status"]>;

/** The backend's research-status decision, provided once by App. Components only read it; nothing here can change it. */
export const ResearchStatusContext = createContext<ResearchStatusInfo | undefined>(undefined);
export const useResearchStatus = () => useContext(ResearchStatusContext);

/** True when the backend says the numbers on screen are not a research result (and there is something on screen). */
export const notAResult = (s?: ResearchStatusInfo) => !!s && !s.results_allowed && s.state !== "NO_DATA";
