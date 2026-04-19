import type { Env, State, Strategy, RunLogEntry } from "./types";

const K_STATE = "state";
const K_STRATEGY = "strategy";
const K_BEST_STRATEGY = "best_strategy";
const K_RUN_LOG = "run_log";
const RUN_LOG_CAP = 50;

export async function readState(env: Env): Promise<State> {
  const raw = await env.STATE.get(K_STATE);
  if (!raw) {
    return {
      fire_count: 0,
      best_mean: null,
      no_improve_streak: 0,
      best_summary_per_route: {},
      stopped: false,
    };
  }
  return JSON.parse(raw);
}

export async function writeState(env: Env, s: State): Promise<void> {
  await env.STATE.put(K_STATE, JSON.stringify(s));
}

export async function readStrategy(env: Env): Promise<Strategy | null> {
  const raw = await env.STATE.get(K_STRATEGY);
  return raw ? JSON.parse(raw) : null;
}

export async function writeStrategy(env: Env, s: Strategy): Promise<void> {
  await env.STATE.put(K_STRATEGY, JSON.stringify(s));
}

export async function readBestStrategy(env: Env): Promise<Strategy | null> {
  const raw = await env.STATE.get(K_BEST_STRATEGY);
  return raw ? JSON.parse(raw) : null;
}

export async function writeBestStrategy(env: Env, s: Strategy): Promise<void> {
  await env.STATE.put(K_BEST_STRATEGY, JSON.stringify(s));
}

export async function readRunLog(env: Env): Promise<RunLogEntry[]> {
  const raw = await env.STATE.get(K_RUN_LOG);
  return raw ? JSON.parse(raw) : [];
}

export async function appendRunLog(env: Env, entry: RunLogEntry): Promise<void> {
  const log = await readRunLog(env);
  log.push(entry);
  while (log.length > RUN_LOG_CAP) log.shift();
  await env.STATE.put(K_RUN_LOG, JSON.stringify(log));
}
