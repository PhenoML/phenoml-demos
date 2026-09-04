// ---------------------------------------------------------------------------
// Server-side Construe proxy (Vite dev/preview middleware).
//
// This is where the PhenoML credentials live. They are read from .env
// server-side (PHENOML_CLIENT_ID / PHENOML_CLIENT_SECRET / PHENOML_BASE_URL via
// vite.config.ts) and NEVER shipped to the browser. The browser talks only to
// same-origin /api/* routes below; this module wraps the PhenoML TypeScript SDK.
// A single server-side phenomlClient mints, caches, and refreshes the OAuth token
// and calls client.construe.codes.searchText / searchSemantic. On a search-phase
// 401, the proxy re-creates the client and retries once.
//
//   GET /api/config                      -> { live }   (no secret)
//   GET /api/search/:mode/:slug?q=&limit -> Construe search results
//
// Plain Node ESM is intentionally kept out of the app's TS program (see
// server/construeProxy.d.mts for the config-import types).
//
// Demo note: before productionizing this credentialed proxy, add application
// authentication, rate limiting, request logging, and abuse controls.
// ---------------------------------------------------------------------------

import { phenomlClient, phenoml, phenomlError, phenomlTimeoutError } from 'phenoml';

const VALID_MODES = new Set(['text', 'semantic']);
const VALID_SLUGS = new Set([
  'ICD-10-CM',
  'SNOMED_CT_US_LITE',
  'RXNORM',
  'LOINC',
]);

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
 * @param {unknown} err
 * @returns {boolean}
 */
function isTokenPhase(err) {
  return err instanceof phenoml.authtoken.UnauthorizedError
    || (typeof err.rawResponse?.url === 'string' && err.rawResponse.url.includes('/v2/auth/token'));
}

/**
 * @param {unknown} err
 * @param {string} slug
 * @param {'text' | 'semantic'} mode
 * @returns {ProxyError | null}
 */
function mapSdkError(err, slug, mode) {
  if (!(err instanceof phenomlError)) return null;
  if (err instanceof phenomlTimeoutError) {
    return new ProxyError('network', `Construe did not respond in time. (${err.message})`, 504);
  }
  if (err.statusCode === undefined) {
    return new ProxyError('network', `Could not reach Construe. (${err.message})`, 502);
  }
  const status = err.statusCode;
  if (isTokenPhase(err)) {
    if (status === 401 || status === 403) {
      return new ProxyError(
        'auth',
        'Authentication failed — check PHENOML_CLIENT_ID / PHENOML_CLIENT_SECRET.',
        status,
      );
    }
    return new ProxyError('unknown', `Auth request failed (HTTP ${status}).`, status);
  }
  switch (status) {
    case 401:
      return new ProxyError('auth', 'Unauthorized — re-auth failed.', 401);
    case 404:
      return new ProxyError(
        'not_found',
        `Code system "${slug}" not found on this instance.`,
        404,
      );
    case 501:
      return new ProxyError(
        'not_configured',
        `${mode === 'text' ? 'Text' : 'Semantic'} search is not configured for "${slug}" on this instance.`,
        501,
      );
    default:
      return new ProxyError('unknown', `Search failed (HTTP ${status}).`, status);
  }
}

/**
 * Build the proxy middleware. Credentials and the SDK client are fixed at
 * process start; the client manages token minting, caching, and refresh.
 */
export function createConstrueProxy({ clientId, clientSecret, baseUrl }) {
  const live = Boolean(clientId && clientSecret);
  // The SDK defaults to retrying 408/429/5xx responses. Disable those retries
  // to retain the proxy's existing bounded type-ahead request behavior.
  const makeClient = () => new phenomlClient({
    clientId,
    clientSecret,
    baseUrl,
    maxRetries: 0,
  });
  let client = live ? makeClient() : null;

  // Run a search with a single client rebuild + retry on a search-phase 401,
  // mapping SDK failures to SearchErrorKind-tagged ProxyErrors.
  async function search(slug, mode, query, limit) {
    /** @param {import('phenoml').phenomlClient} c */
    const run = (c) => mode === 'semantic'
      ? c.construe.codes.searchSemantic(slug, { text: query, limit })
      : c.construe.codes.searchText(slug, { q: query, limit });
    let data;
    try {
      const used = client;
      try {
        data = await run(used);
      } catch (err) {
        // Token-phase auth failures use phenoml.authtoken.UnauthorizedError and
        // must not be retried with the same bad credentials.
        if (!(err instanceof phenoml.construe.UnauthorizedError)) throw err;
        if (client === used) client = makeClient();
        data = await run(client);
      }
    } catch (err) {
      throw mapSdkError(err, slug, mode) ?? err;
    }
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
