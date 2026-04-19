import { PREFERENCES_PROMPT } from "./preferences";
import type { Env, RunLogEntry, State, Strategy } from "./types";

export interface LlmResult {
  strategy: Strategy;
  note: string;
}

const ROUTE_SCHEMA = {
  type: "object",
  required: ["date_pairs", "max_stops", "notes"],
  properties: {
    date_pairs: {
      type: "array",
      minItems: 1,
      maxItems: 8,
      items: {
        type: "array",
        minItems: 2,
        maxItems: 2,
        items: { type: "string", pattern: "^2026-\\d{2}-\\d{2}$" },
      },
    },
    max_stops: { type: "integer", enum: [0, 1, 2] },
    notes: { type: "string" },
  },
};

const TOOL = {
  name: "emit_strategy",
  description: "Emit the strategy for the next fire.",
  input_schema: {
    type: "object",
    required: ["strategy", "note"],
    properties: {
      note: {
        type: "string",
        description: "One short sentence: what you learned from the just-ran fire and what the new strategy probes next.",
      },
      strategy: {
        type: "object",
        required: ["LHR-BLR", "LHR-ATL", "LHR-LAX"],
        properties: {
          "LHR-BLR": ROUTE_SCHEMA,
          "LHR-ATL": ROUTE_SCHEMA,
          "LHR-LAX": ROUTE_SCHEMA,
        },
      },
    },
  },
};

export async function callClaude(
  env: Env,
  state: State,
  currentStrategy: Strategy | null,
  justRanSummary: string,
  recentLog: RunLogEntry[],
): Promise<LlmResult> {
  const bestPerRoute = Object.entries(state.best_summary_per_route)
    .map(([r, s]) => `  ${r}: ${s || "(none yet)"}`)
    .join("\n");

  const recent = recentLog
    .slice(-10)
    .map(
      (e) =>
        `  #${e.fire} kept=${e.kept} mean=${e.mean === null ? "n/a" : e.mean.toFixed(3)} | ${e.llm_note}`,
    )
    .join("\n");

  const userContent = [
    `Fire #${state.fire_count} just finished. Time to decide the strategy for fire #${state.fire_count + 1}.`,
    ``,
    `Persistent best mean: ${state.best_mean === null ? "n/a" : state.best_mean.toFixed(3)} (no-improve streak: ${state.no_improve_streak}).`,
    `Per-route best summary so far:`,
    bestPerRoute || "  (nothing yet)",
    ``,
    `Just-ran fire result:`,
    justRanSummary,
    ``,
    `Recent fire history (oldest first):`,
    recent || "  (none)",
    ``,
    `The strategy that just ran (base your next moves on this — exploit winners, explore gaps):`,
    currentStrategy ? JSON.stringify(currentStrategy, null, 2) : "(none)",
    ``,
    `Emit the strategy for the next fire. ≤8 pairs per route, dates in 2026-05-01..2026-12-20.`,
  ].join("\n");

  const body = {
    model: "claude-sonnet-4-6",
    max_tokens: 4096,
    system: PREFERENCES_PROMPT,
    tools: [TOOL],
    tool_choice: { type: "tool", name: "emit_strategy" },
    messages: [{ role: "user", content: userContent }],
  };

  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`anthropic ${res.status}: ${t.slice(0, 300)}`);
  }
  const data = (await res.json()) as any;
  const toolUse = data.content?.find(
    (c: any) => c.type === "tool_use" && c.name === "emit_strategy",
  );
  if (!toolUse) throw new Error("anthropic returned no emit_strategy tool_use");
  return toolUse.input as LlmResult;
}
