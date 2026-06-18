import {
  SearchError,
  type CodeSystemSlug,
  type Settings,
  type TextSearchResponse,
} from '../types';

// ---------------------------------------------------------------------------
// Construe API client.
//
// Auth: POST {baseUrl}/auth/token (OAuth2 client-credentials, creds in JSON
// body). Token is fetched ONCE and cached with its expiry, reused across every
// keystroke, and only re-minted on expiry or a 401. We never mint per stroke.
//
// Search: GET {baseUrl}/construe/codes/{slug}/search/{text|semantic}?q=&limit=
// with a Bearer token.
// ---------------------------------------------------------------------------

interface CachedToken {
  token: string;
  expiresAt: number; // epoch ms
  // The credentials this token was minted for — if any change, re-auth.
  baseUrl: string;
  clientId: string;
  clientSecret: string;
}

let cachedToken: CachedToken | null = null;

// Refresh slightly before the real expiry to avoid edge-of-expiry 401s.
const EXPIRY_SKEW_MS = 30_000;

function credsMatch(c: CachedToken, s: Settings): boolean {
  return (
    c.baseUrl === s.baseUrl &&
    c.clientId === s.clientId &&
    c.clientSecret === s.clientSecret
  );
}

/** Clear the cached token (call this on a 401 before retrying). */
export function clearToken(): void {
  cachedToken = null;
}

function trimBase(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, '');
}

/**
 * Fetch a fresh OAuth token. Parses the standard OAuth client-credentials
 * shape (access_token / expires_in) with token / expiry fallbacks, since the
 * exact field names aren't pinned in-repo yet.
 */
async function fetchToken(settings: Settings): Promise<CachedToken> {
  const url = `${trimBase(settings.baseUrl)}/auth/token`;
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: settings.clientId,
        client_secret: settings.clientSecret,
      }),
    });
  } catch (e) {
    throw new SearchError(
      'network',
      `Could not reach ${url}. If this is a browser CORS block, use Demo Mode. (${
        e instanceof Error ? e.message : String(e)
      })`,
    );
  }

  if (resp.status === 401 || resp.status === 403) {
    throw new SearchError(
      'auth',
      'Authentication failed — check the client ID and secret in Settings.',
      resp.status,
    );
  }
  if (!resp.ok) {
    throw new SearchError(
      'unknown',
      `Auth request failed (HTTP ${resp.status}).`,
      resp.status,
    );
  }

  const data: Record<string, unknown> = await resp.json().catch(() => ({}));
  const token = (data.access_token ?? data.token) as string | undefined;
  if (!token) {
    throw new SearchError('auth', 'Auth response did not include a token.');
  }

  // Compute expiry. Prefer expires_in (seconds); fall back to an absolute
  // expiry field, else default to 1 hour.
  const expiresIn = data.expires_in as number | undefined;
  const absExpiry = data.expiry as number | string | undefined;
  let expiresAt: number;
  if (typeof expiresIn === 'number') {
    expiresAt = nowMs() + expiresIn * 1000;
  } else if (typeof absExpiry === 'number') {
    expiresAt = absExpiry > 1e12 ? absExpiry : absExpiry * 1000;
  } else if (typeof absExpiry === 'string') {
    const parsed = Date.parse(absExpiry);
    expiresAt = Number.isNaN(parsed) ? nowMs() + 3_600_000 : parsed;
  } else {
    expiresAt = nowMs() + 3_600_000;
  }

  return {
    token,
    expiresAt,
    baseUrl: settings.baseUrl,
    clientId: settings.clientId,
    clientSecret: settings.clientSecret,
  };
}

function nowMs(): number {
  return new Date().getTime();
}

/** Get a valid token from cache, or mint a new one. */
async function getToken(settings: Settings): Promise<string> {
  if (
    cachedToken &&
    credsMatch(cachedToken, settings) &&
    cachedToken.expiresAt - EXPIRY_SKEW_MS > nowMs()
  ) {
    return cachedToken.token;
  }
  cachedToken = await fetchToken(settings);
  return cachedToken.token;
}

type SearchMode = 'text' | 'semantic';

async function doSearch(
  settings: Settings,
  slug: CodeSystemSlug,
  mode: SearchMode,
  query: string,
  token: string,
  limit: number,
): Promise<Response> {
  const url =
    `${trimBase(settings.baseUrl)}/construe/codes/${slug}/search/${mode}` +
    `?q=${encodeURIComponent(query)}&limit=${limit}`;
  try {
    return await fetch(url, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch (e) {
    throw new SearchError(
      'network',
      `Could not reach Construe. If this is a browser CORS block, use Demo Mode. (${
        e instanceof Error ? e.message : String(e)
      })`,
    );
  }
}

/**
 * Run a Construe search (text or semantic). Handles token caching, a single
 * re-auth + retry on 401, and maps 404/501/other statuses to SearchError.
 */
async function search(
  settings: Settings,
  slug: CodeSystemSlug,
  mode: SearchMode,
  query: string,
  limit = 8,
): Promise<TextSearchResponse> {
  let token = await getToken(settings);
  let resp = await doSearch(settings, slug, mode, query, token, limit);

  // 401 → token may have expired server-side. Re-auth once and retry.
  if (resp.status === 401) {
    clearToken();
    token = await getToken(settings);
    resp = await doSearch(settings, slug, mode, query, token, limit);
  }

  if (resp.status === 401) {
    throw new SearchError('auth', 'Unauthorized — re-auth failed.', 401);
  }
  if (resp.status === 404) {
    throw new SearchError(
      'not_found',
      `Code system "${slug}" not found on this instance.`,
      404,
    );
  }
  if (resp.status === 501) {
    throw new SearchError(
      'not_configured',
      `${mode === 'text' ? 'Text' : 'Semantic'} search is not configured for "${slug}" on this instance.`,
      501,
    );
  }
  if (!resp.ok) {
    throw new SearchError('unknown', `Search failed (HTTP ${resp.status}).`, resp.status);
  }

  const data = (await resp.json().catch(() => null)) as TextSearchResponse | null;
  if (!data || !Array.isArray(data.results)) {
    throw new SearchError('unknown', 'Unexpected response shape from Construe.');
  }
  return data;
}

export function searchText(
  settings: Settings,
  slug: CodeSystemSlug,
  query: string,
  limit = 8,
): Promise<TextSearchResponse> {
  return search(settings, slug, 'text', query, limit);
}

export function searchSemantic(
  settings: Settings,
  slug: CodeSystemSlug,
  query: string,
  limit = 8,
): Promise<TextSearchResponse> {
  return search(settings, slug, 'semantic', query, limit);
}
