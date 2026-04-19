import type { Cabin, Env, Itinerary } from "./types";

const CABIN_TO_SERPAPI: Record<Cabin, number> = {
  economy: 1,
  "premium-economy": 2,
  business: 3,
  first: 4,
};

// Our max_stops cap → SerpAPI stops param (0=any, 1=nonstop, 2=≤1, 3=≤2).
function stopsToSerpApi(maxStops: number): number {
  if (maxStops === 0) return 1;
  if (maxStops === 1) return 2;
  if (maxStops === 2) return 3;
  return 0;
}

export async function searchRoundTrip(
  env: Env,
  origin: string,
  dest: string,
  outbound: string,
  inbound: string,
  cabin: Cabin,
  maxStops: number,
): Promise<Itinerary[]> {
  const params = new URLSearchParams({
    engine: "google_flights",
    departure_id: origin,
    arrival_id: dest,
    outbound_date: outbound,
    return_date: inbound,
    type: "1",
    travel_class: String(CABIN_TO_SERPAPI[cabin] ?? 3),
    adults: "1",
    currency: "USD",
    hl: "en",
    stops: String(stopsToSerpApi(maxStops)),
    api_key: env.SERPAPI_KEY,
  });
  const res = await fetch("https://serpapi.com/search?" + params.toString());
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`serpapi http ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = (await res.json()) as any;
  if (data.error) throw new Error(`serpapi error: ${data.error}`);
  return parseItineraries(data, origin, dest, outbound, inbound, cabin);
}

function parseItineraries(
  data: any,
  origin: string,
  dest: string,
  outbound: string,
  inbound: string,
  cabin: Cabin,
): Itinerary[] {
  const items = [
    ...((data.best_flights as any[]) || []),
    ...((data.other_flights as any[]) || []),
  ];
  const route = `${origin}-${dest}`;
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
      outbound_date: outbound,
      return_date: inbound,
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
