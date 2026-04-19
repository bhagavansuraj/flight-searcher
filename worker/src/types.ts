export type Cabin = "economy" | "premium-economy" | "business" | "first";

export interface Itinerary {
  route: string;
  outbound_date: string;
  return_date: string;
  cabin: string;
  price_usd: number;
  stops: number;
  duration_min: number;
  airlines: string[];
  dep_time: string;
  arr_time: string;
  day_shift: string;
  layover_airports: string[];
  raw_label: string;
}

// Kept for backwards compat (pre-agent-harness strategy format in KV).
export interface RouteStrategy {
  date_pairs: [string, string][];
  max_stops: number;
  notes: string;
}
export type Strategy = Record<string, RouteStrategy>;

export interface State {
  fire_count: number;
  best_mean: number | null;
  no_improve_streak: number;
  best_summary_per_route: Record<string, string>;
  stopped: boolean;
  running?: boolean; // true while a fire is in progress
}

export interface RouteOutcome {
  best_score: number | null;
  best_summary: string | null;
  n: number;
  errors: string[];
}

export interface RunLogEntry {
  fire: number;
  ts: string;
  kept: boolean;
  mean: number | null;
  per_route: Record<string, RouteOutcome>;
  llm_note: string;
  // Legacy (pre-agent harness)
  strategy_notes?: Record<string, string>;
  // Agent harness fields (fire >= agent migration)
  agent_notes?: string;
  agent_searches?: number;
  agent_turns?: number;
}

export interface Env {
  SERPAPI_KEY: string;
  AUTH_TOKEN: string;
  ANTHROPIC_API_KEY: string;
  STATE: KVNamespace;
}
