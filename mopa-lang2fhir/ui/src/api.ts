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

export interface Health {
  configured: boolean;
  fhir_provider_id: string | null;
  profile_upload_capable: boolean;
}

export interface SourceArtifact {
  name: string;
  use: string;
  used: boolean;
}

export interface RequirementMap {
  type: string;
  label: string;
  code: string | null;
  source: string;
  used: boolean;
}

export interface SourceData {
  report_text: string;
  artifacts: SourceArtifact[];
  mapped_requirements: RequirementMap[];
  requirements: any;
  regimen_template: any;
}

export interface ExtractResult {
  extraction_id: string;
  resources: any[];
  base_resources: any[];
  bundle: any;
  summary_bundle: any;
  regimen: any;
  source_map: RequirementMap[];
}

export interface ProfileInfo {
  file: string;
  id: string | null;
  url: string | null;
  name: string | null;
  type: string | null;
  valid: boolean;
  error: string | null;
}

export const api = {
  health: () => req<Health>("/health"),
  sourceData: () => req<SourceData>("/source-data"),
  extract: (report_text: string, include_her2: boolean, her2_result: string, her2_positive: boolean) =>
    req<ExtractResult>("/extract", "POST", { report_text, include_her2, her2_result, her2_positive }),
  summary: (extraction_id: string) =>
    req<{ summary: string }>("/summary", "POST", { extraction_id }),
  writeBundle: (extraction_id: string) =>
    req<{ provider: string; locations: string[]; patient_id: string | null; response: any }>(
      "/fhir/write", "POST", { extraction_id }),
  profiles: () => req<{ profiles: ProfileInfo[] }>("/profiles"),
  uploadProfiles: () =>
    req<{ ok: boolean; message: string; results: any[] }>("/profiles/upload", "POST"),
};
