import type { Effort } from "../config";

export interface CompletionRequest {
  prompt: string;
  system?: string;
  maxTokens?: number;
  effort?: Effort;
}

export interface CompletionResult {
  text: string;
  /** True when the provider's safety layer declined; `text` is then empty. */
  refused: boolean;
  stopReason?: string;
  model: string;
  provider: string;
  usage: { inputTokens: number; outputTokens: number };
}

export interface Provider {
  name: string;
  complete(request: CompletionRequest): Promise<CompletionResult>;
}
