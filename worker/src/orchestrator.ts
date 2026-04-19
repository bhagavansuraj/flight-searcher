import { ROUTES, STOP_AFTER_NO_IMPROVE } from "./preferences";
import { scoreItineraries, summarize } from "./score";
import { runAgentLoop } from "./llm";
import {
  readState,
  writeState,
  readAgentNotes,
  writeAgentNotes,
  writeBestAgentNotes,
  readRunLog,
  appendRunLog,
} from "./state";
import type { Env, RouteOutcome } from "./types";

export interface RunResult {
  stopped: boolean;
  summary: string;
  fire: number;
  kept: boolean;
  mean: number | null;
  searches: number;
  turns: number;
}

export async function runAgent(env: Env): Promise<RunResult> {
  const state = await readState(env);

  if (state.stopped) {
    return {
      stopped: true,
      summary: "stopped — streak hit threshold; POST /resume to continue",
      fire: state.fire_count,
      kept: false,
      mean: null,
      searches: 0,
      turns: 0,
    };
  }

  // Mark fire as in-progress so the TUI can show a spinner.
  state.running = true;
  await writeState(env, state);

  const [agentNotes, recentLog] = await Promise.all([readAgentNotes(env), readRunLog(env)]);

  // Run the agent loop.
  let loopResult;
  try {
    loopResult = await runAgentLoop(env, state, agentNotes, recentLog);
  } catch (e) {
    state.running = false;
    state.fire_count += 1;
    state.no_improve_streak += 1;
    await writeState(env, state);
    const errMsg = `Agent loop failed: ${String(e).slice(0, 200)}`;
    await appendRunLog(env, {
      fire: state.fire_count,
      ts: new Date().toISOString(),
      kept: false,
      mean: null,
      per_route: {},
      llm_note: errMsg,
    });
    return { stopped: false, summary: errMsg, fire: state.fire_count, kept: false, mean: null, searches: 0, turns: 0 };
  }

  const { session, turns } = loopResult;

  // Score each route's accumulated pool.
  const routeNames = Object.keys(ROUTES);
  const perRouteBest: Record<string, RouteOutcome> = {};
  const bestScores: number[] = [];

  for (const route of routeNames) {
    const pool = session.pool[route] ?? [];
    const scored = scoreItineraries(pool);
    if (scored.length === 0) {
      perRouteBest[route] = { best_score: null, best_summary: null, n: 0, errors: [] };
    } else {
      const [s, it] = scored[0];
      perRouteBest[route] = {
        best_score: s,
        best_summary: summarize(it),
        n: scored.length,
        errors: [],
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
  if (mean !== null) {
    if (state.best_mean === null || mean < state.best_mean) {
      state.best_mean = mean;
      state.no_improve_streak = 0;
      state.best_summary_per_route = Object.fromEntries(
        Object.entries(perRouteBest).map(([r, v]) => [r, v.best_summary ?? ""]),
      );
      kept = true;
      // Persist the winning agent's notes as the all-time best notes.
      if (session.doneNotes) await writeBestAgentNotes(env, session.doneNotes);
    } else {
      state.no_improve_streak += 1;
    }
  } else {
    state.no_improve_streak += 1;
  }

  state.fire_count += 1;
  state.running = false;

  // Persist agent notes for next fire.
  if (session.doneNotes) await writeAgentNotes(env, session.doneNotes);

  // Build summary.
  const lines: string[] = [
    `Fire #${state.fire_count}: kept=${kept} mean=${mean === null ? "n/a" : mean.toFixed(4)} streak=${state.no_improve_streak} searches=${session.searchesUsed} turns=${turns}`,
  ];
  for (const route of routeNames) {
    const r = perRouteBest[route];
    if (r.best_summary) {
      lines.push(`  ${route} (pool=${r.n}): ${r.best_summary}`);
    } else {
      lines.push(`  ${route}: no results`);
    }
  }
  if (session.doneSummary) lines.push(`  agent: ${session.doneSummary}`);
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
      llm_note: "STOP — no-improve streak hit threshold.",
      agent_notes: session.doneNotes,
      agent_searches: session.searchesUsed,
      agent_turns: turns,
    });
    return { stopped: true, summary: summaryText + "\nSTOPPED.", fire: state.fire_count, kept, mean, searches: session.searchesUsed, turns };
  }

  await writeState(env, state);
  await appendRunLog(env, {
    fire: state.fire_count,
    ts: new Date().toISOString(),
    kept,
    mean,
    per_route: perRouteBest,
    llm_note: session.doneSummary || "(no done() summary)",
    agent_notes: session.doneNotes,
    agent_searches: session.searchesUsed,
    agent_turns: turns,
  });

  return { stopped: false, summary: summaryText, fire: state.fire_count, kept, mean, searches: session.searchesUsed, turns };
}
