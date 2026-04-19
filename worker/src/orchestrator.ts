import { ROUTES, STOP_AFTER_NO_IMPROVE, DATE_WINDOW_START, DATE_WINDOW_END } from "./preferences";
import { searchRoundTrip } from "./search";
import { scoreItineraries, summarize } from "./score";
import { callClaude } from "./llm";
import {
  readState,
  writeState,
  readStrategy,
  writeStrategy,
  readBestStrategy,
  writeBestStrategy,
  readRunLog,
  appendRunLog,
} from "./state";
import type { Env, Itinerary, RouteOutcome, RouteStrategy, Strategy } from "./types";

export interface RunResult {
  stopped: boolean;
  summary: string;
  fire: number;
  kept: boolean;
  mean: number | null;
}

function baselineStrategy(): Strategy {
  const pairs: [string, string][] = [
    ["2026-05-05", "2026-05-19"],
    ["2026-06-02", "2026-06-16"],
    ["2026-07-07", "2026-07-21"],
    ["2026-08-04", "2026-08-18"],
    ["2026-09-01", "2026-09-15"],
    ["2026-10-06", "2026-10-20"],
    ["2026-11-03", "2026-11-17"],
    ["2026-12-01", "2026-12-15"],
  ];
  const note = "Iter 0: EXPLORE — monthly baseline sweep, 14d trips.";
  const rs = (): RouteStrategy => ({
    date_pairs: pairs.map((p) => [p[0], p[1]] as [string, string]),
    max_stops: 2,
    notes: note,
  });
  return { "LHR-BLR": rs(), "LHR-ATL": rs(), "LHR-LAX": rs() };
}

function isValidDate(d: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return false;
  return d >= DATE_WINDOW_START && d <= DATE_WINDOW_END;
}

function validateStrategy(s: Strategy): void {
  const want = Object.keys(ROUTES);
  for (const r of want) {
    const rs = s[r];
    if (!rs) throw new Error(`missing route ${r}`);
    if (!Array.isArray(rs.date_pairs) || rs.date_pairs.length === 0 || rs.date_pairs.length > 8) {
      throw new Error(`${r}: date_pairs must be 1..8 (got ${rs.date_pairs?.length})`);
    }
    for (const pair of rs.date_pairs) {
      if (!Array.isArray(pair) || pair.length !== 2) throw new Error(`${r}: bad pair shape`);
      const [a, b] = pair;
      if (!isValidDate(a) || !isValidDate(b)) {
        throw new Error(`${r}: date pair ${a}/${b} outside ${DATE_WINDOW_START}..${DATE_WINDOW_END}`);
      }
      if (a > b) throw new Error(`${r}: outbound ${a} after return ${b}`);
    }
    if (![0, 1, 2].includes(rs.max_stops)) {
      throw new Error(`${r}: max_stops must be 0/1/2 (got ${rs.max_stops})`);
    }
  }
}

async function scrapeRoute(
  env: Env,
  route: string,
  rs: RouteStrategy,
): Promise<{ pool: Itinerary[]; errors: string[] }> {
  const [origin, dest] = ROUTES[route];
  const results = await Promise.allSettled(
    rs.date_pairs.map(([ob, ib]) =>
      searchRoundTrip(env, origin, dest, ob, ib, "business", rs.max_stops),
    ),
  );
  const pool: Itinerary[] = [];
  const errors: string[] = [];
  for (let i = 0; i < results.length; i++) {
    const r = results[i];
    const [ob, ib] = rs.date_pairs[i];
    if (r.status === "fulfilled") pool.push(...r.value);
    else errors.push(`${ob}→${ib}: ${String(r.reason).slice(0, 140)}`);
  }
  return { pool, errors };
}

