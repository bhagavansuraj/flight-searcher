import { ROUTES, DATE_WINDOW_START, DATE_WINDOW_END } from "./preferences";
import { searchRoundTrip } from "./search";
import { scoreItineraries, summarize } from "./score";
import { readState, readRunLog } from "./state";
import type { Env, Itinerary } from "./types";

// ---------------------------------------------------------------------------
// Tool definitions (sent to the Anthropic API)
// ---------------------------------------------------------------------------

export const TOOL_DEFINITIONS = [
  {
    name: "search_flights",
    description:
      "Search business-class round-trip flights for one route and one departure/return date pair. " +
      "Returns top results sorted by price plus a session-best indicator. Each call uses 1 of your budget.",
    input_schema: {
      type: "object",
      required: ["route", "outbound", "inbound"],
      properties: {
        route: {
          type: "string",
          enum: ["LHR-BLR", "LHR-ATL", "LHR-LAX"],
          description: "The route to search.",
        },
        outbound: {
          type: "string",
          description: `Departure date YYYY-MM-DD (${DATE_WINDOW_START}..${DATE_WINDOW_END}).`,
        },
        inbound: {
          type: "string",
          description: "Return date YYYY-MM-DD, must be after outbound.",
        },
        max_stops: {
          type: "integer",
          enum: [0, 1, 2],
          description: "Max stops: 0=nonstop only, 1=≤1 stop, 2=≤2 stops. Defaults to 2.",
        },
      },
    },
  },
  {
    name: "get_best",
    description: "Return the all-time best itinerary per route found across all previous fires.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "get_history",
    description: "Return recent fire summaries so you understand what has been tried.",
    input_schema: {
      type: "object",
      properties: {
        limit: {
          type: "integer",
          minimum: 1,
          maximum: 20,
          description: "Number of recent fires to return. Defaults to 8.",
        },
      },
    },
  },
  {
    name: "done",
    description:
      "Signal that you are done searching this fire. " +
      "Call this when you have exhausted useful searches or are near the budget limit. " +
      "The harness keeps or reverts based on what you found.",
    input_schema: {
      type: "object",
      required: ["summary", "notes_for_next_fire"],
      properties: {
        summary: {
          type: "string",
          description: "1-2 sentences: what improved (or didn't) and why.",
        },
        notes_for_next_fire: {
          type: "string",
          description:
            "Tactical notes for the next agent: best dates found, what to focus on, what's been ruled out.",
        },
      },
    },
  },
];

// ---------------------------------------------------------------------------
// Session state threaded through the agent loop
// ---------------------------------------------------------------------------

export interface AgentSession {
  // All itineraries accumulated across searches this fire, keyed by route.
  pool: Record<string, Itinerary[]>;
  // Best price seen this fire per route (for the ★ indicator in results).
  sessionBest: Record<string, number>;
  searchesUsed: number;
  budget: number;
  // Set when the agent calls done().
  done: boolean;
  doneSummary: string;
  doneNotes: string;
}

export function newSession(budget: number): AgentSession {
  return {
    pool: { "LHR-BLR": [], "LHR-ATL": [], "LHR-LAX": [] },
    sessionBest: {},
    searchesUsed: 0,
    budget,
    done: false,
    doneSummary: "",
    doneNotes: "",
  };
}

// ---------------------------------------------------------------------------
// Tool dispatch
// ---------------------------------------------------------------------------

export async function dispatchTool(
  name: string,
  input: Record<string, any>,
  session: AgentSession,
  env: Env,
): Promise<string> {
  switch (name) {
    case "search_flights":
      return toolSearchFlights(input, session, env);
    case "get_best":
      return toolGetBest(env);
    case "get_history":
      return toolGetHistory(input, env);
    case "done":
      session.done = true;
      session.doneSummary = String(input.summary ?? "");
      session.doneNotes = String(input.notes_for_next_fire ?? "");
      return "Acknowledged. Fire complete.";
    default:
      return `Unknown tool: ${name}`;
  }
}

// ---------------------------------------------------------------------------
// Individual tool implementations
// ---------------------------------------------------------------------------

