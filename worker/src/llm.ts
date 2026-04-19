import { AGENT_SYSTEM_PROMPT, BUDGET_NUDGE_AT, MAX_AGENT_CALLS } from "./preferences";
import { TOOL_DEFINITIONS, dispatchTool, newSession } from "./tools";
import type { AgentSession } from "./tools";
import type { Env, Itinerary, RunLogEntry, State } from "./types";

export interface AgentLoopResult {
  session: AgentSession;
  turns: number;
}

// ---------------------------------------------------------------------------
// Low-level Anthropic call
// ---------------------------------------------------------------------------

async function callMessages(env: Env, messages: any[], tools: any[]): Promise<any> {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-6",
      max_tokens: 4096,
      system: AGENT_SYSTEM_PROMPT,
      tools,
      messages,
    }),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`anthropic ${res.status}: ${t.slice(0, 300)}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Multi-turn agent loop
// ---------------------------------------------------------------------------

export async function runAgentLoop(
  env: Env,
  state: State,
  agentNotes: string,
  recentLog: RunLogEntry[],
): Promise<AgentLoopResult> {
  const session = newSession(MAX_AGENT_CALLS);

  // Build initial context message.
  const bestLines = Object.entries(state.best_summary_per_route).map(
    ([r, s]) => `  ${r}: ${s}`,
  );
  const recentLines = recentLog.slice(-5).map((e) => {
    const kept = e.kept ? "✓" : "✗";
    const mean = e.mean !== null ? e.mean.toFixed(4) : "n/a";
    return `  #${e.fire} ${kept} mean=${mean}  ${(e.agent_notes ?? e.llm_note ?? "").slice(0, 100)}`;
  });

  const initialMessage = [
    `Fire #${state.fire_count + 1} — ${MAX_AGENT_CALLS} searches available.`,
    ``,
    `CURRENT ALL-TIME BESTS${state.best_mean !== null ? ` (mean ${state.best_mean.toFixed(4)}, streak ${state.no_improve_streak})` : " (none yet)"}:`,
    bestLines.length ? bestLines.join("\n") : "  (none yet — first fire or all reverted)",
    ``,
    `LAST AGENT'S NOTES:`,
    agentNotes || "  (none — this may be an early fire)",
    ``,
    `RECENT FIRE HISTORY:`,
    recentLines.length ? recentLines.join("\n") : "  (none)",
    ``,
    `Search now. Use done() when finished — leave notes for the next agent.`,
  ].join("\n");

  const messages: any[] = [{ role: "user", content: initialMessage }];

  let turns = 0;
  const MAX_TURNS = 50; // safety ceiling on message pairs

  while (turns < MAX_TURNS) {
    const response = await callMessages(env, messages, TOOL_DEFINITIONS);
    turns++;

    // Append assistant message.
    messages.push({ role: "assistant", content: response.content });

    // Collect tool calls.
    const toolUseBlocks = (response.content as any[]).filter((b) => b.type === "tool_use");

    if (toolUseBlocks.length === 0) {
      // No tool calls — agent finished without calling done() (rare). Exit.
      break;
    }

    // Execute tools and collect results.
    const toolResults: any[] = [];
    for (const block of toolUseBlocks) {
      const result = await dispatchTool(block.name, block.input ?? {}, session, env);
      toolResults.push({
        type: "tool_result",
        tool_use_id: block.id,
        content: result,
      });
      if (session.done) break; // stop executing further tools once done() called
    }

    messages.push({ role: "user", content: toolResults });

    if (session.done) break;

    // Budget nudge.
    if (
      session.searchesUsed >= session.budget - BUDGET_NUDGE_AT &&
      session.searchesUsed < session.budget
    ) {
      const remaining = session.budget - session.searchesUsed;
      messages.push({
        role: "user",
        content: `${remaining} search${remaining === 1 ? "" : "es"} remaining. Wrap up and call done() soon.`,
      });
    }

    // Budget exhausted — force done.
    if (session.searchesUsed >= session.budget) {
      messages.push({
        role: "user",
        content: "Budget exhausted. Call done() now with your findings.",
      });
    }
  }

  return { session, turns };
}
