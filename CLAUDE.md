# Routine instructions — flight-searcher

You are running as a **scheduled routine** (e.g. every 30 min). Each fire,
you act as the autonomous researcher in an autoresearch-style loop searching
for the best business-class round-trip flights for a single adult on:

- `LHR-BLR` — London Heathrow ↔ Bangalore
- `LHR-ATL` — London Heathrow ↔ Atlanta
- `LHR-LAX` — London Heathrow ↔ Los Angeles

over the rest of 2026 (2026-05-01 .. 2026-12-20).

## Mental model

The harness mirrors karpathy/autoresearch:

| autoresearch | here |
|---|---|
| `prepare.py` (immutable) | `search_lib.py` — flight scraper, cache, scoring. **Never edit.** |
| `train.py` (agent edits) | `strategy.py` — date pairs + max_stops per route. **You edit this.** |
| `program.md` (goals) | `preferences.md` — scoring weights + tactical hints |
| `val_bpb` (lower=better) | mean of per-route best scores (lower=better) |

The orchestrator runs your current `strategy.py`, scores results, keeps it
(if mean improved) or reverts to `runs/best_strategy.py` (if it didn't), and
persists state across fires in `runs/state.json`.

## Per-fire workflow

Run these steps in order each fire. Bash from `/Users/surajbhagavan/flight-searcher`.

1. **Bail if stopped.** If `runs/STOP` exists, post a one-line summary citing
   `runs/state.json` and exit. Do not delete `STOP` — only the user does.

2. **Read context** (in parallel):
   - `preferences.md` — goals + scoring (stable; skim if you've seen it).
   - `runs/state.json` — `fire_count`, `best_mean`, `best_summary_per_route`,
     `no_improve_streak`. (May not exist on the very first fire.)
   - Tail of `runs/run_log.md` (last ~80 lines) — what's been tried + scored.
   - Current `strategy.py` — the `STRATEGY` dict you'll mutate.

3. **Execute current strategy** — runs the scrape/score/keep-or-revert cycle:
   ```
   uv run python orchestrator.py --iters 1 --no-llm --append-log
   ```
   This logs results, may overwrite `strategy.py` (if it reverted), updates
   `state.json`, and may write `runs/STOP` if the no-improve streak hit
   `--stop-after-no-improve` (default 5).

4. **If `runs/STOP` was just written**, post the final per-route best summaries
   from `state.json["best_summary_per_route"]` and exit.

5. **Edit `strategy.py` for next fire.** Read the (possibly reverted)
   current `strategy.py`, decide a new STRATEGY dict, and write it. Guidance
   in the next section.

6. **Persist state.** `runs/` is tracked in git so state survives across
   remote fires. Commit and push:
   ```bash
   git add runs/ strategy.py
   git -c user.email=routine@flight-searcher -c user.name="flight-searcher routine" \
       commit -m "fire #N: <one-line summary, e.g. 'kept new best mean=0.092'>"
   git push origin main
   ```
   If `git push` fails (auth missing), post the diff in your final message
   and tell the user — without push, the next fire will start from the last
   pushed state.

7. **Done.** Post a one-line summary (best per route or stop reason) and
   exit. The next fire happens at the top of the next hour.

## How to choose the next strategy

You're optimizing one number per route: best score in the pool. Lower = better.
Score = 50% price + 25% duration + 15% stops + 10% airline quality, each
normalized within the pool (see `search_lib.score_itineraries`).

Each iteration, decide explicitly: **explore** or **exploit**? Write that into
the `notes` field of each `RouteStrategy` so you and future-you can read it.

- **Explore** — sample months/trip-lengths you haven't probed yet. Target
  shoulder seasons (May, Sep–Oct) first; then off-season (Jan-style months,
  but those are out of our 2026 window so focus on Nov/early Dec); then peak.
- **Exploit** — densify around your current winning month. Try ±3 days on
  outbound, ±3 days on return, alternate trip lengths (10 / 14 / 17 / 21 days),
  tighter `max_stops` (1 or 0) to bias toward faster flights.

### Hard rules

- Keep keys exactly: `"LHR-BLR"`, `"LHR-ATL"`, `"LHR-LAX"`.
- ≤ 8 date pairs per route per fire (each pair = one Google Flights scrape).
- Dates must be `YYYY-MM-DD` and within `2026-05-01 .. 2026-12-20`.
- Don't re-query date pairs that the log shows you already sampled in the
  last few fires unless you have a reason (e.g. checking for price movement
  on a winner).
- Use `notes` to explain what this iteration probes and what you learned
  from the previous iteration's result. The log + state.json is your only
  memory across fires.

### What good looks like

- **LHR-BLR**: sub-$2500 business is excellent. IndiGo/Air India sometimes
  $1500–$1800 with one stop. Gulf carriers (QR, EK, EY) at $2500–3500 are
  premium sweet spots.
- **LHR-ATL**: BA/VS/DL nonstop usually $3500–5500. Sub-$3500 with a
  European connection is a real find.
- **LHR-LAX**: BA/VS/AA nonstop usually $4500–7000. One-stop via
  BOS/JFK/ORD/EWR sometimes $3000–4000.

## File reference

```
flight-searcher/
├── search_lib.py        # IMMUTABLE — scrape, cache, score
├── strategy.py          # YOU EDIT — current STRATEGY dict
├── preferences.md       # goals + weights
├── orchestrator.py      # the harness — run with --no-llm
├── pyproject.toml
├── cache.sqlite         # 30-min TTL on (route, dates, cabin, max_stops)
└── runs/
    ├── best_strategy.py # snapshot of best strategy.py so far
    ├── run_log.md       # one entry per fire — your memory
    ├── report.md        # rewritten each fire — current best per route
    ├── state.json       # persistent counters + per-route best summaries
    └── STOP             # exists -> all future fires bail at startup
```

## Env / setup

- `uv` is on PATH at `/opt/homebrew/bin/uv`.
- Python 3.12+ is provided by `uv` from the project's virtualenv.
- No `ANTHROPIC_API_KEY` needed — you (the routine) are the LLM. The
  orchestrator is invoked with `--no-llm` so it never makes its own Sonnet call.
- Cache TTL defaults to 30 min — repeated queries within that window serve
  cached results. Override with `--cache-ttl SECONDS` if needed.
- Stop condition defaults to 5 consecutive no-improvement fires
  (`--stop-after-no-improve`). The user can override per-fire.

## Quick commands

```bash
# Standard fire (use this each time):
uv run python orchestrator.py --iters 1 --no-llm --append-log

# Force a fresh scrape (bypass cache, e.g. when checking price movement):
rm cache.sqlite && uv run python orchestrator.py --iters 1 --no-llm --append-log

# Resume after STOP:
rm runs/STOP

# Inspect current best:
cat runs/report.md
cat runs/state.json
```

## What NOT to do

- Don't edit `search_lib.py`, `orchestrator.py`, `preferences.md`, or anything
  in `runs/` except by running the orchestrator.
- Don't pass `--iters > 1` in a routine fire — one iteration per fire keeps
  the cadence consistent and the budget predictable.
- Don't delete `cache.sqlite` unless you specifically want to refresh prices
  (e.g. on a winning date pair to confirm it's still available).
- Don't delete `runs/STOP` — that's the user's signal to stop. If you think
  there's reason to continue past STOP, post the reason and let the user
  decide.
