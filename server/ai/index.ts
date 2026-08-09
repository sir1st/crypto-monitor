import {
  AiConfigError,
  estimateCost,
  isAiConfigured,
  listModels,
  resolveAiConfig,
  type AiConfig,
  type Effort,
} from "./config";
import { createAnthropicProvider } from "./providers/anthropic";
import { createOpenAiProvider } from "./providers/openai";
import type { CompletionRequest, CompletionResult, Provider } from "./providers/types";

export { AiConfigError, isAiConfigured, listModels, resolveAiConfig };
export type { AiConfig, CompletionRequest, CompletionResult, Effort, Provider };

/** Builds the provider client for a resolved config. */
export function createProvider(config: AiConfig): Provider {
  switch (config.model.provider) {
    case "anthropic":
      return createAnthropicProvider(config);
    case "openai":
      return createOpenAiProvider(config);
    default: {
      // Exhaustiveness guard: adding a ProviderName without a client fails here.
      const exhaustive: never = config.model.provider;
      throw new AiConfigError(`No client implemented for provider "${exhaustive}"`);
    }
  }
}

export interface CompleteOptions extends CompletionRequest {
  model?: string;
}

/**
 * One-shot completion against the configured provider, plus the metadata worth
 * surfacing to the caller (which model actually answered, tokens, rough cost).
 */
export async function complete(options: CompleteOptions) {
  const config = resolveAiConfig({ model: options.model, effort: options.effort });
  const provider = createProvider(config);
  const result = await provider.complete(options);

  return {
    ...result,
    configuredModel: config.model.id,
    effort: config.model.supportsEffort ? (options.effort ?? config.effort) : null,
    estimatedCostUsd: estimateCost(
      config.model,
      result.usage.inputTokens,
      result.usage.outputTokens,
    ),
  };
}
