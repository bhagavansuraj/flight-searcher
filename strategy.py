"""Agent-editable search strategy. The orchestrator executes this file.

Analogous to autoresearch's train.py — the single mutable artifact.
The agent rewrites this module each iteration to try new search angles.

Contract: expose a module-level `STRATEGY: dict[str, RouteStrategy]` mapping
each route in search_lib.ROUTES to a RouteStrategy. The orchestrator calls
search_lib.search_and_score for every (route, date_pair) combination, then
scores the pool per route.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class RouteStrategy:
    # List of (outbound_YYYY-MM-DD, return_YYYY-MM-DD) pairs to query.
    date_pairs: list[tuple[str, str]]
    # Max stops filter passed to Google Flights. None = any.
    max_stops: Optional[int] = 2
    # Free-text commentary on what this iteration is probing and why.
    notes: str = ""


# === ITERATION 1: retry baseline monthly sweep, May–Dec 2026 ===
# Fire #1 returned 0 results (err=8 per route) due to Cloudflare Worker
# returning HTTP 403 "Host not in allowlist" — the Worker blocked the
# Anthropic cloud sandbox IP. This is a Worker/infra issue, not a strategy
# issue. Retrying identical date pairs next fire; if Worker is fixed we
# get the first-ever scored pool and can start exploiting.
_BASELINE_PAIRS: list[tuple[str, str]] = [
    ("2026-05-05", "2026-05-19"),
    ("2026-06-02", "2026-06-16"),
    ("2026-07-07", "2026-07-21"),
    ("2026-08-04", "2026-08-18"),
    ("2026-09-01", "2026-09-15"),
    ("2026-10-06", "2026-10-20"),
    ("2026-11-03", "2026-11-17"),
    ("2026-12-01", "2026-12-15"),
]

STRATEGY: dict[str, RouteStrategy] = {
    "LHR-BLR": RouteStrategy(
        date_pairs=list(_BASELINE_PAIRS),
        max_stops=2,
        notes="Iter 1: EXPLORE — retrying monthly baseline sweep (fire #1 all errors, "
              "Worker 403 'Host not in allowlist'). No data yet; same 14d pairs, "
              "looking for cheapest month per route.",
    ),
    "LHR-ATL": RouteStrategy(
        date_pairs=list(_BASELINE_PAIRS),
        max_stops=2,
        notes="Iter 1: EXPLORE — retrying monthly baseline sweep (fire #1 all errors, "
              "Worker 403). No data yet.",
    ),
    "LHR-LAX": RouteStrategy(
        date_pairs=list(_BASELINE_PAIRS),
        max_stops=2,
        notes="Iter 1: EXPLORE — retrying monthly baseline sweep (fire #1 all errors, "
              "Worker 403). No data yet.",
    ),
}
