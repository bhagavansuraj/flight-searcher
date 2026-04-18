"""Autoresearch-style loop for flight search.

Each iteration:
  1. Execute the current strategy.py — query Google Flights for every
     (route, date_pair) it lists, score results, record per-route best.
  2. If overall score improved, keep strategy.py as the new best.
  3. Show Claude preferences.md, search_lib's contract, the current
     strategy.py, and a compact history of what's been tried + scored.
  4. Claude emits a replacement strategy.py. Write it to disk and loop.

Usage:
    ANTHROPIC_API_KEY=... uv run python orchestrator.py --iters 8
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import search_lib
from search_lib import Itinerary, Weights, score_itineraries

load_dotenv()

ROOT = Path(__file__).parent
STRATEGY_FILE = ROOT / "strategy.py"
PREFS_FILE = ROOT / "preferences.md"
RUNS_DIR = ROOT / "runs"
RUNS_DIR.mkdir(exist_ok=True)
BEST_STRATEGY_FILE = RUNS_DIR / "best_strategy.py"
LOG_FILE = RUNS_DIR / "run_log.md"
REPORT_FILE = RUNS_DIR / "report.md"
STATE_FILE = RUNS_DIR / "state.json"
STOP_FILE = RUNS_DIR / "STOP"


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"fire_count": 0, "best_mean": None,
            "no_improve_streak": 0, "best_summary_per_route": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are an autonomous flight-search researcher. Your job is to edit a Python
module, strategy.py, to surface better business-class itineraries for three
routes (LHR-BLR, LHR-ATL, LHR-LAX) over the rest of 2026.

Each iteration, the harness:
  1. Executes your strategy.py, querying Google Flights for every date pair.
  2. Scores all itineraries per route (lower = better — 50% price, 25%
     duration, 15% stops, 10% airline quality, each normalized).
  3. Reports the best per-route score and the overall mean score to you.

You will see:
  - preferences.md — goals, scoring, and tactical hints (stable across runs).
  - search_lib.py contract — the primitives your strategy.py may rely on.
  - The CURRENT strategy.py.
  - A compact HISTORY of recent iterations: per-route best score + one-line
    summary of the winning itinerary, plus each iteration's notes.

Your response must be ONLY the new strategy.py file contents — no prose,
no markdown fences, no commentary outside the Python file. The orchestrator
will overwrite strategy.py verbatim with your output.

Key rules:
  - Keep the STRATEGY dict keys exactly: "LHR-BLR", "LHR-ATL", "LHR-LAX".
  - Keep date_pairs lists short (≤ 8 pairs per route) — each pair is one scrape.
  - Dates must be YYYY-MM-DD and fall in 2026-05-01 .. 2026-12-20.
  - Explore: on early iterations probe months you haven't sampled. Exploit:
    on later iterations densify samples around the month+trip-length that is
    currently winning.
  - Use the `notes` field on each RouteStrategy to explain what you're
    probing THIS iteration and what you learned from the last one. This is
    the only way to track your own reasoning across iterations.
  - Don't repeat date_pairs you've already fully explored unless you have a
    concrete reason — the history shows what's been tried.
"""


SEARCH_LIB_CONTRACT = """\
# search_lib.py contract (read-only — do not assume it contains more than this)

ROUTES = {"LHR-BLR": ("LHR", "BLR"), "LHR-ATL": ("LHR", "ATL"), "LHR-LAX": ("LHR", "LAX")}

@dataclass
class RouteStrategy:
    date_pairs: list[tuple[str, str]]   # (outbound, return) YYYY-MM-DD
    max_stops: Optional[int] = 2
    notes: str = ""

# The orchestrator calls, for each route:
#   for outbound, inbound in route_strategy.date_pairs:
#       itins += search_lib.search_round_trip(route, outbound, inbound,
#                                             cabin="business",
#                                             max_stops=route_strategy.max_stops)
# then scores the combined pool per route.
"""


@dataclass
class RouteResult:
    route: str
    num_itineraries: int
    best_score: float | None
    best_summary: str
    errors: list[str] = field(default_factory=list)


@dataclass
class IterationResult:
    iteration: int
    per_route: list[RouteResult]
    mean_score: float | None
    notes_by_route: dict[str, str]
    wall_time_s: float

    def summary_line(self) -> str:
        bits = []
        for r in self.per_route:
            s = f"{r.best_score:.3f}" if r.best_score is not None else "  n/a"
            bits.append(f"{r.route}={s}")
        m = f"{self.mean_score:.3f}" if self.mean_score is not None else "n/a"
        return f"iter {self.iteration}: mean={m}  " + "  ".join(bits)


def load_strategy_module():
    if "strategy" in sys.modules:
        importlib.reload(sys.modules["strategy"])
        return sys.modules["strategy"]
    return importlib.import_module("strategy")


