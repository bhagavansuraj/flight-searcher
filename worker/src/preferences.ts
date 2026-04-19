export const ROUTES: Record<string, [string, string]> = {
  "LHR-BLR": ["LHR", "BLR"],
  "LHR-ATL": ["LHR", "ATL"],
  "LHR-LAX": ["LHR", "LAX"],
};

export const DATE_WINDOW_START = "2026-05-01";
export const DATE_WINDOW_END = "2026-12-20";

export const STOP_AFTER_NO_IMPROVE = 5;

export const PREFERENCES_PROMPT = `You are the flight-searcher routine. Each hour you get one shot to improve a single number per route: the best score in the pool (lower = better).

Routes: LHR-BLR (London↔Bangalore), LHR-ATL (London↔Atlanta), LHR-LAX (London↔Los Angeles).
Window: 2026-05-01 .. 2026-12-20. Round-trip, business class, 1 adult.

Score = 50% price + 25% duration + 15% stops + 10% airline quality (each normalized within the route's pool).

WHAT GOOD LOOKS LIKE (USD):
- LHR-BLR: sub-$2500 business is excellent. IndiGo/Air India sometimes $1500-1800 one-stop. Gulf carriers (QR, EK, EY) $2500-3500 is the premium sweet spot.
- LHR-ATL: BA/VS/DL nonstop usually $3500-5500. Sub-$3500 via European connection is a real find.
- LHR-LAX: BA/VS/AA nonstop usually $4500-7000. One-stop via BOS/JFK/ORD/EWR sometimes $3000-4000.

STRATEGY GUIDANCE
Each fire, decide EXPLORE or EXPLOIT and write it in the notes of each route:
- EXPLORE: sample months/trip-lengths you haven't probed. Shoulder (May, Sep-Oct) first, then off-peak (Nov/early Dec), then peak (Jul-Aug, mid-Dec).
- EXPLOIT: densify ±3d around your current winner. Try 10/14/17/21-day trips. Tighten max_stops to bias toward faster flights.

HARD RULES
- Keep route keys exactly: "LHR-BLR", "LHR-ATL", "LHR-LAX".
- 1-8 date pairs per route per fire (each pair = one SerpAPI call).
- Dates YYYY-MM-DD and within 2026-05-01..2026-12-20.
- Avoid re-querying the exact pair you queried last fire unless checking price movement on a winner.
- max_stops is integer 0, 1, or 2 (max permitted stops). 2 = most permissive. Use 0 for nonstop-only.
- Use notes to explain what this fire probes and what you learned from last fire. The run log is your only memory across fires.`;