async function toolSearchFlights(
  input: Record<string, any>,
  session: AgentSession,
  env: Env,
): Promise<string> {
  const route = String(input.route ?? "");
  const outbound = String(input.outbound ?? "");
  const inbound = String(input.inbound ?? "");
  const maxStops = typeof input.max_stops === "number" ? input.max_stops : 2;

  if (!ROUTES[route]) return `Unknown route: ${route}`;
  if (outbound < DATE_WINDOW_START || outbound > DATE_WINDOW_END) {
    return `outbound ${outbound} outside window ${DATE_WINDOW_START}..${DATE_WINDOW_END}`;
  }
  if (inbound < DATE_WINDOW_START || inbound > DATE_WINDOW_END) {
    return `inbound ${inbound} outside window ${DATE_WINDOW_START}..${DATE_WINDOW_END}`;
  }
  if (outbound >= inbound) return `outbound must be before inbound`;

  session.searchesUsed++;
  const remaining = session.budget - session.searchesUsed;

  const [origin, dest] = ROUTES[route];
  let itins: Itinerary[];
  try {
    itins = await searchRoundTrip(env, origin, dest, outbound, inbound, "business", maxStops);
  } catch (e) {
    return `search error: ${String(e).slice(0, 200)}\n(${remaining} searches remaining)`;
  }

  if (itins.length === 0) {
    return `No results for ${route} ${outbound}→${inbound}.\n(${remaining} searches remaining)`;
  }

  // Accumulate into session pool.
  session.pool[route] = session.pool[route] ?? [];
  session.pool[route].push(...itins);

  // Track session-best price per route.
  const scored = scoreItineraries(itins);
  const currentSessionBest = session.sessionBest[route] ?? Infinity;
  const cheapest = Math.min(...itins.map((i) => i.price_usd));
  if (cheapest < currentSessionBest) session.sessionBest[route] = cheapest;

  // Format top results.
  const top = scored.slice(0, 8);
  const lines: string[] = [
    `${route}  ${outbound} → ${inbound}  |  ${itins.length} results  |  ${remaining} searches remaining`,
    ``,
  ];
  for (const [, it] of top) {
    const best = it.price_usd <= (session.sessionBest[route] ?? Infinity) + 1 ? " ★" : "";
    const al = it.airlines.join("/") || "?";
    const lay = it.layover_airports.length ? ` via ${it.layover_airports.join(",")}` : "";
    const dur = `${Math.floor(it.duration_min / 60)}h${String(it.duration_min % 60).padStart(2, "0")}m`;
    lines.push(
      `  $${it.price_usd}${best}  |  ${it.stops}st ${dur}  |  ${al}${lay}  |  ${it.dep_time}→${it.arr_time}`,
    );
  }
  if (session.sessionBest[route] !== undefined) {
    lines.push(`\nSession best for ${route}: $${session.sessionBest[route]}`);
  }

  return lines.join("\n");
}

async function toolGetBest(env: Env): Promise<string> {
  const state = await readState(env);
  if (Object.keys(state.best_summary_per_route).length === 0) {
    return "No all-time bests recorded yet (this may be the first fire).";
  }
  const lines = [
    `All-time bests  (mean score: ${state.best_mean?.toFixed(4) ?? "n/a"})`,
    ``,
  ];
  for (const [route, summary] of Object.entries(state.best_summary_per_route)) {
    lines.push(`  ${route}: ${summary}`);
  }
  return lines.join("\n");
}

async function toolGetHistory(input: Record<string, any>, env: Env): Promise<string> {
  const limit = typeof input.limit === "number" ? Math.min(input.limit, 20) : 8;
  const log = await readRunLog(env);
  if (log.length === 0) return "No fire history yet.";
  const recent = log.slice(-limit);
  const lines: string[] = [];
  for (const e of recent) {
    const kept = e.kept ? "✓ kept" : "✗ reverted";
    const mean = e.mean !== null ? e.mean.toFixed(4) : "n/a";
    lines.push(`Fire #${e.fire}  ${e.ts.slice(0, 16)}  ${kept}  mean=${mean}`);
    for (const [route, outcome] of Object.entries(e.per_route)) {
      if (outcome.best_summary) {
        lines.push(`  ${route}: ${outcome.best_summary}  (pool=${outcome.n})`);
      } else {
        lines.push(`  ${route}: no results`);
      }
    }
    const note = e.agent_notes ?? e.llm_note ?? "";
    if (note) lines.push(`  note: ${note.slice(0, 140)}`);
    lines.push("");
  }
  return lines.join("\n").trimEnd();
}