def execute_strategy() -> IterationResult:
    """Run the current strategy.py and return per-route best-score results."""
    start = time.time()
    strat_mod = load_strategy_module()
    strategy = strat_mod.STRATEGY
    weights = Weights()
    per_route: list[RouteResult] = []
    notes_by_route: dict[str, str] = {}
    for route in search_lib.ROUTES:
        rs = strategy.get(route)
        if rs is None:
            per_route.append(RouteResult(route, 0, None, "", ["missing in STRATEGY"]))
            continue
        notes_by_route[route] = rs.notes
        pool: list[Itinerary] = []
        errors: list[str] = []
        for outbound, inbound in rs.date_pairs:
            try:
                pool.extend(
                    search_lib.search_round_trip(
                        route, outbound, inbound,
                        cabin="business", max_stops=rs.max_stops,
                    )
                )
            except Exception as e:
                errors.append(f"{outbound}/{inbound}: {e.__class__.__name__}: {e}")
        scored = score_itineraries(pool, weights)
        if scored:
            best_score, best_it = scored[0]
            per_route.append(RouteResult(
                route, len(pool), best_score, best_it.summary(), errors
            ))
        else:
            per_route.append(RouteResult(route, 0, None, "", errors or ["no results"]))
    scores = [r.best_score for r in per_route if r.best_score is not None]
    mean = sum(scores) / len(scores) if scores else None
    return IterationResult(
        iteration=-1, per_route=per_route, mean_score=mean,
        notes_by_route=notes_by_route, wall_time_s=time.time() - start,
    )


def build_history_block(history: list[IterationResult], current_strategy_src: str) -> str:
    lines = ["# HISTORY (most recent last)"]
    for h in history[-6:]:  # cap context
        lines.append(f"\n## Iteration {h.iteration}  ({h.wall_time_s:.0f}s)")
        for r in h.per_route:
            s = f"{r.best_score:.3f}" if r.best_score is not None else "n/a"
            lines.append(f"- **{r.route}** score={s} (n={r.num_itineraries}): {r.best_summary}")
            if r.errors:
                lines.append(f"  errors: {r.errors[:3]}")
            note = h.notes_by_route.get(r.route, "")
            if note:
                lines.append(f"  notes: {note}")
        m = f"{h.mean_score:.3f}" if h.mean_score is not None else "n/a"
        lines.append(f"- **MEAN** = {m}")
    lines.append("\n# CURRENT strategy.py\n```python\n" + current_strategy_src + "\n```")
    return "\n".join(lines)


