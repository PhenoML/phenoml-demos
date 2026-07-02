// ---------------------------------------------------------------------------
// Server-side Construe proxy (Vite dev/preview middleware).
//
// This is where the PhenoML credentials live. They are read from .env
// server-side (PHENOML_CLIENT_ID / PHENOML_CLIENT_SECRET / PHENOML_BASE_URL via
// vite.config.ts) and NEVER shipped to the browser. The browser talks only to
// same-origin /api/* routes below; this module mints + caches the OAuth token
// and forwards searches to Construe with a Bearer header.
//
//   GET /api/config                      -> { live }   (no secret)
//   GET /api/search/:mode/:slug?q=&limit -> Construe search results
//
// Auth: POST {base}/v2/auth/token (OAuth2 client-credentials, creds in JSON
// body). The token is fetched ONCE, cached with its expiry, reused across every
// keystroke, and only re-minted on expiry or a 401. Plain Node ESM — uses the
// global fetch (Node >= 20) and is intentionally kept out of the app's TS
// program (see server/construeProxy.d.mts for the config-import types).
//
// Demo note: before productionizing this credentialed proxy, add application
// authentication, rate limiting, request logging, and abuse controls.
// ---------------------------------------------------------------------------

const VALID_MODES = new Set(['text', 'semantic']);
const VALID_SLUGS = new Set([
  'ICD-10-CM',
  'SNOMED_CT_US_LITE',
  'RXNORM',
  'LOINC',
]);

// Refresh slightly before the real expiry to avoid edge-of-expiry 401s.
const EXPIRY_SKEW_MS = 30_000;
const DEFAULT_LIMIT = 8;
const MAX_LIMIT = 50;
const MAX_TEXT_QUERY_CHARS = 500;
const MAX_SEMANTIC_QUERY_CHARS = 10_000;

// Error carrying a SearchErrorKind (mirrors src/types.ts) so the browser can
// reconstruct a SearchError from the JSON body unchanged.
class ProxyError extends Error {
  constructor(kind, message, status = 500) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

function trimBase(baseUrl) {
  return baseUrl.replace(/\/+$/, '');
}

function computeExpiry(data) {
  // Prefer expires_in (seconds); fall back to an absolute expiry field, else 1h.
  const expiresIn = data.expires_in;
  const absExpiry = data.expiry;
  if (typeof expiresIn === 'number') return Date.now() + expiresIn * 1000;
  if (typeof absExpiry === 'number') {
    return absExpiry > 1e12 ? absExpiry : absExpiry * 1000;
  }
  if (typeof absExpiry === 'string') {
    const parsed = Date.parse(absExpiry);
    return Number.isNaN(parsed) ? Date.now() + 3_600_000 : parsed;
  }
  return Date.now() + 3_600_000;
}

function clampLimit(raw) {
  const n = Number.parseInt(raw ?? '', 10);
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_LIMIT;
  return Math.min(n, MAX_LIMIT);
}

function maxQueryLength(mode) {
  return mode === 'semantic' ? MAX_SEMANTIC_QUERY_CHARS : MAX_TEXT_QUERY_CHARS;
}

function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}

function sendError(res, err) {
  const status = err.status ?? 500;
  const kind = err.kind ?? 'unknown';
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify({ error: { kind, message: err.message, status } }));
}

/**
 * Build the proxy middleware. Credentials are fixed at process start, so the
 * token cache only needs to track the token + its expiry (no per-request creds).
 */
