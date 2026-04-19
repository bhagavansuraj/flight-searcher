"""Immutable flight search utilities. The agent never edits this file.

Analogous to autoresearch's prepare.py: stable primitives (fetch, parse, cache,
score) that the agent's strategy.py builds on top of.

Backend: SerpAPI Google Flights (when SERPAPI_KEY env var is set) with a
fallback to the original fast-flights/primp scraper.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
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
# Cache helpers
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
# SerpAPI backend
# ---------------------------------------------------------------------------

_CABIN_TO_SERPAPI: dict[str, int] = {
    "economy": 1,
    "premium-economy": 2,
    "business": 3,
    "first": 4,
}

# max_stops=None/0/1/2  →  SerpAPI stops param (0=any,1=nonstop,2=≤1,3=≤2)
_STOPS_TO_SERPAPI: dict[Optional[int], int] = {
    None: 0,
    0: 1,
    1: 2,
    2: 3,
}


def _parse_time(raw: str) -> str:
    """'2026-09-01 08:30' → '8:30AM' (or keep as-is for display)."""
    try:
        _, t = raw.split(" ", 1)
        h, m = t.split(":")
        h, m = int(h), int(m)
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d}{ampm}"
    except Exception:
        return raw


def _serpapi_search(
    origin: str,
    dest: str,
    outbound: str,
    inbound: str,
    cabin: Cabin,
    max_stops: Optional[int],
    api_key: str,
) -> list[Itinerary]:
    import urllib.request
    import urllib.parse

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": outbound,
        "return_date": inbound,
        "type": "1",                          # round-trip
        "travel_class": str(_CABIN_TO_SERPAPI.get(cabin, 3)),
        "adults": "1",
        "currency": "USD",
        "hl": "en",
        "stops": str(_STOPS_TO_SERPAPI.get(max_stops, 0)),
        "api_key": api_key,
    }
    url = "https://serpapi.com/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "flight-searcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    route = f"{origin}-{dest}"
    itins: list[Itinerary] = []

    for item in data.get("best_flights", []) + data.get("other_flights", []):
        try:
            price = float(item["price"])
        except (KeyError, TypeError, ValueError):
            continue

        flights = item.get("flights", [])
        if not flights:
            continue

        total_dur = item.get("total_duration", 0)
        layovers = item.get("layovers", [])
        stops = len(layovers)

        airlines: list[str] = []
        seen_al: set[str] = set()
        for f in flights:
            al = f.get("airline", "")
            if al and al not in seen_al:
                airlines.append(al)
                seen_al.add(al)

        dep_raw = flights[0].get("departure_airport", {}).get("time", "")
        arr_raw = flights[-1].get("arrival_airport", {}).get("time", "")
        dep_time = _parse_time(dep_raw)
        arr_time = _parse_time(arr_raw)

        layover_airports = [lv.get("id", lv.get("name", "")) for lv in layovers]

        raw_label = json.dumps({
            "price": price, "airlines": airlines,
            "stops": stops, "duration": total_dur,
        })

        itins.append(Itinerary(
            route=route,
            outbound_date=outbound,
            return_date=inbound,
            cabin=cabin,
            price_usd=price,
            stops=stops,
            duration_min=total_dur,
            airlines=airlines,
            dep_time=dep_time,
            arr_time=arr_time,
            day_shift="",
            layover_airports=layover_airports,
            raw_label=raw_label,
        ))

    # Dedup by (price, duration, airlines, stops, dep_time)
    seen: set = set()
    unique: list[Itinerary] = []
    for it in itins:
        sig = (it.price_usd, it.duration_min, tuple(it.airlines), it.stops, it.dep_time)
        if sig not in seen:
            seen.add(sig)
            unique.append(it)

    return unique


# ---------------------------------------------------------------------------
# Original fast-flights / primp backend (fallback)
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r"From\s+([\d,]+)\s+US dollars")
_STOPS_RE = re.compile(r"(\d+)\s+stop", re.I)
_NONSTOP_RE = re.compile(r"Nonstop", re.I)
_DURATION_RE = re.compile(r"Total duration\s+(\d+)\s+hr(?:\s+(\d+)\s+min)?", re.I)
_AIRLINE_RE = re.compile(r"flight with\s+([^.]+?)\.", re.I)
_LAYOVER_RE = re.compile(r"layover at\s+([^.]+?)(?:\s+in\s+[^.]+)?\.", re.I)
_DEP_TIME_RE = re.compile(r"Leaves .+?\s+at\s+([\d:]+\s*[AP]M)", re.I)
_ARR_TIME_RE = re.compile(r"arrives at .+?\s+at\s+([\d:]+\s*[AP]M)\s+on\s+([^.]+)\.", re.I)


def _parse_label(label: str) -> dict:
    out: dict = {}
    m = _PRICE_RE.search(label)
    if m:
        out["price_usd"] = float(m.group(1).replace(",", ""))
    if _NONSTOP_RE.search(label):
        out["stops"] = 0
    else:
        m = _STOPS_RE.search(label)
        if m:
            out["stops"] = int(m.group(1))
    m = _DURATION_RE.search(label)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        out["duration_min"] = h * 60 + mi
    m = _AIRLINE_RE.search(label)
    if m:
        raw = m.group(1).strip()
        out["airlines"] = [a.strip() for a in re.split(r",\s*|\s+and\s+", raw) if a.strip()]
    out["layover_airports"] = [
        m.group(1).strip() for m in _LAYOVER_RE.finditer(label)
    ]
    m = _DEP_TIME_RE.search(label)
    if m:
        out["dep_time"] = m.group(1).replace(" ", "")
    m = _ARR_TIME_RE.search(label)
    if m:
        out["arr_time"] = m.group(1).replace(" ", "")
    return out


import random as _random


def _fetch_html_primp(
    origin: str, dest: str, outbound: str, inbound: str,
    cabin: Cabin, max_stops: Optional[int],
    max_attempts: int = 4,
) -> str:
    from fast_flights.filter import TFSData
    from fast_flights.flights_impl import FlightData, Passengers
    from fast_flights.primp import Client
    from selectolax.lexbor import LexborHTMLParser

    f = TFSData.from_interface(
        flight_data=[
            FlightData(date=outbound, from_airport=origin, to_airport=dest),
            FlightData(date=inbound, from_airport=dest, to_airport=origin),
        ],
        trip="round-trip",
        passengers=Passengers(adults=1),
        seat=cabin,
        max_stops=max_stops,
    )
    params = {"tfs": f.as_b64().decode(), "hl": "en", "tfu": "EgQIABABIgA", "curr": "USD"}
    impersonations = ["chrome_131", "chrome_130", "chrome_129", "chrome_128"]
    last_err: Optional[str] = None
    for attempt in range(max_attempts):
        imp = _random.choice(impersonations)
        client = Client(impersonate=imp, verify=False)
        res = client.get("https://www.google.com/travel/flights", params=params)
        if res.status_code != 200:
            last_err = f"status={res.status_code}"
            time.sleep(1.0 + _random.random())
            continue
        text = res.text
        if text.count("JMc5Xc") >= 10:
            return text
        last_err = f"skeleton response (JMc5Xc={text.count('JMc5Xc')})"
        time.sleep(1.5 + _random.random() * 1.5)
    raise RuntimeError(f"Google Flights fetch failed after {max_attempts} attempts: {last_err}")


def _primp_search(
    origin: str, dest: str, outbound: str, inbound: str,
    cabin: Cabin, max_stops: Optional[int],
    route: str,
) -> list[Itinerary]:
    from selectolax.lexbor import LexborHTMLParser

    html = _fetch_html_primp(origin, dest, outbound, inbound, cabin, max_stops)
    parser = LexborHTMLParser(html)
    itins: list[Itinerary] = []
    for label_node in parser.css("div.JMc5Xc[aria-label]"):
        label = label_node.attributes.get("aria-label") or ""
        parsed = _parse_label(label)
        if "price_usd" not in parsed or "duration_min" not in parsed:
            continue
        itins.append(Itinerary(
            route=route,
            outbound_date=outbound,
            return_date=inbound,
            cabin=cabin,
            price_usd=parsed["price_usd"],
            stops=parsed.get("stops", 0),
            duration_min=parsed["duration_min"],
            airlines=parsed.get("airlines", []),
            dep_time=parsed.get("dep_time", ""),
            arr_time=parsed.get("arr_time", ""),
            day_shift="",
            layover_airports=parsed.get("layover_airports", []),
            raw_label=label,
        ))

    seen: set = set()
    unique: list[Itinerary] = []
    for it in itins:
        sig = (it.price_usd, it.duration_min, tuple(it.airlines), it.stops, it.dep_time)
        if sig not in seen:
            seen.add(sig)
            unique.append(it)
    return unique


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

    # Load .env if present so SERPAPI_KEY is available without shell export.
    _load_dotenv()
    api_key = os.environ.get("SERPAPI_KEY", "").strip()

    backend = "serpapi" if api_key else "primp"
    key_parts = (backend, "v2", route, outbound, inbound, cabin, max_stops)
    key = _cache_key(key_parts)

    conn = _init_cache()
    if use_cache:
        row = conn.execute(
            "SELECT fetched_at, payload FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row and time.time() - row[0] < cache_ttl_s:
            conn.close()
            return [Itinerary(**r) for r in json.loads(row[1])]

    if api_key:
        itins = _serpapi_search(origin, dest, outbound, inbound, cabin, max_stops, api_key)
    else:
        itins = _primp_search(origin, dest, outbound, inbound, cabin, max_stops, route)

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
