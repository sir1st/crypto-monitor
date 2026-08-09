import Anthropic from "@anthropic-ai/sdk";
import type { AiConfig } from "../config";
import type { CompletionRequest, CompletionResult, Provider } from "./types";

/**
 * Anthropic provider.
 *
 * Note there is no temperature knob: current Claude models reject
 * `temperature`, `top_p` and `top_k` with a 400. Reasoning depth is controlled
 * with `output_config.effort` instead, which is what the shared Effort type maps
 * onto.
 */
export function createAnthropicProvider(config: AiConfig): Provider {
  const client = new Anthropic({ apiKey: config.apiKey });

  return {
    name: "anthropic",

    async complete(request: CompletionRequest): Promise<CompletionResult> {
      const params: Anthropic.MessageCreateParamsNonStreaming = {
        model: config.model.id,
        max_tokens: request.maxTokens ?? config.maxOutputTokens,
        messages: [{ role: "user", content: request.prompt }],
        ...(request.system ? { system: request.system } : {}),
        // Adaptive thinking lets the model decide how much to reason per call.
        thinking: { type: "adaptive" },
        ...(config.model.supportsEffort
          ? { output_config: { effort: request.effort ?? config.effort } }
          : {}),
      };

      const response = await client.messages.create(params);

      const usage = {
        inputTokens: response.usage.input_tokens,
        outputTokens: response.usage.output_tokens,
      };

      // Safety classifiers can decline a request: HTTP 200 with empty or partial
      // content. Check before reading content, or this throws on an empty array.
      if (response.stop_reason === "refusal") {
        return {
          text: "",
          refused: true,
          stopReason: response.stop_reason,
          model: response.model,
          provider: "anthropic",
          usage,
        };
      }

      const text = response.content
        .filter((block): block is Anthropic.TextBlock => block.type === "text")
        .map((block) => block.text)
        .join("\n")
        .trim();

      return {
        text,
        refused: false,
        stopReason: response.stop_reason ?? undefined,
        model: response.model,
        provider: "anthropic",
        usage,
      };
    },
  };
}
