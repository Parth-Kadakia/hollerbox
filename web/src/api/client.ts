// Typed wrapper for the HollerBox HTTP API. One function per endpoint.
// Dev: relies on the Vite proxy (`/api/*` → http://127.0.0.1:8787/*).
// Prod: relies on the API being served from the same origin under /api/*.

import type {
  ApprovalDecision,
  ChatMessage,
  ConversationSummary,
  ProvidersResponse,
  RunDetail,
  RunSummary,
  SecretPresence,
  SendMessageResponse,
  WorkflowDetail,
  WorkflowSummary,
  WorkflowValidateResponse,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`HTTP ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // body wasn't JSON — keep the status text
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

// --------------------------- health ---------------------------

export function getHealth() {
  return request<{ status: string; version: string }>("/health");
}

// --------------------------- workflows ---------------------------

export function listWorkflows() {
  return request<WorkflowSummary[]>("/workflows");
}

export function getWorkflow(name: string) {
  return request<WorkflowDetail>(`/workflows/${encodeURIComponent(name)}`);
}

export function upsertWorkflow(name: string, yamlSource: string) {
  return request<WorkflowDetail>(`/workflows/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ yaml_source: yamlSource }),
  });
}

export function validateWorkflow(yamlSource: string) {
  return request<WorkflowValidateResponse>("/workflows/validate", {
    method: "POST",
    body: JSON.stringify({ yaml_source: yamlSource }),
  });
}

export function deleteWorkflow(name: string) {
  return request<void>(`/workflows/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

// --------------------------- runs ---------------------------

export function listRuns(opts?: { workflow?: string; limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.workflow) params.set("workflow", opts.workflow);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<RunSummary[]>(`/runs${qs ? `?${qs}` : ""}`);
}

export function getRun(runId: string) {
  return request<RunDetail>(`/runs/${runId}`);
}

export function enqueueRun(
  name: string,
  opts?: { inputs?: Record<string, unknown>; dry_run?: boolean; trigger_kind?: "manual" | "chat" },
) {
  return request<RunSummary>(`/workflows/${encodeURIComponent(name)}/run`, {
    method: "POST",
    body: JSON.stringify({
      inputs: opts?.inputs ?? {},
      dry_run: opts?.dry_run ?? false,
      trigger_kind: opts?.trigger_kind ?? "manual",
    }),
  });
}

// --------------------------- approvals ---------------------------

export function approveRun(runId: string) {
  return request<ApprovalDecision>(`/runs/${runId}/approve`, { method: "POST" });
}

export function rejectRun(runId: string) {
  return request<ApprovalDecision>(`/runs/${runId}/reject`, { method: "POST" });
}

export function cancelRun(runId: string) {
  return request<ApprovalDecision>(`/runs/${runId}/cancel`, { method: "POST" });
}

// --------------------------- providers ---------------------------

export function listProviders() {
  return request<ProvidersResponse>("/providers");
}

// --------------------------- secrets ---------------------------

export function listSecrets() {
  return request<SecretPresence[]>("/secrets");
}

export function setSecret(name: string, value: string) {
  return request<SecretPresence>(`/secrets/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ value }),
  });
}

export function deleteSecret(name: string) {
  return request<void>(`/secrets/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

// --------------------------- settings ---------------------------

export function getSettings() {
  return request<Record<string, unknown>>("/settings");
}

export function setSetting(key: string, value: unknown) {
  return request<{ value: unknown }>(`/settings/${encodeURIComponent(key)}`, {
    method: "PUT",
    body: JSON.stringify({ value }),
  });
}

// --------------------------- conversations ---------------------------

export function listConversations() {
  return request<ConversationSummary[]>("/conversations");
}

export function createConversation(title = "") {
  return request<ConversationSummary>("/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function deleteConversation(convId: string) {
  return request<void>(`/conversations/${convId}`, { method: "DELETE" });
}

export function listMessages(convId: string) {
  return request<ChatMessage[]>(`/conversations/${convId}/messages`);
}

export function sendMessage(
  convId: string,
  content: string,
  opts?: { provider?: string; model?: string },
) {
  return request<SendMessageResponse>(`/conversations/${convId}/messages`, {
    method: "POST",
    body: JSON.stringify({
      content,
      ...(opts?.provider ? { provider: opts.provider } : {}),
      ...(opts?.model ? { model: opts.model } : {}),
    }),
  });
}

export function streamConversationEvents(
  convId: string,
  onMessage: (msg: ChatMessage) => void,
  onDone?: () => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`${BASE}/conversations/${convId}/events`);
  es.addEventListener("message", (ev: MessageEvent) => {
    try {
      onMessage(JSON.parse(ev.data) as ChatMessage);
    } catch {
      // ignore malformed
    }
  });
  es.addEventListener("done", () => {
    onDone?.();
    es.close();
  });
  if (onError) es.addEventListener("error", onError);
  return es;
}

// --------------------------- SSE ---------------------------

export interface RunStreamEvent {
  event: "status" | "step" | "done";
  data: unknown;
}

/** Subscribe to a run's SSE stream. Returns the EventSource so callers can close it. */
export function streamRunEvents(
  runId: string,
  onEvent: (e: RunStreamEvent) => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`${BASE}/runs/${runId}/events`);
  ["status", "step", "done"].forEach((name) => {
    es.addEventListener(name, (ev: MessageEvent) => {
      try {
        onEvent({ event: name as RunStreamEvent["event"], data: JSON.parse(ev.data) });
      } catch {
        // ignore malformed events
      }
    });
  });
  if (onError) es.addEventListener("error", onError);
  return es;
}
