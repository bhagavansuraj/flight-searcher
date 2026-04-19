"""Immutable flight search utilities. The agent never edits this file.

Analogous to autoresearch's prepare.py: stable primitives (fetch, parse, cache,
score) that the agent's strategy.py builds on top of.

Backend: calls a Cloudflare Worker (FLIGHT_WORKER_URL) that proxies SerpAPI's
google_flights engine. This keeps the SerpAPI key off the routine sandbox and
centralises rate-limiting / caching at the edge.

Required env vars:
  FLIGHT_WORKER_URL    e.g. https://flight-searcher-proxy.<sub>.workers.dev
  FLIGHT_WORKER_TOKEN  shared bearer token (same as Worker's AUTH_TOKEN secret)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal, Optional

ROUTES = {
    "LHR-BLR": ("LHR", "BLR"),
    "LHR-ATL": ("LHR", "ATL"),
    "LHR-LAX": ("LHR", "LAX"),
}

CACHE_DB = Path(__file__).parent / "cache.sqlite"
Cabin = Literal["economy", "premium-economy", "business", "first"]

_DEFAULT_CACHE_TTL_S: float = 30 * 60  # 30 min


def set_default_cache_ttl(seconds: float) -> None:
    global _DEFAULT_CACHE_TTL_S
    _DEFAULT_CACHE_TTL_S = float(seconds)


@dataclass
class Itinerary:
    route: str
    outbound_date: str
    return_date: str
    cabin: str
    price_usd: float
    stops: int
    duration_min: int
    airlines: list[str]
    dep_time: str
    arr_time: str
    day_shift: str
    layover_airports: list[str]
    raw_label: str

    def summary(self) -> str:
        d = self.duration_min
        dur = f"{d // 60}h{d % 60:02d}m"
        al = "/".join(self.airlines) or "?"
        lay = f" via {','.join(self.layover_airports)}" if self.layover_airports else ""
        return (
            f"${self.price_usd:.0f} | {self.stops}st | {dur} | {al}{lay} | "
            f"{self.dep_time}→{self.arr_time}{self.day_shift} | "
            f"{self.outbound_date}/{self.return_date}"
        )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _init_cache() -> sqlite3.Connection:
    conn = sqlite3.connect(CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache "
        "(key TEXT PRIMARY KEY, fetched_at REAL, payload TEXT)"
    )
    return conn


def _cache_key(parts: tuple) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Worker client
# ---------------------------------------------------------------------------

def _call_worker(
    origin: str,
    dest: str,
    outbound: str,
    inbound: str,
    cabin: Cabin,
    max_stops: Optional[int],
    timeout: float = 30.0,
) -> list[dict]:
    worker_url = os.environ.get("FLIGHT_WORKER_URL", "").rstrip("/")
    token = os.environ.get("FLIGHT_WORKER_TOKEN", "")
    if not worker_url or not token:
        raise RuntimeError(
            "FLIGHT_WORKER_URL and FLIGHT_WORKER_TOKEN must be set "
            "(Cloudflare Worker proxy for SerpAPI)"
        )

    body = json.dumps({
        "origin": origin,
        "dest": dest,
        "outbound": outbound,
        "inbound": inbound,
        "cabin": cabin,
        "max_stops": max_stops,
    }).encode()
    req = urllib.request.Request(
        f"{worker_url}/search",
        data=body,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        raise RuntimeError(f"worker http {e.code}: {detail}") from None

    return data.get("itineraries", [])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_round_trip(
    route: str,
    outbound: str,
    inbound: str,
    *,
    cabin: Cabin = "business",
    max_stops: Optional[int] = None,
    use_cache: bool = True,
    cache_ttl_s: Optional[float] = None,
) -> list[Itinerary]:
    if route not in ROUTES:
        raise ValueError(f"Unknown route {route!r}; expected one of {list(ROUTES)}")
    if cache_ttl_s is None:
        cache_ttl_s = _DEFAULT_CACHE_TTL_S
    origin, dest = ROUTES[route]

    _load_dotenv()

    key_parts = ("worker", "v1", route, outbound, inbound, cabin, max_stops)
    key = _cache_key(key_parts)

    conn = _init_cache()
    if use_cache:
        row = conn.execute(
            "SELECT fetched_at, payload FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row and time.time() - row[0] < cache_ttl_s:
            conn.close()
            return [Itinerary(**r) for r in json.loads(row[1])]

    raw = _call_worker(origin, dest, outbound, inbound, cabin, max_stops)
    itins = [Itinerary(**r) for r in raw]

    conn.execute(
        "INSERT OR REPLACE INTO cache (key, fetched_at, payload) VALUES (?, ?, ?)",
        (key, time.time(), json.dumps([asdict(it) for it in itins])),
    )
    conn.commit()
    conn.close()
    return itins


def _load_dotenv() -> None:
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


# --- Scoring -----------------------------------------------------------------

@dataclass
class Weights:
    price: float = 0.50
    duration: float = 0.25
    stops: float = 0.15
    airline_quality: float = 0.10


AIRLINE_TIER: dict[str, float] = {
    "Qatar Airways": 1.0, "Singapore Airlines": 1.0, "Emirates": 0.95,
    "ANA": 0.95, "Japan Airlines": 0.95, "Cathay Pacific": 0.9,
    "Etihad Airways": 0.9, "Virgin Atlantic": 0.85, "British Airways": 0.8,
    "Lufthansa": 0.8, "Swiss": 0.8, "KLM": 0.75, "Air France": 0.75,
    "Turkish Airlines": 0.75, "Finnair": 0.7, "Delta": 0.75,
    "American": 0.65, "United": 0.65, "Air India": 0.55, "IndiGo": 0.4,
    "Vistara": 0.7, "Air Canada": 0.7, "Iberia": 0.65,
}


def airline_score(airlines: list[str]) -> float:
    if not airlines:
        return 0.5
    return sum(AIRLINE_TIER.get(a, 0.55) for a in airlines) / len(airlines)


def score_itineraries(
    itins: list[Itinerary], weights: Weights = Weights()
) -> list[tuple[float, Itinerary]]:
    if not itins:
        return []
    min_price = min(i.price_usd for i in itins)
    min_dur = min(i.duration_min for i in itins)
    scored = []
    for it in itins:
        price_c = (it.price_usd - min_price) / max(min_price, 1.0)
        dur_c = (it.duration_min - min_dur) / max(min_dur, 1.0)
        stops_c = min(it.stops, 3) / 3.0
        airline_c = 1.0 - airline_score(it.airlines)
        s = (
            weights.price * price_c
            + weights.duration * dur_c
            + weights.stops * stops_c
            + weights.airline_quality * airline_c
        )
        scored.append((s, it))
    scored.sort(key=lambda x: x[0])
    return scored


def search_and_score(
    route: str, outbound: str, inbound: str, *,
    cabin: Cabin = "business", max_stops: Optional[int] = None,
    weights: Weights = Weights(),
) -> list[tuple[float, Itinerary]]:
    itins = search_round_trip(
        route, outbound, inbound, cabin=cabin, max_stops=max_stops
    )
    return score_itineraries(itins, weights)
