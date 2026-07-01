import {
  SearchError,
  type CodeSystemSlug,
  type SearchErrorKind,
  type TextSearchResponse,
} from '../types';

// ---------------------------------------------------------------------------
// Construe API client (browser side).
//
// The browser never sees the PhenoML credentials or the OAuth token. It calls
// the same-origin proxy (server/construeProxy, mounted by vite.config.ts), which
// holds the .env credentials, mints/caches the token, and forwards searches to
// Construe. So there is no auth, no Bearer header, and no CORS here.
//
//   GET /api/config                       -> { live }
//   GET /api/search/{text|semantic}/{slug}?q=&limit=
// ---------------------------------------------------------------------------

type SearchMode = 'text' | 'semantic';

const VALID_KINDS: ReadonlySet<string> = new Set([
  'auth',
  'not_found',
  'not_configured',
  'network',
  'unknown',
]);

export interface LiveConfig {
  live: boolean;
}

/** Ask the proxy whether Live mode is configured (creds present in .env). */
export async function fetchLiveConfig(): Promise<LiveConfig> {
  try {
    const resp = await fetch('/api/config');
    if (!resp.ok) return { live: false };
    const data = (await resp.json().catch(() => null)) as LiveConfig | null;
    if (!data || typeof data.live !== 'boolean') return { live: false };
    return data;
  } catch {
    // Proxy not reachable (e.g. static build with no server) → Demo-only.
    return { live: false };
  }
}

// Turn a proxy error body / failed response into a SearchError.
async function errorFromResponse(resp: Response): Promise<SearchError> {
  const body = (await resp.json().catch(() => null)) as
    | { error?: { kind?: string; message?: string; status?: number } }
    | null;
  const err = body?.error;
  if (err) {
    const kind: SearchErrorKind = VALID_KINDS.has(err.kind ?? '')
      ? (err.kind as SearchErrorKind)
      : 'unknown';
    return new SearchError(kind, err.message ?? `Search failed (HTTP ${resp.status}).`, err.status ?? resp.status);
  }
  return new SearchError('unknown', `Search failed (HTTP ${resp.status}).`, resp.status);
}

async function search(
  slug: CodeSystemSlug,
  mode: SearchMode,
  query: string,
  limit: number,
  signal?: AbortSignal,
): Promise<TextSearchResponse> {
  const url = `/api/search/${mode}/${encodeURIComponent(slug)}?q=${encodeURIComponent(
    query,
  )}&limit=${limit}`;

  let resp: Response;
  try {
    resp = await fetch(url, { signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new SearchError(
      'network',
      `Could not reach the proxy. Is the dev server running? (${
        e instanceof Error ? e.message : String(e)
      })`,
    );
  }

  if (!resp.ok) throw await errorFromResponse(resp);

  const data = (await resp.json().catch(() => null)) as TextSearchResponse | null;
  if (!data || !Array.isArray(data.results)) {
    throw new SearchError('unknown', 'Unexpected response shape from the proxy.');
  }
  return data;
}

export function searchText(
  slug: CodeSystemSlug,
  query: string,
  limit = 8,
  signal?: AbortSignal,
): Promise<TextSearchResponse> {
  return search(slug, 'text', query, limit, signal);
}

export function searchSemantic(
  slug: CodeSystemSlug,
  query: string,
  limit = 8,
  signal?: AbortSignal,
): Promise<TextSearchResponse> {
  return search(slug, 'semantic', query, limit, signal);
}
