# Flight search preferences

You (the agent) are searching for the best **business-class round-trip** flights
for a single adult between London (LHR) and three destinations, departing any
time from **2026-05-01 to 2026-12-20** (i.e. the remainder of 2026). Trip length
for each route is typically **10–21 days**, but shorter/longer windows are fair
game if they surface exceptional value.

## Routes
- `LHR-BLR` — London Heathrow ↔ Bangalore (Bengaluru, India)
- `LHR-ATL` — London Heathrow ↔ Atlanta (USA)
- `LHR-LAX` — London Heathrow ↔ Los Angeles (USA)

## Scoring (lower score = better)
Score is a weighted sum of normalized components:
- **50%** price (USD, round-trip total)
- **25%** total duration
- **15%** stops (nonstop = 0, else penalized)
- **10%** airline quality tier

The orchestrator computes this automatically via `search_lib.score_itineraries`.
The **metric you are optimizing** is the score of the single best itinerary
your strategy surfaces per route. Lower is better.

## What good looks like
- **LHR-BLR**: sub-$2500 business is excellent; $1500–1800 IndiGo/Air India
  deals occasionally surface. Gulf carriers (Qatar, Emirates, Etihad) at
  $2500–3500 are premium sweet spots.
- **LHR-ATL**: direct BA/VS/DL usually $3500–5500; sub-$3500 with a connection
  via Europe can be excellent value.
- **LHR-LAX**: direct BA/VS/AA usually $4500–7000; one-stop via BOS/JFK/ORD/EWR
  sometimes $3000–4000.

## Strategy levers you control (edit strategy.py)
- `date_pairs` — a list of (outbound, return) tuples to query. Cover months you
  haven't sampled yet. Shoulder seasons (May, Sep–Oct) tend to be cheapest.
- `max_stops` — tighter (e.g. 0 or 1) biases to faster itineraries.
- `trip_lengths` — days between outbound and return.
- `notes` — free-text commentary on what you learned from the last run;
  the orchestrator shows these back to you each iteration.

## Good iteration behavior
- On iteration 1, cast a wide net: sample one date pair per month, max_stops=2.
- As you learn which months/stop-counts score well, concentrate samples there.
- Each iteration, either (a) explore a new month/configuration, or (b) exploit
  by densifying samples around your current best. Announce which you're doing
  in `notes`.
- Prefer short `date_pairs` lists (≤ 8 pairs per iteration) — each pair is one
  Google Flights scrape.
