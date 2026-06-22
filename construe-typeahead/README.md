# Construe Type-Ahead — Clinician Coding Demo

A two-screen demo where a clinician types in **plain language** and the app silently
stores **structured medical codes**. The UI shows human-readable text; the in-memory
store holds the coded concepts. A **Show codes** toggle reveals exactly what was
captured — the key sales moment.

Powered by [PhenoML Construe](https://developer.pheno.ml) code search.

![Plain language in · coded concepts out](#)

## What it shows

- **Encounter note** screen — a problem-list builder, a medication builder, and a
  free-text clinical note.
- **Orders** screen — an order-entry field.
- Accepting a suggestion commits **display text** to the UI and **code(s)** to an
  in-memory store. Flip **Show codes** to reveal the stored `system · code · description`
  next to every committed entry.

### Two search endpoints, by purpose

| Field | Code system(s) | Endpoint | Why |
| --- | --- | --- | --- |
| Problem list | `SNOMED_CT_US_LITE` + `ICD-10-CM` | **text** | Fast prefix/substring type-ahead; stores **both** codes per problem |
| Medication | `RXNORM` | **text** | Prefix/substring type-ahead |
| Orders | `LOINC` | **text** | Prefix/substring type-ahead |
| Clinical note | `SNOMED_CT_US_LITE` | **semantic** | The clinician writes a phrase, not a prefix — semantic finds the concept by meaning |

### The ranking fix

Construe text search is substring-based, so `asth` returns long co-occurrent descriptors
(_"Acute exacerbation of asthma co-occurrent with allergic rhinitis"_) alongside the plain
concept _"Asthma"_. The app re-ranks results client-side
(`src/api/ranking.ts`) so exact-prefix and shortest-description matches float to the top
and combination/co-occurrent concepts are demoted — the plain concept wins for a plain
prefix.

## Two modes

- **Demo Mode (default ON)** — baked responses shaped exactly like a real Construe
  `TextSearchResponse`. No credentials, fully standalone. Try `asth`, `albut`,
  `shortness of breath` (note), `lipid panel`, `a1c`.
- **Live Mode** — debounced (250 ms) calls to a real Construe instance, made through a
  **same-origin proxy** so the client secret never reaches the browser. The proxy holds
  the credentials, fetches a single OAuth token once, and reuses it across all keystrokes
  (re-auth only on expiry or a 401).

## Run it

```bash
npm install
npm run dev      # opens http://localhost:5173
```

Other scripts:

```bash
npm run build      # tsc --noEmit + vite build
npm run typecheck  # tsc --noEmit
npm run preview    # preview the production build
```

## Live Mode credentials (`.env`)

Copy `.env.example` to `.env` and fill in your instance credentials:

```bash
cp .env.example .env
```

```dotenv
PHENOML_CLIENT_ID=your_client_id
PHENOML_CLIENT_SECRET=your_client_secret
PHENOML_BASE_URL=https://experiment.app.pheno.ml   # optional
```

These are read **server-side only** by the proxy middleware (`server/construeProxy.mjs`,
mounted in `vite.config.ts`). They are **never** shipped to the browser — note the absence
of the `VITE_` prefix, which is exactly what would inline a value into the client bundle.
Restart the dev server after editing `.env`.

> 🔒 **The client secret stays on the server.** The browser only ever calls the
> same-origin `/api/*` proxy — it never sees the credentials or the OAuth token. This is
> the pattern to copy when building your own app: keep the secret behind a server you
> control, mint the token there, and proxy the API.

### How Live mode reaches Construe

The browser calls same-origin `/api/*`; the proxy adds the Bearer token and forwards to
Construe. Because the browser talks to the same origin, there's **no CORS** to configure
and **no secret in the page**. Demo Mode needs no server at all.

> ⚠️ **Production note.** The proxy runs as Vite dev/preview middleware, so it's active
> under `npm run dev` and `npm run preview` but **not** in a bare static `dist/` deploy.
> To deploy, host the same handler (`server/construeProxy.mjs`) behind a server you run
> (Express, a serverless function, an edge worker, …) and serve the built `dist/` from the
> same origin so `/api/*` resolves to it.

Handled gracefully in the UI: `401` (re-auth + retry once), `404` (code system not
found), `501` (search not configured for that system), proxy/network failures, and empty
results.

## API contract

The browser talks only to the same-origin proxy:

```
GET  /api/config                                   # { live, baseUrl } — no secret
GET  /api/search/text/{slug}?q={query}&limit=8
GET  /api/search/semantic/{slug}?q={query}&limit=8
```

The proxy (`server/construeProxy.mjs`) holds the credentials and calls Construe:

```
POST {baseUrl}/v2/auth/token              # OAuth2 client-credentials, creds in JSON body
GET  {baseUrl}/construe/codes/{slug}/search/text?q={query}&limit=8
GET  {baseUrl}/construe/codes/{slug}/search/semantic?q={query}&limit=8
                                          # Authorization: Bearer <token>
```

Response shape (system name/version is on the parent `system` object, not per result):

```json
{ "system": { "name": "...", "version": "..." },
  "results": [ { "code": "...", "description": "..." } ],
  "found": 0 }
```

A stored coded concept is composed from `system.name` + `result.code` + `result.description`.

## Architecture

```
server/
  construeProxy.mjs   holds .env credentials; mints/caches the OAuth token; proxies
                      /api/config + /api/search/* to Construe (mounted by vite.config.ts)
src/
  api/construe.ts     thin same-origin client: searchText/searchSemantic + /api/config
  api/ranking.ts      client-side re-ranking (pure, testable)
  demo/fixtures.ts    baked TextSearchResponse data + semantic keyword map
  hooks/useAppState   live-availability (from /api/config) + demo/show-codes + code store
  hooks/useTypeahead  debounced demo/live search; runs multi-system; applies ranking
  components/         TopBar, RowBuilder, SuggestionList,
                      NoteField + ChipRail, CommittedEntry, CodeBadge, Panel
  screens/            EncounterScreen, OrdersScreen
```

### Where the credentials live

Credentials are read **only** in `server/construeProxy.mjs` (from `.env`, via `loadEnv` in
`vite.config.ts`). The browser learns whether Live mode is available from `GET /api/config`
(`{ live, baseUrl }`, no secret) — it never holds the client ID, secret, or token.

## Stack

Vite 7 · React 18 · TypeScript 5 · Mantine 8 (custom theme) · `@tabler/icons-react`.
Same toolchain as the sibling `demochat/` demo.
