import { useEffect, useRef, useState } from 'react';
import { useDebouncedValue } from '@mantine/hooks';
import { searchSemantic, searchText } from '../api/construe';
import { rankResults } from '../api/ranking';
import { demoSemanticSearch, demoTextSearch } from '../demo/fixtures';
import { useAppState } from './useAppState';
import {
  SearchError,
  type CodeSystemSlug,
  type CodedConcept,
  type SearchErrorKind,
  type SearchResultItem,
  type SearchSystem,
  type Suggestion,
  type TextSearchResponse,
} from '../types';

export type SearchMode = 'text' | 'semantic';

interface UseTypeaheadArgs {
  /**
   * Code systems to query. The FIRST is the display/primary system whose
   * ranked results become the suggestion labels; any additional systems
   * contribute their top-ranked concept so a single accepted suggestion can
   * store codes across systems (e.g. problem list → SNOMED + ICD-10-CM).
   */
  systems: CodeSystemSlug[];
  mode: SearchMode;
  /** Minimum trimmed query length before a search fires. */
  minLength?: number;
}

export interface TypeaheadState {
  query: string;
  setQuery: (q: string) => void;
  suggestions: Suggestion[];
  loading: boolean;
  error: { kind: SearchErrorKind; message: string } | null;
  reset: () => void;
}

function toConcept(system: SearchSystem, item: SearchResultItem): CodedConcept {
  return {
    system: system.name,
    version: system.version,
    code: item.code,
    description: item.description,
  };
}

function buildSuggestions(
  query: string,
  systems: CodeSystemSlug[],
  responses: Record<string, TextSearchResponse>,
  mode: SearchMode,
): Suggestion[] {
  const [primarySlug, ...secondarySlugs] = systems;
  const primary = responses[primarySlug];
  if (!primary) return [];

  // Semantic results are already ranked by meaning server-side; only re-rank
  // substring-based text results.
  const primaryItems =
    mode === 'text' ? rankResults(query, primary.results) : primary.results;

  // Each additional system contributes its single best concept for the query,
  // so accepting one suggestion stores codes across all configured systems.
  const secondaryTops: CodedConcept[] = [];
  for (const slug of secondarySlugs) {
    const resp = responses[slug];
    if (!resp || resp.results.length === 0) continue;
    const ranked = mode === 'text' ? rankResults(query, resp.results) : resp.results;
    secondaryTops.push(toConcept(resp.system, ranked[0]));
  }

  return primaryItems.map((item) => ({
    id: `${primarySlug}:${item.code}`,
    label: item.description,
    codes: [toConcept(primary.system, item), ...secondaryTops],
  }));
}

export function useTypeahead({
  systems,
  mode,
  minLength = 2,
}: UseTypeaheadArgs): TypeaheadState {
  const { settings, demoMode } = useAppState();
  const [query, setQuery] = useState('');
  const [debounced] = useDebouncedValue(query, 250);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] =
    useState<{ kind: SearchErrorKind; message: string } | null>(null);

  // Guards against out-of-order responses clobbering newer ones.
  const reqId = useRef(0);
  const systemsKey = systems.join(',');

  useEffect(() => {
    const q = debounced.trim();
    if (q.length < minLength) {
      setSuggestions([]);
      setError(null);
      setLoading(false);
      return;
    }

    const myReq = ++reqId.current;
    setLoading(true);
    setError(null);

    async function fetchSystem(slug: CodeSystemSlug): Promise<TextSearchResponse> {
      if (demoMode) {
        return mode === 'semantic'
          ? demoSemanticSearch(q)
          : demoTextSearch(slug, q);
      }
      return mode === 'semantic'
        ? searchSemantic(settings, slug, q)
        : searchText(settings, slug, q);
    }

    (async () => {
      try {
        const [primarySlug, ...secondarySlugs] = systems;
        // Primary failure surfaces an error; secondary failures degrade quietly
        // (e.g. one system returns 501) so the primary still works.
        const primaryResp = await fetchSystem(primarySlug);
        const secondarySettled = await Promise.allSettled(
          secondarySlugs.map((s) => fetchSystem(s)),
        );

        const responses: Record<string, TextSearchResponse> = {
          [primarySlug]: primaryResp,
        };
        secondarySettled.forEach((res, i) => {
          if (res.status === 'fulfilled') responses[secondarySlugs[i]] = res.value;
        });

        if (myReq !== reqId.current) return;
        setSuggestions(buildSuggestions(q, systems, responses, mode));
        setLoading(false);
      } catch (err) {
        if (myReq !== reqId.current) return;
        const kind: SearchErrorKind =
          err instanceof SearchError ? err.kind : 'unknown';
        const message =
          err instanceof Error ? err.message : 'Something went wrong.';
        setError({ kind, message });
        setSuggestions([]);
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, demoMode, settings, mode, systemsKey, minLength]);

  function reset() {
    setQuery('');
    setSuggestions([]);
    setError(null);
    setLoading(false);
  }

  return { query, setQuery, suggestions, loading, error, reset };
}
