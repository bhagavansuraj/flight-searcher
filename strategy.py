"""Agent-editable search strategy. The orchestrator executes this file.

Analogous to autoresearch's train.py — the single mutable artifact.
The agent rewrites this module each iteration to try new search angles.

Contract: expose a module-level `STRATEGY: dict[str, RouteStrategy]` mapping
each route in search_lib.ROUTES to a RouteStrategy. The orchestrator calls
search_lib.search_and_score for every (route, date_pair) combination, then
scores the pool per route.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RouteStrategy:
    # List of (outbound_YYYY-MM-DD, return_YYYY-MM-DD) pairs to query.
    date_pairs: list[tuple[str, str]]
    # Max stops filter passed to Google Flights. None = any.
    max_stops: Optional[int] = 2
    # Free-text commentary on what this iteration is probing and why.
    notes: str = ""


# === ITERATION 2: sandbox blocked — minimal probe, await env fix ==============
# Fires #1 and #2 both failed with Google Flights 403 after 4 retries.
# Root cause: sandbox IP is blocked by Google Flights. The primp impersonation
# warning ("chrome_13x does not exist, using 'random'") may also reduce success.
# Keeping 4 pairs per route (minimal footprint) targeting best shoulder seasons
# in case the environment changes (proxy, residential IP, etc.).
# Next step for user: run from a non-datacenter IP or add a proxy to search_lib.
STRATEGY: dict[str, RouteStrategy] = {
    "LHR-BLR": RouteStrategy(
        date_pairs=[
            ("2026-09-08", "2026-09-22"),   # Sep shoulder, 14d
            ("2026-10-06", "2026-10-20"),   # Oct shoulder, 14d
            ("2026-05-12", "2026-05-26"),   # May shoulder, 14d
            ("2026-11-10", "2026-11-24"),   # Nov off-peak, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 2: Google Flights 403 both fires — sandbox IP blocked. "
            "Minimal 4-pair probe; shoulder seasons Sep/Oct/May prioritised. "
            "No change in strategy will fix this; env needs a non-blocked IP."
        ),
    ),
    "LHR-ATL": RouteStrategy(
        date_pairs=[
            ("2026-09-08", "2026-09-22"),
            ("2026-10-06", "2026-10-20"),
            ("2026-05-12", "2026-05-26"),
            ("2026-11-10", "2026-11-24"),
        ],
        max_stops=2,
        notes=(
            "Iter 2: same sandbox-blocked situation. ATL nonstop BA/VS/DL. "
            "Keeping shoulder dates ready for when scraping unblocks."
        ),
    ),
    "LHR-LAX": RouteStrategy(
        date_pairs=[
            ("2026-09-08", "2026-09-22"),
            ("2026-10-06", "2026-10-20"),
            ("2026-05-12", "2026-05-26"),
            ("2026-11-10", "2026-11-24"),
        ],
        max_stops=2,
        notes=(
            "Iter 2: same sandbox-blocked situation. LAX one-stop via "
            "BOS/JFK/ORD/EWR target $3000-4000. Ready for unblocked env."
        ),
    ),
}
