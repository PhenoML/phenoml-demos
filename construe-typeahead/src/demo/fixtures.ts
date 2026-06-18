import type {
  CodeSystemSlug,
  SearchResultItem,
  SearchSystem,
  TextSearchResponse,
} from '../types';

// ---------------------------------------------------------------------------
// Demo Mode fixtures.
//
// Baked data shaped exactly like a real Construe TextSearchResponse, so the app
// is fully standalone with no creds. demoTextSearch() filters a per-system
// catalog by substring — mirroring Construe's substring text search — so the
// client-side ranking (api/ranking.ts) does the same work it does live.
//
// Coverage spans all four systems and deliberately includes co-occurrent
// "noise" (e.g. asthma) so the ranking demo is visible:
//   asth  → Asthma            (ICD-10-CM + SNOMED_CT_US_LITE)
//   albut → Albuterol         (RXNORM)
//   lipid panel → Lipid panel (LOINC)
//   plus hypertension, diabetes, COPD, metformin, lisinopril, A1c, CBC, etc.
// ---------------------------------------------------------------------------

export const SYSTEM_META: Record<CodeSystemSlug, SearchSystem> = {
  'ICD-10-CM': { name: 'ICD-10-CM', version: '2025' },
  SNOMED_CT_US_LITE: { name: 'SNOMED CT US', version: '2024-09' },
  RXNORM: { name: 'RxNorm', version: '2025-01' },
  LOINC: { name: 'LOINC', version: '2.78' },
};

const CATALOG: Record<CodeSystemSlug, SearchResultItem[]> = {
  'ICD-10-CM': [
    { code: 'J45.909', description: 'Unspecified asthma, uncomplicated' },
    { code: 'J45.901', description: 'Unspecified asthma with (acute) exacerbation' },
    { code: 'J45.40', description: 'Moderate persistent asthma, uncomplicated' },
    { code: 'J44.9', description: 'Chronic obstructive pulmonary disease, unspecified' },
    { code: 'I10', description: 'Essential (primary) hypertension' },
    { code: 'I11.9', description: 'Hypertensive heart disease without heart failure' },
    { code: 'E11.9', description: 'Type 2 diabetes mellitus without complications' },
    { code: 'E11.65', description: 'Type 2 diabetes mellitus with hyperglycemia' },
    { code: 'E11.22', description: 'Type 2 diabetes mellitus with diabetic chronic kidney disease' },
    { code: 'E78.5', description: 'Hyperlipidemia, unspecified' },
  ],
  SNOMED_CT_US_LITE: [
    { code: '195967001', description: 'Asthma' },
    { code: '389145006', description: 'Allergic asthma' },
    { code: '304527002', description: 'Acute asthma' },
    {
      code: '708090002',
      description: 'Acute exacerbation of asthma co-occurrent with allergic rhinitis',
    },
    { code: '195949008', description: 'Chronic asthmatic bronchitis' },
    { code: '38341003', description: 'Hypertension' },
    { code: '13644009', description: 'Hypercholesterolemia' },
    { code: '73211009', description: 'Diabetes mellitus' },
    { code: '44054006', description: 'Type 2 diabetes mellitus' },
    { code: '13645005', description: 'Chronic obstructive lung disease' },
  ],
  RXNORM: [
    { code: '435', description: 'Albuterol' },
    { code: '801095', description: 'Albuterol 90 MCG/ACTUAT inhalation aerosol' },
    { code: '745679', description: 'Albuterol 0.09 MG/ACTUAT metered dose inhaler' },
    { code: '6809', description: 'Metformin' },
    { code: '860975', description: 'Metformin hydrochloride 500 MG oral tablet' },
    { code: '29046', description: 'Lisinopril' },
    { code: '314076', description: 'Lisinopril 10 MG oral tablet' },
    { code: '83367', description: 'Atorvastatin' },
    { code: '617312', description: 'Atorvastatin 20 MG oral tablet' },
  ],
  LOINC: [
    { code: '24331-1', description: 'Lipid panel' },
    { code: '57698-3', description: 'Lipid panel with direct LDL - Serum or Plasma' },
    { code: '4548-4', description: 'Hemoglobin A1c/Hemoglobin.total in Blood' },
    { code: '2345-7', description: 'Glucose [Mass/volume] in Serum or Plasma' },
    { code: '58410-2', description: 'CBC panel - Blood by Automated count' },
    { code: '2160-0', description: 'Creatinine [Mass/volume] in Serum or Plasma' },
    { code: '3016-3', description: 'Thyrotropin [Units/volume] in Serum or Plasma' },
  ],
};