export async function runOnce(env: Env): Promise<RunResult> {
  const state = await readState(env);
  if (state.stopped) {
    return {
      stopped: true,
      summary: "stopped — streak hit threshold; POST /resume to continue",
      fire: state.fire_count,
      kept: false,
      mean: null,
    };
  }

  let strategy = await readStrategy(env);
  if (!strategy) {
    strategy = baselineStrategy();
    await writeStrategy(env, strategy);
  }

  // Scrape all 3 routes in parallel.
  const routeNames = Object.keys(ROUTES);
  const scrapes = await Promise.all(
    routeNames.map((r) => scrapeRoute(env, r, strategy![r])),
  );

  // Score per route.
  const perRouteBest: Record<string, RouteOutcome> = {};
  const bestScores: number[] = [];
  for (let i = 0; i < routeNames.length; i++) {
    const route = routeNames[i];
    const { pool, errors } = scrapes[i];
    const scored = scoreItineraries(pool);
    if (scored.length === 0) {
      perRouteBest[route] = { best_score: null, best_summary: null, n: 0, errors };
    } else {
      const [s, it] = scored[0];
      perRouteBest[route] = {
        best_score: s,
        best_summary: summarize(it),
        n: scored.length,
        errors,
      };
      bestScores.push(s);
    }
  }

  const mean =
    bestScores.length === routeNames.length
      ? bestScores.reduce((a, b) => a + b, 0) / bestScores.length
      : null;

  // Keep-or-revert.
  let kept = false;
  let strategyForNextFire = strategy;
  if (mean !== null) {
    if (state.best_mean === null || mean < state.best_mean) {
      state.best_mean = mean;
      state.no_improve_streak = 0;
      state.best_summary_per_route = Object.fromEntries(
        Object.entries(perRouteBest).map(([r, v]) => [r, v.best_summary ?? ""]),
      );
      await writeBestStrategy(env, strategy);
      kept = true;
    } else {
      state.no_improve_streak += 1;
      const best = await readBestStrategy(env);
      if (best) strategyForNextFire = best;
    }
  } else {
    state.no_improve_streak += 1;
  }
  state.fire_count += 1;

  // Build summary text for the LLM + caller.
  const lines: string[] = [];
  lines.push(
    `Fire #${state.fire_count}: kept=${kept} mean=${mean === null ? "n/a" : mean.toFixed(3)} streak=${state.no_improve_streak}`,
  );
  for (const route of routeNames) {
    const r = perRouteBest[route];
    if (r.best_summary) {
      lines.push(`  ${route} (pool=${r.n}): ${r.best_summary}`);
    } else {
      lines.push(`  ${route}: no results (errors=${r.errors.length})`);
    }
    if (r.errors.length) {
      lines.push(`    errors: ${r.errors.slice(0, 2).join("; ")}`);
    }
  }
  const summaryText = lines.join("\n");

  // Stop check.
  if (state.no_improve_streak >= STOP_AFTER_NO_IMPROVE) {
    state.stopped = true;
    await writeState(env, state);
    await appendRunLog(env, {
      fire: state.fire_count,
      ts: new Date().toISOString(),
      kept,
      mean,
      per_route: perRouteBest,
      strategy_notes: Object.fromEntries(
        Object.entries(strategy).map(([r, s]) => [r, s.notes]),
      ),
      llm_note: "STOP — no-improve streak hit threshold.",
    });
    return {
      stopped: true,
      summary: summaryText + "\nSTOPPED.",
      fire: state.fire_count,
      kept,
      mean,
    };
  }

  // Ask LLM for next strategy.
  const recentLog = await readRunLog(env);
  let llmNote = "";
  try {
    const { strategy: nextStrategy, note } = await callClaude(
      env,
      state,
      strategyForNextFire,
      summaryText,
      recentLog,
    );
    validateStrategy(nextStrategy);
    await writeStrategy(env, nextStrategy);
    llmNote = note;
  } catch (e) {
    // LLM failed — keep strategyForNextFire (reverted-best or current) for next fire.
    await writeStrategy(env, strategyForNextFire);
    llmNote = `LLM call failed: ${String(e).slice(0, 160)}`;
  }

  await writeState(env, state);
  await appendRunLog(env, {
    fire: state.fire_count,
    ts: new Date().toISOString(),
    kept,
    mean,
    per_route: perRouteBest,
    strategy_notes: Object.fromEntries(
      Object.entries(strategy).map(([r, s]) => [r, s.notes]),
    ),
    llm_note: llmNote,
  });

  return {
    stopped: false,
    summary: summaryText + `\nnext: ${llmNote}`,
    fire: state.fire_count,
    kept,
    mean,
  };
}
