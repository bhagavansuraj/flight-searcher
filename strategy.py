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


# === ITERATION 3: rotate to unexplored months (Jun/Jul/Aug/Dec) ===============
# Fires #1-3 all 403'd — sandbox IP blocked by Google Flights on every attempt.
# Previous strategies covered May/Sep/Oct/Nov. Rotating to Jun/Jul/Aug/Dec so
# that when the environment unblocks, we'll have full month coverage ready.
# Mixed trip lengths (10d / 14d / 17d / 21d) within each route to diversify.
STRATEGY: dict[str, RouteStrategy] = {
    "LHR-BLR": RouteStrategy(
        date_pairs=[
            ("2026-06-09", "2026-06-23"),   # Jun shoulder, 14d
            ("2026-07-07", "2026-07-17"),   # Jul, 10d (shorter trip)
            ("2026-08-04", "2026-08-21"),   # Aug, 17d
            ("2026-12-01", "2026-12-15"),   # Dec early, 14d (before cutoff)
        ],
        max_stops=2,
        notes=(
            "Iter 3: EXPLORE — rotating to Jun/Jul/Aug/Dec, months not yet probed. "
            "Fires 1-3 all 403; strategy rotation ensures full month coverage for "
            "when sandbox IP unblocks. BLR: IndiGo/AI $1500-1800, Gulf $2500-3500."
        ),
    ),
    "LHR-ATL": RouteStrategy(
        date_pairs=[
            ("2026-06-09", "2026-06-23"),   # Jun, 14d
            ("2026-07-07", "2026-07-21"),   # Jul, 14d
            ("2026-08-04", "2026-08-18"),   # Aug, 14d
            ("2026-12-01", "2026-12-15"),   # Dec early, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 3: EXPLORE — same Jun/Jul/Aug/Dec rotation as BLR. "
            "ATL target: BA/VS/DL nonstop $3500-5500 or sub-$3500 via European hub."
        ),
    ),
    "LHR-LAX": RouteStrategy(
        date_pairs=[
            ("2026-06-09", "2026-06-23"),   # Jun, 14d
            ("2026-07-07", "2026-07-28"),   # Jul, 21d (longer trip)
            ("2026-08-04", "2026-08-18"),   # Aug, 14d
            ("2026-12-01", "2026-12-15"),   # Dec early, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 3: EXPLORE — Jun/Jul/Aug/Dec rotation. "
            "LAX target: one-stop via BOS/JFK/ORD/EWR at $3000-4000."
        ),
    ),
}
