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
- **Live Mode** — debounced (250 ms) calls to a real Construe instance using the
  configured credentials. A single OAuth token is fetched once and reused across all
  keystrokes (re-auth only on expiry or a 401).

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
VITE_PHENOML_CLIENT_ID=your_client_id
VITE_PHENOML_CLIENT_SECRET=your_client_secret
VITE_PHENOML_BASE_URL=https://experiment.app.pheno.ml
```

These seed the in-app **Settings** panel (gear icon). You can also enter/override them
there at runtime, and the **base URL is swappable** so you can point at any instance.

> ⚠️ **Internal / dev use only.** In Live mode the client secret is sent from the
> browser. Do **not** paste production credentials, and never share a public link that
> bakes them in. For demos, leave Demo Mode on — it needs no credentials.

### CORS caveat

Live mode makes browser `fetch` calls directly to the Construe instance. If the instance
does **not** return permissive CORS headers, the browser will block the call and Live
mode will fail. **Demo Mode is the reliable default** and needs no network access. If you
need Live mode locally against a CORS-restricted instance, proxy the requests (e.g. a
small dev proxy or a server-side relay) so the browser sees a same-origin response.

Handled gracefully in the UI: `401` (re-auth + retry once), `404` (code system not
found), `501` (search not configured for that system), CORS/network failures, and empty
results.

## API contract

```
POST {baseUrl}/auth/token                 # OAuth2 client-credentials, creds in JSON body
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
src/
  api/construe.ts     token cache + searchText/searchSemantic + error handling
  api/ranking.ts      client-side re-ranking (pure, testable)
  demo/fixtures.ts    baked TextSearchResponse data + semantic keyword map
  hooks/useAppState   settings (env-seeded) + demo/show-codes + committed-code store
  hooks/useTypeahead  debounced demo/live search; runs multi-system; applies ranking
  components/         TopBar, SettingsPanel, RowBuilder, SuggestionList,
                      NoteField + ChipRail, CommittedEntry, CodeBadge, Panel
  screens/            EncounterScreen, OrdersScreen
```

### Settings shape (stable for a localStorage port)

The Claude artifact sandbox blocks `localStorage`, so Settings is backed by React state.
The signatures are kept identical so the app ports to a `localStorage` build unchanged —
only the storage layer in `hooks/useAppState.tsx` would change:

```ts
export type Settings = { clientId: string; clientSecret: string; baseUrl: string };
export const DEFAULT_SETTINGS: Settings = {
  clientId: '', clientSecret: '', baseUrl: 'https://experiment.app.pheno.ml',
};
```

## Stack

Vite 7 · React 18 · TypeScript 5 · Mantine 8 (custom theme) · `@tabler/icons-react`.
Same toolchain as the sibling `demochat/` demo.
