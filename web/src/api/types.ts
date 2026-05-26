// Mirrors `backend/api/schemas.py`. Kept in sync by hand for now —
// once Phase 4 settles we'll consider generating from /openapi.json.

export type RunStatus =
  | "queued"
  | "running"
  | "paused"
  | "success"
  | "failed"
  | "cancelled";

export type StepStatus =
  | "success"
  | "failed"
  | "skipped"
  | "dry_run"
  | "pending_approval";

export interface WorkflowSummary {
  name: string;
  version: number;
  description: string;
  enabled: boolean;
  updated_at: string;
}

export interface WorkflowDetail extends WorkflowSummary {
  yaml_source: string;
}

export interface WorkflowValidateResponse {
  valid: boolean;
  name: string | null;
  step_ids: string[];
  references: string[];
  errors: string[];
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  yaml_source: string;
  step_count: number;
}

export interface StepRunDetail {
  step_id: string;
  step_type: string;
  status: StepStatus;
  resolved_input: Record<string, unknown>;
  output: Record<string, unknown>;
  logs: string[];
  error: string | null;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  /** Optional because older backends won't emit this field over SSE. */
  attachments?: FileAttachment[];
}

export interface RunSummary {
  id: string;
  workflow_name: string;
  status: RunStatus;
  dry_run: boolean;
  trigger_kind: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_at: string;
}

export interface RunDetail extends RunSummary {
  inputs: Record<string, unknown>;
  steps: StepRunDetail[];
}

export interface ApprovalDecision {
  run_id: string;
  status: RunStatus;
  last_step_id?: string | null;
  error?: string | null;
}

export interface SecretPresence {
  name: string;
  set: true;
}

export interface ProviderStatus {
  name: string;
  kind: "text" | "image";
  status: "ready" | "missing-sdk" | "no-key";
  detail: string;
  /** Locally-enumerable model ids (Ollama). Empty for hosted providers. */
  models?: string[];
}

export interface ProvidersResponse {
  text: ProviderStatus[];
  image: ProviderStatus[];
}

// --------------------------- conversations ---------------------------

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export type MessageKind = "text" | "ack" | "approval_request" | "result" | "error";

export interface FileAttachment {
  kind: "image" | "file";
  /** Absolute path on the server's filesystem (informational only). */
  path: string;
  /** API-relative URL — prepend the API base when rendering. */
  url: string;
  name: string;
  size_bytes: number | null;
}

/** @deprecated kept for callers that imported the old name. */
export type MessageAttachment = FileAttachment;

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  kind: MessageKind;
  run_id: string | null;
  created_at: string;
  /** Optional because older backends won't emit this field over SSE. */
  attachments?: FileAttachment[];
}

export interface SendMessageResponse {
  user_message_id: string;
  assistant_message_ids: string[];
  messages: ChatMessage[];
}
