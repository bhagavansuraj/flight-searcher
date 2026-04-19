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


# === ITERATION 4: best shoulder season (Sep/Oct) + May — last chance before STOP ===
# Fires #1-4 all 403'd — sandbox IP blocked by Google Flights every attempt.
# no_improve_streak=4; one more failure triggers STOP (default --stop-after-no-improve 5).
# Pivoting to the highest-value month coverage: Sep/Oct shoulder + May early-book,
# with 8 pairs per route (max) to maximise the probability of a hit if env unblocks.
# Trip lengths: 10d, 14d, 17d, 21d to capture different demand buckets.
STRATEGY: dict[str, RouteStrategy] = {
    "LHR-BLR": RouteStrategy(
        date_pairs=[
            ("2026-09-01", "2026-09-15"),   # Sep shoulder, 14d
            ("2026-09-08", "2026-09-18"),   # Sep shoulder, 10d
            ("2026-09-15", "2026-10-02"),   # Sep→Oct overlap, 17d
            ("2026-10-06", "2026-10-20"),   # Oct shoulder, 14d
            ("2026-10-13", "2026-11-03"),   # Oct→Nov, 21d
            ("2026-05-05", "2026-05-19"),   # May early, 14d
            ("2026-05-12", "2026-05-29"),   # May, 17d
            ("2026-11-10", "2026-11-24"),   # Nov off-season, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 4: EXPLORE — Sep/Oct shoulder prime targets + May early-book + Nov. "
            "Fire #5 is last before STOP (streak=4→5). BLR target: IndiGo/AI $1500-1800, "
            "Gulf carriers $2500-3500. Max 8 pairs to maximise hit chance if env unblocks."
        ),
    ),
    "LHR-ATL": RouteStrategy(
        date_pairs=[
            ("2026-09-01", "2026-09-15"),   # Sep shoulder, 14d
            ("2026-09-08", "2026-09-18"),   # Sep shoulder, 10d
            ("2026-09-15", "2026-10-02"),   # Sep→Oct overlap, 17d
            ("2026-10-06", "2026-10-20"),   # Oct shoulder, 14d
            ("2026-10-13", "2026-11-03"),   # Oct→Nov, 21d
            ("2026-05-05", "2026-05-19"),   # May early, 14d
            ("2026-05-12", "2026-05-29"),   # May, 17d
            ("2026-11-10", "2026-11-24"),   # Nov off-season, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 4: EXPLORE — Sep/Oct shoulder + May + Nov. ATL target: BA/VS/DL nonstop "
            "$3500-5500 or sub-$3500 via European hub. max_stops=2 to capture both nonstop "
            "and one-stop options."
        ),
    ),
    "LHR-LAX": RouteStrategy(
        date_pairs=[
            ("2026-09-01", "2026-09-15"),   # Sep shoulder, 14d
            ("2026-09-08", "2026-09-18"),   # Sep shoulder, 10d
            ("2026-09-15", "2026-10-02"),   # Sep→Oct overlap, 17d
            ("2026-10-06", "2026-10-20"),   # Oct shoulder, 14d
            ("2026-10-13", "2026-11-03"),   # Oct→Nov, 21d
            ("2026-05-05", "2026-05-19"),   # May early, 14d
            ("2026-05-12", "2026-05-29"),   # May, 17d
            ("2026-11-10", "2026-11-24"),   # Nov off-season, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 4: EXPLORE — Sep/Oct shoulder + May + Nov. LAX target: one-stop via "
            "BOS/JFK/ORD/EWR at $3000-4000; nonstop BA/VS/AA $4500-7000. Sep/Oct "
            "historically cheapest for transatlantic."
        ),
    ),
}
