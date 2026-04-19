# flight-searcher

Autoresearch-style hourly loop searching for the best business-class
round-trip flights on:

- `LHR-BLR` — London Heathrow ↔ Bangalore
- `LHR-ATL` — London Heathrow ↔ Atlanta
- `LHR-LAX` — London Heathrow ↔ Los Angeles

over 2026-05-01 .. 2026-12-20 (one adult, round-trip, business class).

## Architecture

The loop now runs entirely inside a **Cloudflare Worker** on a cron trigger.
There is no remote Anthropic-cloud routine and no local Python orchestrator
in the critical path.

```
CF Cron (0 * * * *)
  └─ worker.scheduled(event)
       └─ orchestrator.runOnce(env)
            ├─ read state from KV (strategy, best_strategy, state, run_log)
            ├─ for each route × date_pair: SerpAPI search + score (parallel)
            ├─ keep-or-revert vs persistent best_mean
            ├─ POST api.anthropic.com/v1/messages → new strategy (tool_use)
            └─ write state back to KV
```

All code lives in `worker/`. See `worker/src/` for the 7-file module layout.

Legacy Python files (`search_lib.py`, `strategy.py`, `orchestrator.py`,
`preferences.md`, `runs/`) are kept for historical reference and ad-hoc local
inspection. They are NOT part of the active loop and should not be edited
to change routine behaviour — edit the Worker instead.

## Operating the Worker

State lives in a KV namespace bound as `STATE`. HTTP endpoints (all bearer-
auth'd with `AUTH_TOKEN` except `/health`):

| method | path       | purpose                                       |
|--------|------------|-----------------------------------------------|
| GET    | /health    | liveness                                      |
| POST   | /run       | kick a fire immediately (same as cron tick)   |
| POST   | /resume    | clear the STOP flag after a no-improve trip   |
| GET    | /state     | dump current strategy + state + run log       |
| POST   | /search    | ad-hoc SerpAPI proxy (single route×dates)     |

Deploy:

```bash
cd worker
npm install
npx wrangler kv namespace create STATE       # paste id into wrangler.toml
npx wrangler secret put SERPAPI_KEY
npx wrangler secret put AUTH_TOKEN
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler deploy
```

Inspect live state (curl with `$AUTH_TOKEN`):

```bash
curl -sS "$URL/state" -H "authorization: Bearer $TOKEN" | jq .
```

Kick a fire out-of-band:

```bash
curl -sS -X POST "$URL/run" -H "authorization: Bearer $TOKEN" | jq .
```

Reset the loop after STOP:

```bash
curl -sS -X POST "$URL/resume" -H "authorization: Bearer $TOKEN"
```

Wipe all state (nuclear — starts fresh from the baseline strategy):

```bash
for k in state strategy best_strategy run_log; do
  npx wrangler kv key delete --binding=STATE "$k"
done
```

## Tuning

- **Cadence**: edit `[triggers].crons` in `worker/wrangler.toml`.
- **Stop threshold**: `STOP_AFTER_NO_IMPROVE` in `worker/src/preferences.ts`.
- **Scoring weights**: `WEIGHTS` in `worker/src/score.ts`.
- **Preferences prompt** (what "good" looks like, explore/exploit guidance,
  rules): `PREFERENCES_PROMPT` in `worker/src/preferences.ts`.
- **Baseline strategy** (used on first-ever fire): `baselineStrategy()` in
  `worker/src/orchestrator.ts`.
- **LLM model**: `model:` field in `worker/src/llm.ts` (currently
  `claude-sonnet-4-6`).

## Legacy Python side

Files retained for inspection / local experimentation:

- `search_lib.py` — still works against `/search` HTTP endpoint if
  `FLIGHT_WORKER_URL` + `FLIGHT_WORKER_TOKEN` are set.
- `strategy.py` / `orchestrator.py` / `runs/` — not used by the cron loop.