export function createConstrueProxy({ clientId, clientSecret, baseUrl }) {
  const base = trimBase(baseUrl);
  const live = Boolean(clientId && clientSecret);

  let cachedToken = null; // { token, expiresAt } | null

  function clearToken() {
    cachedToken = null;
  }

  async function fetchToken() {
    const url = `${base}/v2/auth/token`;
    let resp;
    try {
      resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: clientId,
          client_secret: clientSecret,
        }),
      });
    } catch (e) {
      throw new ProxyError(
        'network',
        `Could not reach ${url}. (${e instanceof Error ? e.message : String(e)})`,
        502,
      );
    }

    if (resp.status === 401 || resp.status === 403) {
      throw new ProxyError(
        'auth',
        'Authentication failed — check PHENOML_CLIENT_ID / PHENOML_CLIENT_SECRET.',
        resp.status,
      );
    }
    if (!resp.ok) {
      throw new ProxyError(
        'unknown',
        `Auth request failed (HTTP ${resp.status}).`,
        resp.status,
      );
    }

    const data = await resp.json().catch(() => ({}));
    const token = data.access_token ?? data.token;
    if (!token) {
      throw new ProxyError('auth', 'Auth response did not include a token.', 502);
    }
    return { token, expiresAt: computeExpiry(data) };
  }

  async function getToken() {
    if (cachedToken && cachedToken.expiresAt - EXPIRY_SKEW_MS > Date.now()) {
      return cachedToken.token;
    }
    cachedToken = await fetchToken();
    return cachedToken.token;
  }

  async function doSearch(slug, mode, query, limit, token) {
    // Construe's two endpoints name the query param differently:
    //   /search/text     → q     (keyword, <=500 chars)
    //   /search/semantic → text  (natural language, <=10,000 chars)
    const param = mode === 'semantic' ? 'text' : 'q';
    const url =
      `${base}/construe/codes/${slug}/search/${mode}` +
      `?${param}=${encodeURIComponent(query)}&limit=${limit}`;
    try {
      return await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    } catch (e) {
      throw new ProxyError(
        'network',
        `Could not reach Construe. (${e instanceof Error ? e.message : String(e)})`,
        502,
      );
    }
  }

  // Run a search, with a single re-auth + retry on 401, mapping upstream
  // statuses to SearchErrorKind-tagged ProxyErrors.
  async function search(slug, mode, query, limit) {
    let token = await getToken();
    let resp = await doSearch(slug, mode, query, limit, token);

    if (resp.status === 401) {
      clearToken();
      token = await getToken();
      resp = await doSearch(slug, mode, query, limit, token);
    }

    if (resp.status === 401) {
      throw new ProxyError('auth', 'Unauthorized — re-auth failed.', 401);
    }
    if (resp.status === 404) {
      throw new ProxyError(
        'not_found',
        `Code system "${slug}" not found on this instance.`,
        404,
      );
    }
    if (resp.status === 501) {
      throw new ProxyError(
        'not_configured',
        `${mode === 'text' ? 'Text' : 'Semantic'} search is not configured for "${slug}" on this instance.`,
        501,
      );
    }
    if (!resp.ok) {
      throw new ProxyError('unknown', `Search failed (HTTP ${resp.status}).`, resp.status);
    }

    const data = await resp.json().catch(() => null);
    if (!data || !Array.isArray(data.results)) {
      throw new ProxyError('unknown', 'Unexpected response shape from Construe.', 502);
    }
    return data;
  }

  return async function construeProxy(req, res, next) {
    if (!req.url || !req.url.startsWith('/api/')) return next();

    const url = new URL(req.url, 'http://localhost');
    const path = url.pathname;

    try {
      if (req.method === 'GET' && path === '/api/config') {
        return sendJson(res, 200, { live });
      }

      const match = path.match(/^\/api\/search\/([^/]+)\/([^/]+)$/);
      if (req.method === 'GET' && match) {
        if (!live) {
          return sendError(
            res,
            new ProxyError(
              'auth',
              'Live mode is not configured. Set PHENOML_CLIENT_ID and PHENOML_CLIENT_SECRET in .env, then restart.',
              503,
            ),
          );
        }
        const mode = decodeURIComponent(match[1]);
        const slug = decodeURIComponent(match[2]);
        if (!VALID_MODES.has(mode) || !VALID_SLUGS.has(slug)) {
          return sendError(
            res,
            new ProxyError('unknown', 'Unknown search mode or code system.', 400),
          );
        }
        const q = (url.searchParams.get('q') ?? '').trim();
        if (!q) {
          return sendError(
            res,
            new ProxyError('unknown', 'Missing query parameter "q".', 400),
          );
        }
        const maxChars = maxQueryLength(mode);
        if (q.length > maxChars) {
          return sendError(
            res,
            new ProxyError(
              'unknown',
              `Query is too long for ${mode} search. Maximum length is ${maxChars} characters.`,
              400,
            ),
          );
        }
        const limit = clampLimit(url.searchParams.get('limit'));
        const data = await search(slug, mode, q, limit);
        return sendJson(res, 200, data);
      }

      return sendError(
        res,
        new ProxyError('not_found', `No such endpoint: ${req.method} ${path}`, 404),
      );
    } catch (err) {
      if (err instanceof ProxyError) return sendError(res, err);
      const message = err instanceof Error ? err.message : String(err);
      return sendError(
        res,
        new ProxyError('unknown', `Proxy error: ${message}`, 500),
      );
    }
  };
}
