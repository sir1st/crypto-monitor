/**
 * Thin HTTP client the MCP tools call.
 *
 * The MCP server talks to the running app over HTTP rather than opening the
 * SQLite file directly. That keeps validation and alert evaluation in one place,
 * and means the agent can point at a different instance by changing VALE_API_URL.
 *
 * The API is unauthenticated, so there is no credential to configure.
 */

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClient {
  get<T>(path: string, query?: Record<string, string | number | undefined>): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  patch<T>(path: string, body?: unknown): Promise<T>;
  del(path: string): Promise<void>;
}

export function createApiClient(): ApiClient {
  const baseUrl = (process.env.VALE_API_URL ?? "http://127.0.0.1:5000").replace(/\/$/, "");

  async function request<T>(
    method: string,
    path: string,
    options: { body?: unknown; query?: Record<string, string | number | undefined> } = {},
  ): Promise<T> {
    const url = new URL(`${baseUrl}${path}`);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers: options.body === undefined ? {} : { "Content-Type": "application/json" },
        ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      });
    } catch (error) {
      throw new ApiError(
        `Cannot reach the Vale server at ${baseUrl}. Is it running (\`npm run dev\`)? ` +
          `Underlying error: ${(error as Error).message}`,
        0,
      );
    }

    if (response.status === 204) return undefined as T;

    const text = await response.text();
    const payload = text ? safeJson(text) : undefined;

    if (!response.ok) {
      const detail =
        (payload as { error?: string; message?: string } | undefined)?.error ??
        (payload as { message?: string } | undefined)?.message ??
        text ??
        response.statusText;
      throw new ApiError(`${method} ${path} failed (${response.status}): ${detail}`, response.status);
    }

    return payload as T;
  }

  function safeJson(text: string): unknown {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  return {
    get: (path, query) => request("GET", path, { query }),
    post: (path, body) => request("POST", path, { body }),
    patch: (path, body) => request("PATCH", path, { body }),
    del: async (path) => {
      await request("DELETE", path);
    },
  };
}
