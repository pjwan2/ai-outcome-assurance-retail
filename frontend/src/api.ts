const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface CaseSummary {
  case_id: string;
  order_ref: string;
  seller_ref: string;
  product_ref: string;
  risk_band: string;
  status: string;
  state_version: number;
  source_refs: string[];
  created_at: string | null;
}

export interface Claim {
  claim_id: string;
  claim_type: string;
  status: "TRUE" | "FALSE" | "UNKNOWN";
  evidence_ids: string[];
  counter_evidence_ids: string[];
  rule_version: string;
  reason_codes: string[];
}

export interface Evidence {
  evidence_id: string;
  source_id: string;
  locator: string;
  excerpt: string;
  excerpt_kind: string;
  authority_status: string;
  entity_binding_status: string;
  support_status: string;
  validation_reasons: string[];
}

export interface AuthorityRecord {
  authority_id: string;
  proposed_action: string;
  decision: "ALLOW" | "DENY" | "REQUIRE_HUMAN";
  reason_codes: string[];
  required_role: string;
  policy_version: string;
}

export interface TraceEvent {
  sequence: number;
  stage: string;
  event_type: string;
  tool_name: string | null;
  evidence_ids: string[];
  timestamp: string | null;
}

export interface ReviewTask {
  review_id: string;
  case_id: string;
  status: string;
  reason_codes: string[];
  assigned_role: string;
  reviewer_id: string | null;
  reviewer_decision: string | null;
  reviewer_notes: string | null;
  created_at: string | null;
  decided_at: string | null;
}

export interface ReleaseResult {
  release_id: string;
  config_name: string;
  decision: "PASS" | "BLOCK";
  reason_codes: string[];
  critical_positive_recovered: number;
  critical_positive_total: number;
  critical_recall: number;
  critical_recall_wilson_lower_bound_95: number;
  dataset_version: string;
  thresholds_version: string;
  regression_fixture_check: ReleaseResult | null;
}

export const api = {
  createCase: () => request<CaseSummary>("/api/cases", { method: "POST" }),
  getCase: (caseId: string) => request<CaseSummary>(`/api/cases/${caseId}`),
  getClaims: (caseId: string) => request<Claim[]>(`/api/cases/${caseId}/claims`),
  getEvidence: (caseId: string) => request<Evidence[]>(`/api/cases/${caseId}/evidence`),
  getAuthority: (caseId: string) => request<AuthorityRecord[]>(`/api/cases/${caseId}/authority`),
  getTrace: (caseId: string) => request<TraceEvent[]>(`/api/cases/${caseId}/trace`),
  replayCase: (caseId: string) => request<CaseSummary>(`/api/cases/${caseId}/replay`, { method: "POST" }),
  listReviews: () => request<ReviewTask[]>("/api/reviews"),
  decideReview: (reviewId: string, body: { reviewer_id: string; decision: string; notes?: string; idempotency_key: string }) =>
    request<ReviewTask>(`/api/reviews/${reviewId}/decision`, { method: "POST", body: JSON.stringify(body) }),
  getLatestRelease: () => request<ReleaseResult>("/api/releases/latest"),
};
