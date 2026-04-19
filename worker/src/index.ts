// Cloudflare Worker — flight-searcher
//
// Cron (0 * * * *) fires scheduled() → runOnce() → autoresearch-style loop:
//   scrape SerpAPI per route × date_pair, score, keep-or-revert vs persistent
//   best, then call Claude for the next strategy. State lives in KV.
//
// HTTP endpoints (all bearer-auth'd with AUTH_TOKEN except /health):
//   GET  /health           → liveness
//   POST /run              → kick a fire now
//   POST /resume           → clear the STOP flag
//   GET  /state            → dump current KV state (strategy + state + log)
//   POST /search           → ad-hoc SerpAPI proxy (single route × date pair)
//
// Secrets (wrangler secret put …):
//   SERPAPI_KEY         — SerpAPI key
//   AUTH_TOKEN          — bearer token for HTTP endpoints
//   ANTHROPIC_API_KEY   — Claude key for the next-strategy call
// Bindings (wrangler.toml):
//   STATE               — KV namespace

import { runOnce } from "./orchestrator";
import { searchRoundTrip } from "./search";
import {
  readState,
  readStrategy,
  readBestStrategy,
  readRunLog,
  writeState,
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
      env,
      body.origin,
      body.dest,
      body.outbound,
      body.inbound,
      cabin,
      maxStops,
    );
    return json({ route: `${body.origin}-${body.dest}`, n: itins.length, itineraries: itins });
  } catch (e) {
    return json({ error: String(e) }, 502);
  }
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, ts: Date.now() });
    }

    if (!authed(req, env)) return new Response("Unauthorized", { status: 401 });

    if (req.method === "GET" && url.pathname === "/state") {
      const [state, strategy, best, log] = await Promise.all([
        readState(env),
        readStrategy(env),
        readBestStrategy(env),
        readRunLog(env),
      ]);
      return json({ state, strategy, best_strategy: best, run_log: log });
    }

    if (req.method === "POST" && url.pathname === "/run") {
      try {
        const result = await runOnce(env);
        return json(result);
      } catch (e) {
        return json({ error: String(e) }, 500);
      }
    }

    if (req.method === "POST" && url.pathname === "/resume") {
      const state = await readState(env);
      state.stopped = false;
      state.no_improve_streak = 0;
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
      runOnce(env)
        .then((r) => console.log("fire:", JSON.stringify({ fire: r.fire, kept: r.kept, mean: r.mean, stopped: r.stopped })))
        .catch((e) => console.error("fire failed:", String(e))),
    );
  },
};
