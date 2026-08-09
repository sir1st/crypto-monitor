import OpenAI from "openai";
import type { AiConfig, Effort } from "../config";
import type { CompletionRequest, CompletionResult, Provider } from "./types";

/**
 * OpenAI provider.
 *
 * Current reasoning models take `max_completion_tokens` (not `max_tokens`) and
 * reject `temperature`, so neither is sent. Effort maps onto `reasoning_effort`.
 */
export function createOpenAiProvider(config: AiConfig): Provider {
  const client = new OpenAI({ apiKey: config.apiKey });

  // OpenAI has no "xhigh"; fold it into the nearest supported level.
  const reasoningEffort = (effort: Effort) => (effort === "xhigh" ? "high" : effort);

  return {
    name: "openai",

    async complete(request: CompletionRequest): Promise<CompletionResult> {
      const messages: OpenAI.Chat.ChatCompletionMessageParam[] = [];
      if (request.system) messages.push({ role: "system", content: request.system });
      messages.push({ role: "user", content: request.prompt });

      const params: Record<string, unknown> = {
        model: config.model.id,
        messages,
        max_completion_tokens: request.maxTokens ?? config.maxOutputTokens,
      };

      if (config.model.supportsEffort) {
        params.reasoning_effort = reasoningEffort(request.effort ?? config.effort);
      }

      const response = await client.chat.completions.create(
        params as unknown as OpenAI.Chat.ChatCompletionCreateParamsNonStreaming,
      );

      const choice = response.choices[0];
      const refused = choice?.finish_reason === "content_filter";

      return {
        text: refused ? "" : (choice?.message?.content ?? "").trim(),
        refused,
        stopReason: choice?.finish_reason ?? undefined,
        model: response.model,
        provider: "openai",
        usage: {
          inputTokens: response.usage?.prompt_tokens ?? 0,
          outputTokens: response.usage?.completion_tokens ?? 0,
        },
      };
    },
  };
}
