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


# === ITERATION 1: shoulder-season focus with fresh dates =====================
# Fire #1 had all 8 scrapes fail (err=8 per route) — likely transient network
# issues. Retrying with fresh date pairs, focusing on shoulder seasons (May,
# Sep, Oct) and mixing trip lengths (10, 14, 17 days). Still max_stops=2 for
# maximum coverage. Re-use some Iter 0 dates + add new ones.
STRATEGY: dict[str, RouteStrategy] = {
    "LHR-BLR": RouteStrategy(
        date_pairs=[
            ("2026-05-05", "2026-05-19"),   # early May, 14d
            ("2026-05-19", "2026-05-29"),   # late May, 10d
            ("2026-09-01", "2026-09-15"),   # early Sep, 14d
            ("2026-09-22", "2026-10-06"),   # late Sep, 14d
            ("2026-10-06", "2026-10-23"),   # Oct, 17d
            ("2026-11-03", "2026-11-17"),   # early Nov, 14d
            ("2026-12-05", "2026-12-19"),   # early Dec, 14d
            ("2026-06-02", "2026-06-16"),   # Jun, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 1: fire #1 all-errors, retrying with fresh date pairs. "
            "Shoulder focus: May, Sep-Oct. Mixed trip lengths (10/14/17d). "
            "If errors persist again, scraper is blocked in this sandbox."
        ),
    ),
    "LHR-ATL": RouteStrategy(
        date_pairs=[
            ("2026-05-05", "2026-05-19"),   # early May, 14d
            ("2026-05-19", "2026-05-29"),   # late May, 10d
            ("2026-09-01", "2026-09-15"),   # early Sep, 14d
            ("2026-09-22", "2026-10-06"),   # late Sep, 14d
            ("2026-10-06", "2026-10-23"),   # Oct, 17d
            ("2026-11-03", "2026-11-17"),   # early Nov, 14d
            ("2026-12-05", "2026-12-19"),   # early Dec, 14d
            ("2026-06-02", "2026-06-16"),   # Jun, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 1: same approach as BLR. ATL is mostly nonstop BA/VS/DL; "
            "shoulder seasons (May, Sep-Oct) expected cheapest. "
            "Sub-$3500 with European connection is a real find."
        ),
    ),
    "LHR-LAX": RouteStrategy(
        date_pairs=[
            ("2026-05-05", "2026-05-19"),   # early May, 14d
            ("2026-05-19", "2026-05-29"),   # late May, 10d
            ("2026-09-01", "2026-09-15"),   # early Sep, 14d
            ("2026-09-22", "2026-10-06"),   # late Sep, 14d
            ("2026-10-06", "2026-10-23"),   # Oct, 17d
            ("2026-11-03", "2026-11-17"),   # early Nov, 14d
            ("2026-12-05", "2026-12-19"),   # early Dec, 14d
            ("2026-06-02", "2026-06-16"),   # Jun, 14d
        ],
        max_stops=2,
        notes=(
            "Iter 1: LAX nonstop BA/VS/AA usually $4500-7000; one-stop via "
            "BOS/JFK/ORD/EWR sometimes $3000-4000. Shoulder seasons first."
        ),
    ),
}
