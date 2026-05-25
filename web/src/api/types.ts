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

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  kind: MessageKind;
  run_id: string | null;
  created_at: string;
}

export interface SendMessageResponse {
  user_message_id: string;
  assistant_message_ids: string[];
  messages: ChatMessage[];
}
