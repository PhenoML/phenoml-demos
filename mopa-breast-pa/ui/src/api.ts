// Thin typed client for the MOPA prior-auth backend (ui_server.py). In dev, Vite proxies /api to
// the FastAPI server on :8001 (see vite.config.ts), so these are same-origin fetches.

async function req<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data && (data.detail || data.message)) || `HTTP ${res.status}`);
  return data as T;
}

export interface ReadinessItem { label: string; type: string; code?: string | null; }
export interface Readiness {
  satisfied: ReadinessItem[];
  missing: ReadinessItem[];
  follow_up_questions: string[];
}
export interface IntakeResult {
  intake_id: string;
  patient_name: string;
  patient_id: string | null;
  resources: any[];
  construe_codes: Record<string, any[]>;
  regimen: any;
  ips_text: string;
  readiness: Readiness;
  write: { ok: boolean; error: string | null; patient_id: string | null; locations: string[] };
}
export interface ClaimRecord {
  id: string;
  fhir_claim_id: string | null;
  persisted: boolean;
  patient_name: string;
  regimen_text: string;
  created: string;
  status: "queued" | "approved" | "denied";
  decision: any;
}
export interface ClaimDetail {
  claim: ClaimRecord;
  patient_name: string;
  ips_text: string;
  regimen: any;
  resources: any[];
  readiness: Readiness;
  construe_codes: Record<string, any[]>;
  decision: any;
}
export interface Card {
  summary?: string;
  indicator?: string;
  detail?: string;
  links?: { label?: string; url?: string; type?: string }[];
}
export interface Recommendation {
  outcome: string;
  decision: string;
  card: Card;
  coverage: any | null;
  her2_used: string;
}

export const api = {
  health: () => req<{ configured: boolean; provider: string | null }>("/health"),
  sampleReport: () => req<{ report_text: string }>("/sample-report"),
  intake: (report_text: string) => req<IntakeResult>("/intake", "POST", { report_text }),
  submit: (intake_id: string, her2_result: string, her2_positive: boolean) =>
    req<{ claim: ClaimRecord; her2_writeback: any; readiness: Readiness }>(
      "/submit", "POST", { intake_id, her2_result, her2_positive }),
  claims: () => req<{ claims: ClaimRecord[] }>("/claims"),
  claim: (id: string) => req<ClaimDetail>(`/claims/${id}`),
  recommend: (id: string, her2_override: string | null) =>
    req<Recommendation>(`/claims/${id}/recommendation`, "POST", { her2_override }),
  decide: (id: string, decision: "approve" | "deny", note: string, citations: string[], coverage: any) =>
    req<{ claim: ClaimRecord }>(`/claims/${id}/decision`, "POST", { decision, note, citations, coverage }),
};
