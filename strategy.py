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


# === ITERATION 0: wide-net baseline ==========================================
# One 14-day sample per month across the rest of 2026. Max 2 stops.
STRATEGY: dict[str, RouteStrategy] = {
    "LHR-BLR": RouteStrategy(
        date_pairs=[
            ("2026-05-12", "2026-05-26"),
            ("2026-06-09", "2026-06-23"),
            ("2026-07-14", "2026-07-28"),
            ("2026-08-11", "2026-08-25"),
            ("2026-09-15", "2026-09-29"),
            ("2026-10-13", "2026-10-27"),
            ("2026-11-10", "2026-11-24"),
            ("2026-12-01", "2026-12-15"),
        ],
        max_stops=2,
        notes="Iter 0: one 14-day sample per month May–Dec 2026 to find the cheapest months.",
    ),
    "LHR-ATL": RouteStrategy(
        date_pairs=[
            ("2026-05-12", "2026-05-26"),
            ("2026-06-09", "2026-06-23"),
            ("2026-07-14", "2026-07-28"),
            ("2026-08-11", "2026-08-25"),
            ("2026-09-15", "2026-09-29"),
            ("2026-10-13", "2026-10-27"),
            ("2026-11-10", "2026-11-24"),
            ("2026-12-01", "2026-12-15"),
        ],
        max_stops=2,
        notes="Iter 0: same cadence as LHR-BLR — shoulder seasons likely cheapest.",
    ),
    "LHR-LAX": RouteStrategy(
        date_pairs=[
            ("2026-05-12", "2026-05-26"),
            ("2026-06-09", "2026-06-23"),
            ("2026-07-14", "2026-07-28"),
            ("2026-08-11", "2026-08-25"),
            ("2026-09-15", "2026-09-29"),
            ("2026-10-13", "2026-10-27"),
            ("2026-11-10", "2026-11-24"),
            ("2026-12-01", "2026-12-15"),
        ],
        max_stops=2,
        notes="Iter 0: same cadence. LAX is the longest route; direct BA/VS premium.",
    ),
}
