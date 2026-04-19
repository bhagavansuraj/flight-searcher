// Cloudflare Worker — flight-searcher agent harness
//
// Cron (0 * * * *): scheduled() → runAgent() → multi-turn Claude loop that
//   calls search_flights / get_best / get_history / done tools, then scores
//   the accumulated pool and keep-or-reverts vs persistent best. State in KV.
//
// HTTP endpoints (all bearer-auth'd with AUTH_TOKEN except /health):
//   GET  /health    → liveness
//   POST /run       → kick a fire (202 async; poll /state for results)
//   POST /resume    → clear the STOP flag + reset streak
//   GET  /state     → dump KV state (state + agent_notes + run_log)
//   POST /search    → ad-hoc SerpAPI proxy (single route × date pair)
//
// Secrets: SERPAPI_KEY, AUTH_TOKEN, ANTHROPIC_API_KEY
// Bindings: STATE (KV namespace)

import { runAgent } from "./orchestrator";
import { searchRoundTrip } from "./search";
import {
  readState,
  writeState,
  readAgentNotes,
  readBestAgentNotes,
  readRunLog,
} from "./state";
import type { Cabin, Env } from "./types";

function json(body: any, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function authed(req: Request, env: Env): boolean {
  return (req.headers.get("authorization") || "") === `Bearer ${env.AUTH_TOKEN}`;
}

async function handleSearch(req: Request, env: Env): Promise<Response> {
  let body: any;
  try {
    body = await req.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }
  const missing = ["origin", "dest", "outbound", "inbound"].filter((k) => !body[k]);
  if (missing.length) return json({ error: "missing_fields", fields: missing }, 400);
  const cabin: Cabin = body.cabin || "business";
  const maxStops: number =
    typeof body.max_stops === "number" && [0, 1, 2].includes(body.max_stops)
      ? body.max_stops
      : 2;
  try {
    const itins = await searchRoundTrip(
      env, body.origin, body.dest, body.outbound, body.inbound, cabin, maxStops,
    );
    return json({ route: `${body.origin}-${body.dest}`, n: itins.length, itineraries: itins });
  } catch (e) {
    return json({ error: String(e) }, 502);
  }
}

export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, ts: Date.now() });
    }

    if (!authed(req, env)) return new Response("Unauthorized", { status: 401 });

    if (req.method === "GET" && url.pathname === "/state") {
      const [state, agentNotes, bestNotes, log] = await Promise.all([
        readState(env),
        readAgentNotes(env),
        readBestAgentNotes(env),
        readRunLog(env),
      ]);
      return json({ state, agent_notes: agentNotes, best_agent_notes: bestNotes, run_log: log });
    }

    if (req.method === "POST" && url.pathname === "/run") {
      const state = await readState(env);
      if (state.running) {
        return json({ ok: false, message: "A fire is already in progress." }, 409);
      }
      // Kick fire async — returns immediately; poll /state for completion.
      ctx.waitUntil(
        runAgent(env)
          .then((r) => console.log("fire:", JSON.stringify({ fire: r.fire, kept: r.kept, mean: r.mean, searches: r.searches, turns: r.turns })))
          .catch((e) => console.error("fire failed:", String(e))),
      );
      return json({ ok: true, message: "fire started", fire: state.fire_count + 1 }, 202);
    }

    if (req.method === "POST" && url.pathname === "/resume") {
      const state = await readState(env);
      state.stopped = false;
      state.no_improve_streak = 0;
      state.running = false;
      await writeState(env, state);
      return json({ ok: true, state });
    }

    if (req.method === "POST" && url.pathname === "/search") {
      return handleSearch(req, env);
    }

    return new Response("Not found", { status: 404 });
  },

  async scheduled(_event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      runAgent(env)
        .then((r) => console.log("fire:", JSON.stringify({ fire: r.fire, kept: r.kept, mean: r.mean, searches: r.searches, turns: r.turns, stopped: r.stopped })))
        .catch((e) => console.error("fire failed:", String(e))),
    );
  },
};
