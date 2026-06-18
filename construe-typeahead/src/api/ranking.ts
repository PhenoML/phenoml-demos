import type { SearchResultItem } from '../types';

// ---------------------------------------------------------------------------
// Client-side re-ranking.
//
// Construe text search is substring-based, so a query like "asth" returns long
// co-occurrent descriptors ("Acute exacerbation of asthma co-occurrent with
// allergic rhinitis") alongside the plain concept "Asthma". For a plain prefix
// the plain concept should win. We re-rank so that:
//   1. exact-prefix matches float to the top,
//   2. shorter descriptions beat longer ones,
//   3. combination / co-occurrent concepts are demoted.
// ---------------------------------------------------------------------------

// Tokens that signal a combination / co-occurrent / qualified concept. Their
// presence pushes a result down so the plain concept surfaces first.
const COMBINATION_MARKERS = [
  'co-occurrent',
  'cooccurrent',
  ' with ',
  ' due to ',
  ' associated with ',
  ' and ',
  ' in ',
  ' without ',
  ' complicating ',
  ' secondary to ',
];

function norm(s: string): string {
  return s.trim().toLowerCase();
}

/**
 * Score a single result against the query. Higher is better.
 * Pure function of (query, item) so it is trivially testable.
 */
export function scoreResult(query: string, item: SearchResultItem): number {
  const q = norm(query);
  const desc = norm(item.description);
  if (!q) return 0;

  let score = 0;

  // Exact match of the whole description — the strongest signal.
  if (desc === q) score += 1000;

  // Prefix match: the description starts with the typed query.
  if (desc.startsWith(q)) score += 500;
  // Whole-word match somewhere (e.g. query "asthma" inside the description).
  else if (new RegExp(`\\b${escapeRegExp(q)}\\b`).test(desc)) score += 200;
  // Plain substring (the default Construe behaviour) — weakest positive.
  else if (desc.includes(q)) score += 80;

  // Demote combination / co-occurrent concepts.
  for (const marker of COMBINATION_MARKERS) {
    if (desc.includes(marker.trim()) && desc.includes(marker)) {
      score -= 120;
      break;
    }
  }

  // Prefer shorter, plainer descriptions. Subtract a gentle length penalty so
  // "Asthma" (6 chars) beats a 60-char co-occurrent descriptor on a tie.
  score -= desc.length * 0.8;

  // A description with a comma or parenthetical qualifier is usually more
  // specific/longer than the plain concept — small extra demotion.
  if (desc.includes(',') || desc.includes('(')) score -= 15;

  return score;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Re-rank Construe results client-side for a plain-prefix type-ahead. Stable
 * for equal scores (preserves the server order as a tiebreaker).
 */
export function rankResults(
  query: string,
  results: SearchResultItem[],
): SearchResultItem[] {
  return results
    .map((item, index) => ({ item, index, score: scoreResult(query, item) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((r) => r.item);
}