def ask_claude_for_new_strategy(
    client: anthropic.Anthropic,
    history: list[IterationResult],
    current_src: str,
    prefs_text: str,
) -> str:
    history_block = build_history_block(history, current_src)
    user_msg = (
        "# preferences.md\n" + prefs_text
        + "\n\n" + SEARCH_LIB_CONTRACT
        + "\n\n" + history_block
        + "\n\nEmit the new strategy.py now. Python source only."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    # Strip accidental code fences if the model adds them.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def append_log(line: str) -> None:
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def write_report(history: list[IterationResult], state: dict) -> None:
    lines = ["# Flight search — best results\n"]
    bm = state.get("best_mean")
    lines.append(
        f"_Persistent best mean = {bm:.3f}_  (fire #{state.get('fire_count', 0)}, "
        f"no-improve streak {state.get('no_improve_streak', 0)})\n"
        if bm is not None else "_No best yet._\n"
    )
    summaries = state.get("best_summary_per_route", {})
    for route, summary in summaries.items():
        lines.append(f"\n## {route}")
        lines.append(f"- {summary}")
    if history:
        lines.append("\n---\n## Recent iterations\n")
        for h in history[-15:]:
            lines.append(f"- {h.summary_line()}")
    REPORT_FILE.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=None,
                    help="How many iterations to run. Default: 5 if --interval "
                         "is unset, else infinite.")
    ap.add_argument("--interval", type=float, default=None,
                    help="Seconds to sleep between iterations. With this set, "
                         "--iters defaults to infinite.")
    ap.add_argument("--cache-ttl", type=float, default=None,
                    help="Override search_lib cache TTL in seconds (default 1800).")
    ap.add_argument("--no-llm", action="store_true",
                    help="Execute current strategy once; skip the LLM call for "
                         "the next strategy (use this when an external agent "
                         "edits strategy.py — e.g. a Claude routine).")
    ap.add_argument("--append-log", action="store_true",
                    help="Append to run_log.md instead of truncating it.")
    ap.add_argument("--stop-after-no-improve", type=int, default=5,
                    help="Write runs/STOP after this many consecutive "
                         "iterations with no improvement to best mean score. "
                         "Future runs that see runs/STOP exit immediately.")
    args = ap.parse_args()

    if STOP_FILE.exists():
        print(f"runs/STOP exists — stop signal active. Delete {STOP_FILE} to resume.")
        return

    if not os.getenv("ANTHROPIC_API_KEY") and not args.no_llm:
        print("ANTHROPIC_API_KEY not set. Export it or pass --no-llm.", file=sys.stderr)
        sys.exit(1)

    if args.cache_ttl is not None:
        search_lib.set_default_cache_ttl(args.cache_ttl)

    if args.iters is None:
        iters = 10**9 if args.interval is not None else 5
    else:
        iters = args.iters

    if args.append_log and LOG_FILE.exists():
        with LOG_FILE.open("a") as f:
            f.write(f"\n# Resumed {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    else:
        LOG_FILE.write_text(f"# Run log — started {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    prefs_text = PREFS_FILE.read_text()
    history: list[IterationResult] = []
    state = _load_state()
    best: IterationResult | None = None
    client = None if args.no_llm else anthropic.Anthropic()

    for i in range(iters):
        print(f"\n=== iteration {i} ===")
        try:
            result = execute_strategy()
        except Exception as e:
            print("strategy exec failed:", e)
            traceback.print_exc()
            append_log(f"iter {i}: EXEC FAILED — {e}")
            # Revert to best so next iteration starts from a known-good file.
            if BEST_STRATEGY_FILE.exists():
                shutil.copy(BEST_STRATEGY_FILE, STRATEGY_FILE)
            break
        state["fire_count"] += 1
        result.iteration = state["fire_count"]
        history.append(result)
        line = result.summary_line()
        print(line)
        append_log(line)
        for r in result.per_route:
            append_log(f"  {r.route}: {r.best_summary}  (n={r.num_itineraries}, err={len(r.errors)})")
            note = result.notes_by_route.get(r.route, "")
            if note:
                append_log(f"    notes: {note}")

        # Keep-or-revert against the persistent best across fires.
        prev_best_mean = state.get("best_mean")
        improved = (
            result.mean_score is not None
            and (prev_best_mean is None or result.mean_score < prev_best_mean)
        )
        if improved:
            best = result
            state["best_mean"] = result.mean_score
            state["best_summary_per_route"] = {
                r.route: r.best_summary for r in result.per_route
            }
            state["no_improve_streak"] = 0
            shutil.copy(STRATEGY_FILE, BEST_STRATEGY_FILE)
            append_log(f"  -> kept as new best (mean={result.mean_score:.3f})")
        else:
            state["no_improve_streak"] = state.get("no_improve_streak", 0) + 1
            best_mean_str = f"{prev_best_mean:.3f}" if prev_best_mean is not None else "n/a"
            append_log(
                f"  -> reverting (best mean={best_mean_str}, "
                f"no-improve streak={state['no_improve_streak']})"
            )
            if BEST_STRATEGY_FILE.exists():
                shutil.copy(BEST_STRATEGY_FILE, STRATEGY_FILE)
        _save_state(state)

        # Stop signal: future fires bail at startup.
        if state["no_improve_streak"] >= args.stop_after_no_improve:
            STOP_FILE.write_text(
                f"Stopped {time.strftime('%Y-%m-%d %H:%M:%S')} after "
                f"{state['no_improve_streak']} consecutive iterations with "
                f"no improvement. Best mean={state.get('best_mean')}.\n"
                f"Delete this file to resume.\n"
            )
            append_log(f"  -> STOP written (streak={state['no_improve_streak']})")
            print(f"\nStop condition hit — wrote {STOP_FILE}")
            break

        if args.no_llm or i == iters - 1:
            continue
        current_src = STRATEGY_FILE.read_text()
        try:
            new_src = ask_claude_for_new_strategy(client, history, current_src, prefs_text)
        except Exception as e:
            print("Claude call failed:", e)
            append_log(f"  LLM failure: {e}")
            break
        STRATEGY_FILE.write_text(new_src)
        append_log(f"  -> wrote new strategy.py ({len(new_src)} chars)")

        # Write rolling report so external observers see progress mid-run.
        write_report(history, state)

        if args.interval is not None and i < iters - 1:
            time.sleep(args.interval)

    write_report(history, state)
    bm = state.get("best_mean")
    bm_str = f"{bm:.3f}" if bm is not None else "n/a"
    print(f"\nPersistent best mean: {bm_str}  (fire #{state.get('fire_count', 0)})")
    print(f"Report: {REPORT_FILE}")
    print(f"Log: {LOG_FILE}")
    if STOP_FILE.exists():
        print(f"STOP marker present: {STOP_FILE}")


if __name__ == "__main__":
    main()
