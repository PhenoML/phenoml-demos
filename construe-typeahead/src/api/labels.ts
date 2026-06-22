// ---------------------------------------------------------------------------
// Display-text cleaning.
//
// Code-system descriptions often carry parenthetical qualifiers that read as
// clutter to a clinician, e.g. "Unspecified asthma with (acute) exacerbation"
// or "Essential (primary) hypertension". For display we strip those "(...)"
// segments and tidy the surrounding whitespace/punctuation so the label reads
// as plain human text. The underlying CODE is never touched — only the text.
// ---------------------------------------------------------------------------

/**
 * Strip "(...)" qualifiers from a description and tidy whitespace/punctuation.
 * Pure function so it is trivially testable.
 *
 *   "Unspecified asthma with (acute) exacerbation" -> "Unspecified asthma with exacerbation"
 *   "Essential (primary) hypertension"             -> "Essential hypertension"
 *   "Asthma"                                        -> "Asthma" (unchanged)
 */
export function cleanDisplay(description: string): string {
  const cleaned = description
    .replace(/\s*\([^)]*\)/g, '') // drop " (qualifier)" segments
    .replace(/\s{2,}/g, ' ') // collapse doubled spaces
    .replace(/\s+([,;])/g, '$1') // fix stray space before a comma/semicolon
    .trim();

  // If the description was entirely parenthetical, never render blank.
  return cleaned || description;
}
