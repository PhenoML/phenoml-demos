// PhenoStore natural-language chat server.
//
// Serves a single static chat page and translates plain-English questions into
// FHIR queries against a PhenoStore FHIR server using the PhenoML SDK.
//
//   - "cohort" mode  -> client.cohort.analyze()   (population / multi-concept criteria)
//   - "search" mode  -> client.lang2Fhir.search()  (a single resource-type query)
//
// Both paths only *translate* natural language into FHIR search queries; the
// translated queries are then executed against PhenoStore via client.fhir.search()
// to fetch the actual matching resources. All PhenoML credentials stay on the
// server -- the browser only ever talks to /api/query.

import express from "express";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import dotenv from "dotenv";
import { phenomlClient } from "phenoml";

dotenv.config();

const __dirname = dirname(fileURLToPath(import.meta.url));

const PORT = process.env.PORT || 3000;
const CLIENT_ID = process.env.PHENOML_CLIENT_ID;
const CLIENT_SECRET = process.env.PHENOML_CLIENT_SECRET;
const BASE_URL = process.env.PHENOML_BASE_URL || "https://experiment.app.pheno.ml";
const PROVIDER_ID = process.env.PHENOSTORE_PROVIDER_ID;

// Default page size so a broad question doesn't pull an unbounded bundle.
const DEFAULT_COUNT = "50";

if (!CLIENT_ID || !CLIENT_SECRET) {
  console.error(
    "Missing PHENOML_CLIENT_ID / PHENOML_CLIENT_SECRET. Set them in .env (see .env.example).",
  );
  process.exit(1);
}
if (!PROVIDER_ID) {
  console.error(
    "Missing PHENOSTORE_PROVIDER_ID. Set the FHIR provider to query in .env (see .env.example).",
  );
  process.exit(1);
}

// One client for the process; the SDK refreshes the OAuth token automatically.
const client = new phenomlClient({
  clientId: CLIENT_ID,
  clientSecret: CLIENT_SECRET,
  baseUrl: BASE_URL,
});

/**
 * Turn a FHIR search-parameter string ("name=John&birthdate=ge1960") into a
 * queryParams object for the SDK. Repeated keys (FHIR AND semantics) become an
 * array so none are dropped. A default _count is added to bound result size.
 */
function toQueryParams(searchParams: string | undefined): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const [key, value] of new URLSearchParams(searchParams ?? "")) {
    if (key in params) {
      const existing = params[key];
      params[key] = Array.isArray(existing) ? [...existing, value] : [existing, value];
    } else {
      params[key] = value;
    }
  }
  if (!("_count" in params)) params._count = DEFAULT_COUNT;
  return params;
}

/** A FHIR searchset Bundle, narrowed to the bits we summarize. */
interface Bundle {
  resourceType?: string;
  total?: number;
  entry?: Array<{ resource?: { resourceType?: string } }>;
}

/** Count of matches in a searchset bundle (prefer Bundle.total, fall back to entries). */
function bundleCount(bundle: Bundle): number {
  if (typeof bundle.total === "number") return bundle.total;
  return bundle.entry?.length ?? 0;
}

/** Execute one translated query against PhenoStore and return the raw bundle. */
async function runFhirSearch(resourceType: string, searchParams?: string): Promise<Bundle> {
  return (await client.fhir.search(PROVIDER_ID!, resourceType, {}, {
    queryParams: toQueryParams(searchParams),
  })) as Bundle;
}

const app = express();
app.use(express.json());
app.use(express.static(join(__dirname, "public")));

app.get("/health", (_req, res) => {
  res.json({ status: "ok", provider: PROVIDER_ID, baseUrl: BASE_URL });
});

app.post("/api/query", async (req, res) => {
  const question: unknown = req.body?.question;
  const mode: unknown = req.body?.mode;

  if (typeof question !== "string" || question.trim() === "") {
    return res.status(400).json({ error: "A non-empty 'question' is required." });
  }
  if (mode !== "cohort" && mode !== "search") {
    return res.status(400).json({ error: "'mode' must be 'cohort' or 'search'." });
  }

  try {
    if (mode === "search") {
      // Single resource-type natural-language query.
      const translation = await client.lang2Fhir.search({ text: question });
      const resourceType = translation.resource_type;
      const searchParams = translation.search_params;

      if (!resourceType) {
        return res.json({
          summary: "Couldn't identify a FHIR resource type for that question. Try rephrasing it.",
          raw: { translation },
        });
      }

      const bundle = await runFhirSearch(resourceType, searchParams);
      const count = bundleCount(bundle);
      const query = `${resourceType}?${searchParams ?? ""}`;

      return res.json({
        summary:
          `Searched PhenoStore for ${resourceType} resources and found ${count} match${count === 1 ? "" : "es"}.\n` +
          `Translated FHIR query: ${query}`,
        raw: { translation, results: bundle },
      });
    }

    // Cohort mode: a population described by one or more include/exclude concepts.
    const analysis = await client.cohort.analyze({ text: question });
    const concepts = analysis.queries ?? [];

    if (concepts.length === 0) {
      return res.json({
        summary:
          analysis.message ||
          "The cohort builder didn't return any search concepts for that description. Try adding more detail.",
        raw: { analysis },
      });
    }

    // Execute each concept's query against PhenoStore.
    const executed = await Promise.all(
      concepts.map(async (concept) => {
        const resourceType = concept.resource_type;
        if (!resourceType) {
          return { concept, error: "No resource type for this concept." };
        }
        try {
          const bundle = await runFhirSearch(resourceType, concept.search_params);
          return { concept, count: bundleCount(bundle), results: bundle };
        } catch (err) {
          return { concept, error: err instanceof Error ? err.message : String(err) };
        }
      }),
    );

    const lines = executed.map((item) => {
      const c = item.concept;
      const label = c.concept || c.resource_type || "concept";
      const kind = c.exclude ? "EXCLUDE" : "include";
      const query = `${c.resource_type ?? "?"}?${c.search_params ?? ""}`;
      if ("error" in item && item.error) return `  • [${kind}] ${label} — error: ${item.error}`;
      return `  • [${kind}] ${label} — ${item.count} match${item.count === 1 ? "" : "es"} (${query})`;
    });

    return res.json({
      summary:
        `${analysis.message ? analysis.message + "\n" : ""}` +
        `Broke your cohort into ${concepts.length} concept${concepts.length === 1 ? "" : "s"} and ran each against PhenoStore:\n` +
        lines.join("\n"),
      raw: { analysis, executed },
    });
  } catch (error) {
    console.error("Query failed:", error);
    return res.status(500).json({
      error: "Query failed.",
      message: error instanceof Error ? error.message : String(error),
    });
  }
});

app.listen(PORT, () => {
  console.log(`PhenoStore chat running on http://localhost:${PORT}`);
  console.log(`Querying FHIR provider ${PROVIDER_ID} via ${BASE_URL}`);
});