function buildResponse(
  slug: CodeSystemSlug,
  results: SearchResultItem[],
  limit: number,
): TextSearchResponse {
  const clipped = results.slice(0, limit);
  return { system: SYSTEM_META[slug], results: clipped, found: results.length };
}

/** Demo text search: case-insensitive substring match over the catalog. */
export function demoTextSearch(
  slug: CodeSystemSlug,
  query: string,
  limit = 8,
): TextSearchResponse {
  const q = query.trim().toLowerCase();
  if (!q) return buildResponse(slug, [], limit);
  const matches = CATALOG[slug].filter((item) =>
    item.description.toLowerCase().includes(q),
  );
  return buildResponse(slug, matches, limit);
}

// ---------------------------------------------------------------------------
// Demo semantic search (note field). Real semantic search matches by meaning,
// not substring — so we map clinical phrasing to SNOMED concepts via keyword
// triggers. Each trigger can surface multiple related concepts.
// ---------------------------------------------------------------------------
interface SemanticTrigger {
  match: string[];
  concepts: SearchResultItem[];
}

const SEMANTIC_TRIGGERS: SemanticTrigger[] = [
  {
    match: ['short of breath', 'shortness of breath', 'sob', 'dyspnea', 'breathless'],
    concepts: [
      { code: '267036007', description: 'Dyspnea' },
      { code: '60845006', description: 'Dyspnea on exertion' },
    ],
  },
  {
    match: ['wheez'],
    concepts: [{ code: '56018004', description: 'Wheezing' }],
  },
  {
    match: ['chest pain', 'chest tightness'],
    concepts: [
      { code: '29857009', description: 'Chest pain' },
      { code: '23924001', description: 'Heavy feeling in chest' },
    ],
  },
  {
    match: ['cough'],
    concepts: [
      { code: '49727002', description: 'Cough' },
      { code: '11833005', description: 'Dry cough' },
    ],
  },
  {
    match: ['fever', 'febrile'],
    concepts: [{ code: '386661006', description: 'Fever' }],
  },
  {
    match: ['headache', 'head ache'],
    concepts: [{ code: '25064002', description: 'Headache' }],
  },
  {
    match: ['fatigue', 'tired', 'exhausted'],
    concepts: [{ code: '84229001', description: 'Fatigue' }],
  },
  {
    match: ['nausea', 'nauseous'],
    concepts: [{ code: '422587007', description: 'Nausea' }],
  },
  {
    match: ['dizz', 'lightheaded', 'light-headed'],
    concepts: [{ code: '404640003', description: 'Dizziness' }],
  },
  {
    match: ['palpitation'],
    concepts: [{ code: '80313002', description: 'Palpitations' }],
  },
];

export function demoSemanticSearch(query: string, limit = 8): TextSearchResponse {
  const q = query.trim().toLowerCase();
  const seen = new Set<string>();
  const results: SearchResultItem[] = [];
  if (q.length >= 3) {
    for (const trigger of SEMANTIC_TRIGGERS) {
      if (trigger.match.some((m) => q.includes(m))) {
        for (const concept of trigger.concepts) {
          if (!seen.has(concept.code)) {
            seen.add(concept.code);
            results.push(concept);
          }
        }
      }
    }
  }
  return buildResponse('SNOMED_CT_US_LITE', results, limit);
}
