export type RecallFeedRow = {
  recall_case_id: string;
  state: string;
  source_type: string | null;
  updated_at_utc: string;
  severity: string | null;
  hazard_type: string | null;
  recall_id: string | null;
};

export type RecallOverview = {
  recall_case_id: string;
  state: string;
  source_type: string | null;
  source_details: Record<string, unknown>;
  recall_spec: Record<string, unknown> | null;
};

export type BlastRadius = {
  blast_radius: any | null;
};

export type TransactionRow = {
  transaction_id: string;
  store_id: string;
  timestamp_utc: string;
  affected_probability: number;
  confidence_tier: string;
  customer_initials: string | null;
  email_masked: string | null;
};

export type TaskRow = {
  id: string;
  task_type: string;
  status: string;
  payload: Record<string, unknown>;
  created_at_utc: string;
};

export type DraftRow = {
  id: string;
  channel: string;
  confidence_tier: string;
  draft: Record<string, unknown>;
  created_at_utc: string;
};

export type ComplianceEventRow = {
  event_type: string;
  message: string;
  payload: Record<string, unknown>;
  created_at_utc: string;
};

export type AgentTelemetryRow = {
  agent: string;
  state: string;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  ts: string;
};

export type AgentsTelemetry = {
  recall_case_id: string | null;
  recall_state: string | null;
  agents: AgentTelemetryRow[];
};

export type GpuTelemetry = {
  memory_pct: number;
  compute_pct: number;
  ts: string;
  mi300x_identifier: string;
  rocm_version: string;
  vllm_version: string;
  model_name: string;
  source: string;
};

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export const api = {
  listRecalls: async () => apiFetch<{ recalls: RecallFeedRow[] }>("/api/recalls"),
  getRecallOverview: async (id: string) => apiFetch<RecallOverview>(`/api/recalls/${id}/overview`),
  getBlastRadius: async (id: string) => apiFetch<BlastRadius>(`/api/recalls/${id}/blast_radius`),
  getTransactions: async (id: string) => apiFetch<{ transactions: TransactionRow[] }>(`/api/recalls/${id}/transactions`),
  getTasks: async (id: string) => apiFetch<{ tasks: TaskRow[] }>(`/api/recalls/${id}/tasks`),
  getDrafts: async (id: string) => apiFetch<{ drafts: DraftRow[] }>(`/api/recalls/${id}/drafts`),
  getCompliance: async (id: string) => apiFetch<{ events: ComplianceEventRow[] }>(`/api/recalls/${id}/compliance`),
  createApproval: async (id: string, body: { approved_by: string; action: string }) =>
    apiFetch<{ approval_id: string; approvals_count: number }>(`/api/recalls/${id}/approvals`, {
      method: "POST",
      body: JSON.stringify(body)
    }),
  getAgentsTelemetry: async () => apiFetch<AgentsTelemetry>("/api/telemetry/agents"),
  getGpuTelemetry: async () => apiFetch<GpuTelemetry>("/api/telemetry/gpu")
};

