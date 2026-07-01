import { useEffect, useRef, useState } from 'react';
import { useDebouncedValue } from '@mantine/hooks';
import { searchSemantic, searchText } from '../api/construe';
import { rankResults } from '../api/ranking';
import { cleanDisplay } from '../api/labels';
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
   * contribute their top-ranked search result for the same query. This is
   * useful for side-by-side demo reveal; it is not cross-system mapping.
   */
  systems: CodeSystemSlug[];
  mode: SearchMode;
  /** Minimum trimmed query length before a search fires. */
  minLength?: number;
  /**
   * When true, strip parenthetical qualifiers from the displayed label (e.g.
   * "Essential (primary) hypertension" → "Essential hypertension"). Stored
   * code descriptions keep the raw API text.
   */
  cleanLabels?: boolean;
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
  cleanLabels: boolean,
): Suggestion[] {
  const [primarySlug, ...secondarySlugs] = systems;
  const primary = responses[primarySlug];
  if (!primary) return [];

  // Ranking runs on the RAW description; cleaning is applied afterwards to the
  // text that ships to the UI, so display tidying never changes result order.
  const shape = (item: SearchResultItem): SearchResultItem =>
    cleanLabels ? { ...item, description: cleanDisplay(item.description) } : item;

  // Semantic results are already ranked by meaning server-side; only re-rank
  // substring-based text results.
  const primaryItems =
    mode === 'text' ? rankResults(query, primary.results) : primary.results;

  // Each additional system contributes its single best search result for the
  // same query. This is not a cross-system mapping.
  const secondaryTops: CodedConcept[] = [];
  for (const slug of secondarySlugs) {
    const resp = responses[slug];
    if (!resp || resp.results.length === 0) continue;
    const ranked = mode === 'text' ? rankResults(query, resp.results) : resp.results;
    secondaryTops.push(toConcept(resp.system, ranked[0]));
  }

  return primaryItems.map((item) => {
    const shaped = shape(item);
    return {
      id: `${primarySlug}:${item.code}`,
      label: shaped.description,
      codes: [toConcept(primary.system, item), ...secondaryTops],
    };
  });
}

export function useTypeahead({
  systems,
  mode,
  minLength = 2,
  cleanLabels = false,
}: UseTypeaheadArgs): TypeaheadState {
  const { demoMode } = useAppState();
  const [query, setQueryState] = useState('');
  const [debounced] = useDebouncedValue(query, 250);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] =
    useState<{ kind: SearchErrorKind; message: string } | null>(null);

  // Guards against out-of-order responses clobbering newer ones.
  const reqId = useRef(0);
  const activeController = useRef<AbortController | null>(null);
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
    const controller = new AbortController();
    activeController.current = controller;
    setLoading(true);
    setError(null);

    async function fetchSystem(
      slug: CodeSystemSlug,
      signal: AbortSignal,
    ): Promise<TextSearchResponse> {
      if (demoMode) {
        return mode === 'semantic'
          ? demoSemanticSearch(q)
          : demoTextSearch(slug, q);
      }
      return mode === 'semantic'
        ? searchSemantic(slug, q, 8, signal)
        : searchText(slug, q, 8, signal);
    }

    (async () => {
      try {
        // Start all system requests together. Primary failure surfaces an error;
        // secondary failures degrade quietly (e.g. one system returns 501) so
        // the primary still works.
        const settled = await Promise.allSettled(
          systems.map((s) => fetchSystem(s, controller.signal)),
        );
        const primarySlug = systems[0];
        const primaryResult = settled[0];
        if (primaryResult.status === 'rejected') throw primaryResult.reason;

        const responses: Record<string, TextSearchResponse> = {
          [primarySlug]: primaryResult.value,
        };
        settled.slice(1).forEach((res, i) => {
          if (res.status === 'fulfilled') responses[systems[i + 1]] = res.value;
        });

        if (myReq !== reqId.current) return;
        setSuggestions(buildSuggestions(q, systems, responses, mode, cleanLabels));
        setLoading(false);
      } catch (err) {
        if (controller.signal.aborted || myReq !== reqId.current) return;
        const kind: SearchErrorKind =
          err instanceof SearchError ? err.kind : 'unknown';
        const message =
          err instanceof Error ? err.message : 'Something went wrong.';
        setError({ kind, message });
        setSuggestions([]);
        setLoading(false);
      }
    })();
    return () => {
      reqId.current += 1;
      if (activeController.current === controller) {
        activeController.current = null;
      }
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, demoMode, mode, systemsKey, minLength, cleanLabels]);

  function setQuery(q: string) {
    reqId.current += 1;
    activeController.current?.abort();
    setQueryState(q);
  }

  function reset() {
    reqId.current += 1;
    activeController.current?.abort();
    setQueryState('');
    setSuggestions([]);
    setError(null);
    setLoading(false);
  }

  return { query, setQuery, suggestions, loading, error, reset };
}
