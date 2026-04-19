// Proxies POST /search requests to SerpAPI's google_flights engine and
// returns parsed itineraries in the Python routine's Itinerary schema.
//
// Secrets (set via `wrangler secret put`):
//   SERPAPI_KEY  — your SerpAPI key
//   AUTH_TOKEN   — shared bearer token so randos can't drain our SerpAPI quota

export interface Env {
  SERPAPI_KEY: string;
  AUTH_TOKEN: string;
}

type Cabin = "economy" | "premium-economy" | "business" | "first";

interface SearchReq {
  origin: string;           // IATA e.g. "LHR"
  dest: string;             // IATA e.g. "BLR"
  outbound: string;         // "YYYY-MM-DD"
  inbound: string;          // "YYYY-MM-DD"
  cabin?: Cabin;            // default "business"
  max_stops?: number | null;
}

interface Itinerary {
  route: string;
  outbound_date: string;
  return_date: string;
  cabin: string;
  price_usd: number;
  stops: number;
  duration_min: number;
  airlines: string[];
  dep_time: string;
  arr_time: string;
  day_shift: string;
  layover_airports: string[];
  raw_label: string;
}

const CABIN_TO_SERPAPI: Record<Cabin, number> = {
  "economy": 1,
  "premium-economy": 2,
  "business": 3,
  "first": 4,
};

// max_stops (routine) → SerpAPI stops param (0=any, 1=nonstop, 2=≤1, 3=≤2)
function stopsToSerpApi(max: number | null | undefined): number {
  if (max === null || max === undefined) return 0;
  if (max === 0) return 1;
  if (max === 1) return 2;
  if (max === 2) return 3;
  return 0;
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, ts: Date.now() });
    }

    if (req.method !== "POST" || url.pathname !== "/search") {
      return new Response("Not found", { status: 404 });
    }

    const auth = req.headers.get("authorization") || "";
    if (auth !== `Bearer ${env.AUTH_TOKEN}`) {
      return new Response("Unauthorized", { status: 401 });
    }

    let body: SearchReq;
    try {
      body = (await req.json()) as SearchReq;
    } catch {
      return json({ error: "invalid_json" }, 400);
    }

    const missing = ["origin", "dest", "outbound", "inbound"].filter(
      (k) => !(body as any)[k]
    );
    if (missing.length) {
      return json({ error: "missing_fields", fields: missing }, 400);
    }

    const cabin: Cabin = body.cabin || "business";

    const params = new URLSearchParams({
      engine: "google_flights",
      departure_id: body.origin,
      arrival_id: body.dest,
      outbound_date: body.outbound,
      return_date: body.inbound,
      type: "1", // round-trip
      travel_class: String(CABIN_TO_SERPAPI[cabin] ?? 3),
      adults: "1",
      currency: "USD",
      hl: "en",
      stops: String(stopsToSerpApi(body.max_stops ?? null)),
      api_key: env.SERPAPI_KEY,
    });

    const serpUrl = "https://serpapi.com/search?" + params.toString();
    const serpRes = await fetch(serpUrl);
    if (!serpRes.ok) {
      const text = await serpRes.text();
      return json(
        { error: "serpapi_error", status: serpRes.status, body: text.slice(0, 400) },
        502
      );
    }

    const data = (await serpRes.json()) as any;
    if (data.error) {
      return json({ error: "serpapi_error", detail: data.error }, 502);
    }

    const itineraries = parseItineraries(data, body, cabin);
    return json({
      route: `${body.origin}-${body.dest}`,
      n: itineraries.length,
      itineraries,
    });
  },
};

function parseItineraries(data: any, req: SearchReq, cabin: Cabin): Itinerary[] {
  const items = [
    ...((data.best_flights as any[]) || []),
    ...((data.other_flights as any[]) || []),
  ];
  const route = `${req.origin}-${req.dest}`;
  const seen = new Set<string>();
  const out: Itinerary[] = [];

  for (const item of items) {
    const price = Number(item.price);
    if (!Number.isFinite(price) || price <= 0) continue;

    const flights: any[] = item.flights || [];
    if (flights.length === 0) continue;

    const layovers: any[] = item.layovers || [];
    const stops = layovers.length;

    const airlines: string[] = [];
    const seenAl = new Set<string>();
    for (const f of flights) {
      const al = (f.airline || "").trim();
      if (al && !seenAl.has(al)) {
        airlines.push(al);
        seenAl.add(al);
      }
    }

    const depRaw = flights[0]?.departure_airport?.time || "";
    const arrRaw = flights[flights.length - 1]?.arrival_airport?.time || "";
    const depTime = formatTime(depRaw);
    const arrTime = formatTime(arrRaw);

    const layoverAirports = layovers.map((lv) => lv.id || lv.name || "");
    const duration = Number(item.total_duration || 0);

    const sig = `${price}|${duration}|${airlines.join(",")}|${stops}|${depTime}`;
    if (seen.has(sig)) continue;
    seen.add(sig);

    out.push({
      route,
      outbound_date: req.outbound,
      return_date: req.inbound,
      cabin,
      price_usd: price,
      stops,
      duration_min: duration,
      airlines,
      dep_time: depTime,
      arr_time: arrTime,
      day_shift: "",
      layover_airports: layoverAirports,
      raw_label: JSON.stringify({ price, airlines, stops, duration }),
    });
  }

  return out;
}

function formatTime(raw: string): string {
  // "2026-09-01 08:30" → "8:30AM"
  if (!raw) return "";
  const parts = raw.split(" ");
  if (parts.length < 2) return raw;
  const [hs, ms] = parts[1].split(":");
  let h = parseInt(hs, 10);
  const m = parseInt(ms, 10);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return raw;
  const ampm = h < 12 ? "AM" : "PM";
  h = h % 12 || 12;
  return `${h}:${String(m).padStart(2, "0")}${ampm}`;
}

function json(body: any, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
