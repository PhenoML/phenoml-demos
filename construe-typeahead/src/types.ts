// ---------------------------------------------------------------------------
// Construe code systems (exact path slugs — do not alter)
// ---------------------------------------------------------------------------
export type CodeSystemSlug =
  | 'ICD-10-CM'
  | 'SNOMED_CT_US_LITE'
  | 'RXNORM'
  | 'LOINC';

// ---------------------------------------------------------------------------
// API response shapes (confirmed against docs — do not invent fields).
// GET /construe/codes/{codesystem}/search/{text|semantic}?q=&limit=
//   { system: { name, version }, results: [ { code, description } ], found }
// The system name/version lives on the PARENT system object, not per result.
// ---------------------------------------------------------------------------
export interface SearchSystem {
  name: string;
  version: string;
}

export interface SearchResultItem {
  code: string;
  description: string;
}

export interface TextSearchResponse {
  system: SearchSystem;
  results: SearchResultItem[];
  found: number;
}

// A stored coded concept: system.name + result.code + result.description.
export interface CodedConcept {
  system: string; // system.name
  version: string; // system.version
  code: string;
  description: string;
}

// A single ranked suggestion shown in the type-ahead dropdown / chip rail.
// Carries the coded concept(s) it would commit when accepted.
export interface Suggestion {
  /** Stable key for React lists. */
  id: string;
  /** Human-readable label shown to the clinician. */
  label: string;
  /** Coded concept(s) committed when this suggestion is accepted. */
  codes: CodedConcept[];
}

// Field categories — drive which code system(s) / endpoint a field uses.
export type FieldKind = 'problem' | 'medication' | 'order' | 'note';

// A committed entry in the in-memory store. `text` is what the UI shows;
// `codes` is the structured data revealed by the Show-codes toggle.
export interface CommittedEntry {
  id: string;
  kind: FieldKind;
  text: string;
  codes: CodedConcept[];
}

// Error categories surfaced to the UI for graceful handling.
export type SearchErrorKind =
  | 'auth' // 401 after re-auth attempt
  | 'not_found' // 404 code system not found
  | 'not_configured' // 501 text search not configured
  | 'network' // fetch/CORS failure
  | 'unknown';

export class SearchError extends Error {
  kind: SearchErrorKind;
  status?: number;
  constructor(kind: SearchErrorKind, message: string, status?: number) {
    super(message);
    this.name = 'SearchError';
    this.kind = kind;
    this.status = status;
  }
}
