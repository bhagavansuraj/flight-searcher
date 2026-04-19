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
  strategy_notes: Record<string, string>;
  llm_note: string;
}

export interface Env {
  SERPAPI_KEY: string;
  AUTH_TOKEN: string;
  ANTHROPIC_API_KEY: string;
  STATE: KVNamespace;
}
