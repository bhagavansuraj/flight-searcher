import type { Env, State, RunLogEntry } from "./types";

const K_STATE = "state";
const K_AGENT_NOTES = "agent_notes";
const K_BEST_AGENT_NOTES = "best_agent_notes";
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
      running: false,
    };
  }
  return JSON.parse(raw);
}

export async function writeState(env: Env, s: State): Promise<void> {
  await env.STATE.put(K_STATE, JSON.stringify(s));
}

export async function readAgentNotes(env: Env): Promise<string> {
  return (await env.STATE.get(K_AGENT_NOTES)) ?? "";
}

export async function writeAgentNotes(env: Env, notes: string): Promise<void> {
  await env.STATE.put(K_AGENT_NOTES, notes);
}

export async function readBestAgentNotes(env: Env): Promise<string> {
  return (await env.STATE.get(K_BEST_AGENT_NOTES)) ?? "";
}

export async function writeBestAgentNotes(env: Env, notes: string): Promise<void> {
  await env.STATE.put(K_BEST_AGENT_NOTES, notes);
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
