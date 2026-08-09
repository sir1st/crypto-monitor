/**
 * Model registry and configuration for the AI layer.
 *
 * To add or change a model, edit MODELS below — nothing else in the codebase
 * hardcodes a model id. To switch what the app uses at runtime, set AI_PROVIDER
 * and AI_MODEL in .env.
 */

export type ProviderName = "anthropic" | "openai";

/** Reasoning depth. Mapped onto each provider's own knob in providers/. */
export type Effort = "low" | "medium" | "high" | "xhigh" | "max";

export interface ModelSpec {
  id: string;
  provider: ProviderName;
  label: string;
  /** Total context window in tokens. */
  contextWindow: number;
  maxOutputTokens: number;
  /** USD per million tokens, for the cost estimate shown alongside results. */
  pricing: { inputPerMTok: number; outputPerMTok: number };
  supportsEffort: boolean;
  notes?: string;
}

/**
 * Anthropic ids and pricing are current as of 2026-06. Anthropic model ids are
 * stable strings with no date suffix — do not append one.
 *
 * OpenAI ids move faster and are not verifiable from here; check
 * platform.openai.com/docs/models before relying on the pricing figures, and
 * add whatever model you actually want to use.
 */
export const MODELS: Record<string, ModelSpec> = {
  // -- Anthropic -----------------------------------------------------------
  "claude-opus-5": {
    id: "claude-opus-5",
    provider: "anthropic",
    label: "Claude Opus 5",
    contextWindow: 1_000_000,
    maxOutputTokens: 128_000,
    pricing: { inputPerMTok: 5, outputPerMTok: 25 },
    supportsEffort: true,
    notes: "Default. Strongest reasoning; thinking is on by default.",
  },
  "claude-sonnet-5": {
    id: "claude-sonnet-5",
    provider: "anthropic",
    label: "Claude Sonnet 5",
    contextWindow: 1_000_000,
    maxOutputTokens: 128_000,
    pricing: { inputPerMTok: 3, outputPerMTok: 15 },
    supportsEffort: true,
    notes: "Near-Opus quality at lower cost.",
  },
  "claude-haiku-4-5": {
    id: "claude-haiku-4-5",
    provider: "anthropic",
    label: "Claude Haiku 4.5",
    contextWindow: 200_000,
    maxOutputTokens: 64_000,
    pricing: { inputPerMTok: 1, outputPerMTok: 5 },
    supportsEffort: false,
    notes: "Cheapest and fastest; no effort control.",
  },
  "claude-opus-4-8": {
    id: "claude-opus-4-8",
    provider: "anthropic",
    label: "Claude Opus 4.8",
    contextWindow: 1_000_000,
    maxOutputTokens: 128_000,
    pricing: { inputPerMTok: 5, outputPerMTok: 25 },
    supportsEffort: true,
  },

  // -- OpenAI --------------------------------------------------------------
  "gpt-5.1": {
    id: "gpt-5.1",
    provider: "openai",
    label: "GPT-5.1",
    contextWindow: 400_000,
    maxOutputTokens: 128_000,
    pricing: { inputPerMTok: 1.25, outputPerMTok: 10 },
    supportsEffort: true,
    notes: "Verify id and pricing against the OpenAI model docs.",
  },
  "gpt-5": {
    id: "gpt-5",
    provider: "openai",
    label: "GPT-5",
    contextWindow: 400_000,
    maxOutputTokens: 128_000,
    pricing: { inputPerMTok: 1.25, outputPerMTok: 10 },
    supportsEffort: true,
    notes: "Verify id and pricing against the OpenAI model docs.",
  },
  "gpt-5-mini": {
    id: "gpt-5-mini",
    provider: "openai",
    label: "GPT-5 mini",
    contextWindow: 400_000,
    maxOutputTokens: 128_000,
    pricing: { inputPerMTok: 0.25, outputPerMTok: 2 },
    supportsEffort: true,
    notes: "Verify id and pricing against the OpenAI model docs.",
  },
};

export const DEFAULT_MODEL = "claude-opus-5";

export interface AiConfig {
  model: ModelSpec;
  effort: Effort;
  maxOutputTokens: number;
  apiKey: string;
}

export class AiConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AiConfigError";
  }
}

function apiKeyFor(provider: ProviderName): string | undefined {
  return provider === "anthropic"
    ? process.env.ANTHROPIC_API_KEY
    : process.env.OPENAI_API_KEY;
}

/** True when the configured provider has a key, i.e. AI features are usable. */
export function isAiConfigured(): boolean {
  const requested = process.env.AI_MODEL ?? DEFAULT_MODEL;
  const spec = MODELS[requested];
  return Boolean(spec && apiKeyFor(spec.provider));
}

/**
 * Resolves the effective configuration, throwing a message that names the exact
 * environment variable to set when something is missing.
 */
export function resolveAiConfig(overrides: { model?: string; effort?: Effort } = {}): AiConfig {
  const requestedModel = overrides.model ?? process.env.AI_MODEL ?? DEFAULT_MODEL;
  const spec = MODELS[requestedModel];

  if (!spec) {
    throw new AiConfigError(
      `Unknown model "${requestedModel}". Available: ${Object.keys(MODELS).join(", ")}. ` +
        `Add it to server/ai/config.ts to use a model that isn't listed.`,
    );
  }

  const configuredProvider = process.env.AI_PROVIDER as ProviderName | undefined;
  if (configuredProvider && configuredProvider !== spec.provider) {
    throw new AiConfigError(
      `AI_PROVIDER is "${configuredProvider}" but AI_MODEL "${spec.id}" is a ` +
        `${spec.provider} model. Set AI_PROVIDER=${spec.provider} or pick a ` +
        `${configuredProvider} model.`,
    );
  }

  const apiKey = apiKeyFor(spec.provider);
  if (!apiKey) {
    const variable = spec.provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY";
    throw new AiConfigError(`${variable} is not set, which ${spec.label} requires.`);
  }

  const effort = overrides.effort ?? (process.env.AI_EFFORT as Effort | undefined) ?? "medium";

  return {
    model: spec,
    effort,
    // Comfortably under the model ceiling and under HTTP timeouts for
    // non-streaming requests, which is all this layer issues.
    maxOutputTokens: Math.min(Number(process.env.AI_MAX_TOKENS ?? 8000), spec.maxOutputTokens),
    apiKey,
  };
}

/** Rough USD cost of a call, for display next to the result. */
export function estimateCost(spec: ModelSpec, inputTokens: number, outputTokens: number): number {
  const cost =
    (inputTokens / 1_000_000) * spec.pricing.inputPerMTok +
    (outputTokens / 1_000_000) * spec.pricing.outputPerMTok;
  return Math.round(cost * 10_000) / 10_000;
}

/** Registry listing for the UI and the /api/ai/config endpoint. */
export function listModels() {
  return Object.values(MODELS).map((spec) => ({
    id: spec.id,
    label: spec.label,
    provider: spec.provider,
    contextWindow: spec.contextWindow,
    supportsEffort: spec.supportsEffort,
    pricing: spec.pricing,
    notes: spec.notes,
    available: Boolean(apiKeyFor(spec.provider)),
  }));
}
