import type { Itinerary } from "./types";

export const WEIGHTS = {
  price: 0.50,
  duration: 0.25,
  stops: 0.15,
  airline_quality: 0.10,
};

const AIRLINE_TIER: Record<string, number> = {
  "Qatar Airways": 1.0,
  "Singapore Airlines": 1.0,
  "Emirates": 0.95,
  "ANA": 0.95,
  "Japan Airlines": 0.95,
  "Cathay Pacific": 0.9,
  "Etihad Airways": 0.9,
  "Virgin Atlantic": 0.85,
  "British Airways": 0.8,
  "Lufthansa": 0.8,
  "Swiss": 0.8,
  "KLM": 0.75,
  "Air France": 0.75,
  "Turkish Airlines": 0.75,
  "Finnair": 0.7,
  "Delta": 0.75,
  "American": 0.65,
  "United": 0.65,
  "Air India": 0.55,
  "IndiGo": 0.4,
  "Vistara": 0.7,
  "Air Canada": 0.7,
  "Iberia": 0.65,
};

function airlineScore(airlines: string[]): number {
  if (airlines.length === 0) return 0.5;
  const sum = airlines.reduce((acc, a) => acc + (AIRLINE_TIER[a] ?? 0.55), 0);
  return sum / airlines.length;
}

export function scoreItineraries(itins: Itinerary[]): Array<[number, Itinerary]> {
  if (itins.length === 0) return [];
  const minPrice = Math.min(...itins.map((i) => i.price_usd));
  const minDur = Math.min(...itins.map((i) => i.duration_min));
  const scored: Array<[number, Itinerary]> = itins.map((it) => {
    const priceC = (it.price_usd - minPrice) / Math.max(minPrice, 1);
    const durC = (it.duration_min - minDur) / Math.max(minDur, 1);
    const stopsC = Math.min(it.stops, 3) / 3;
    const airlineC = 1 - airlineScore(it.airlines);
    const s =
      WEIGHTS.price * priceC +
      WEIGHTS.duration * durC +
      WEIGHTS.stops * stopsC +
      WEIGHTS.airline_quality * airlineC;
    return [s, it];
  });
  scored.sort((a, b) => a[0] - b[0]);
  return scored;
}

export function summarize(it: Itinerary): string {
  const d = it.duration_min;
  const dur = `${Math.floor(d / 60)}h${String(d % 60).padStart(2, "0")}m`;
  const al = it.airlines.join("/") || "?";
  const lay = it.layover_airports.length ? ` via ${it.layover_airports.join(",")}` : "";
  return `$${it.price_usd.toFixed(0)} | ${it.stops}st | ${dur} | ${al}${lay} | ${it.dep_time}→${it.arr_time} | ${it.outbound_date}/${it.return_date}`;
}
