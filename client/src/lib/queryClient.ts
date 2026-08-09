import { QueryClient, type QueryFunction } from "@tanstack/react-query";

async function throwIfNotOk(res: Response) {
  if (res.ok) return;

  const text = await res.text();
  let message = text || res.statusText;
  try {
    const body = JSON.parse(text) as { error?: string; message?: string };
    message = body.error ?? body.message ?? message;
  } catch {
    // Not JSON — use the raw text.
  }
  throw new Error(`${res.status}: ${message}`);
}

export async function apiRequest(
  method: string,
  url: string,
  data?: unknown,
): Promise<Response> {
  const res = await fetch(url, {
    method,
    headers: data === undefined ? {} : { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });

  await throwIfNotOk(res);
  return res;
}

/** Default query function: the first query-key element is the URL to fetch. */
const defaultQueryFn: QueryFunction = async ({ queryKey }) => {
  const res = await fetch(queryKey[0] as string);
  await throwIfNotOk(res);
  return res.json();
};

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      queryFn: defaultQueryFn,
      refetchInterval: false,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
    },
  },
});
