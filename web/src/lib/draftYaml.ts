// Convert between the form-builder's typed `WorkflowDraft` and the raw
// YAML the engine consumes. Keeps the form UI in one shape and the
// over-the-wire format in another so they can evolve independently.

import yaml from "js-yaml";

export type StepKind =
  | "shell"
  | "python_step"
  | "http"
  | "read_file"
  | "write_file"
  | "llm"
  | "image";

interface StepBase {
  id: string;
  destructive?: boolean;
  requires_confirmation?: boolean;
}

export interface ShellStep extends StepBase {
  type: "shell";
  command: string;
}
export interface PythonStep extends StepBase {
  type: "python_step";
  code: string;
}
export interface HttpStep extends StepBase {
  type: "http";
  method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  url: string;
  body: string;
}
export interface ReadFileStep extends StepBase {
  type: "read_file";
  path: string;
}
export interface WriteFileStep extends StepBase {
  type: "write_file";
  path: string;
  content: string;
}
export interface LLMStep extends StepBase {
  type: "llm";
  provider: string;
  model: string;
  system: string;
  prompt: string;
  attachments: string[];
}
export interface ImageStep extends StepBase {
  type: "image";
  provider: string;
  model: string;
  prompt: string;
  size: string;
  save_to: string;
}

export type DraftStep =
  | ShellStep
  | PythonStep
  | HttpStep
  | ReadFileStep
  | WriteFileStep
  | LLMStep
  | ImageStep;

export interface WorkflowDraft {
  name: string;
  description: string;
  inputs: Array<{ key: string; default: string }>;
  steps: DraftStep[];
}

// --------------------------- step factory ---------------------------

export function newStep(kind: StepKind, id: string): DraftStep {
  switch (kind) {
    case "shell":
      return { id, type: "shell", command: "echo hello" };
    case "python_step":
      return {
        id,
        type: "python_step",
        code: "output = {\"value\": 1}\n",
      };
    case "http":
      return { id, type: "http", method: "GET", url: "https://example.com", body: "" };
    case "read_file":
      return { id, type: "read_file", path: "/tmp/in.txt" };
    case "write_file":
      return {
        id,
        type: "write_file",
        path: "/tmp/out.txt",
        content: "",
        destructive: true,
        requires_confirmation: true,
      };
    case "llm":
      return {
        id,
        type: "llm",
        provider: "anthropic",
        model: "",
        system: "",
        prompt: "Hello, world.",
        attachments: [],
      };
    case "image":
      return {
        id,
        type: "image",
        provider: "openai",
        model: "",
        prompt: "a children's book illustration",
        size: "1024x1024",
        save_to: "/tmp/hollerbox-image.png",
        destructive: true,
        requires_confirmation: true,
      };
  }
}

export const STEP_KINDS: { kind: StepKind; label: string; hint: string }[] = [
  { kind: "shell", label: "Shell", hint: "Run a shell command" },
  { kind: "http", label: "HTTP", hint: "Make an HTTP request" },
  { kind: "llm", label: "LLM", hint: "Call an AI model with a prompt" },
  { kind: "image", label: "Image", hint: "Generate an image from a prompt" },
  { kind: "read_file", label: "Read file", hint: "Read a file from disk" },
  { kind: "write_file", label: "Write file", hint: "Write content to a file" },
  { kind: "python_step", label: "Python", hint: "Run a Python snippet" },
];

// --------------------------- serialize ---------------------------

function stepConfig(step: DraftStep): Record<string, unknown> {
  switch (step.type) {
    case "shell":
      return { command: step.command };
    case "python_step":
      return { code: step.code };
    case "http": {
      const cfg: Record<string, unknown> = { method: step.method, url: step.url };
      if (step.body.trim()) cfg.body = step.body;
      return cfg;
    }
    case "read_file":
      return { path: step.path };
    case "write_file":
      return { path: step.path, content: step.content };
    case "llm": {
      const cfg: Record<string, unknown> = { prompt: step.prompt };
      if (step.provider) cfg.provider = step.provider;
      if (step.model) cfg.model = step.model;
      if (step.system) cfg.system = step.system;
      if (step.attachments && step.attachments.length > 0)
        cfg.attachments = step.attachments;
      return cfg;
    }
    case "image": {
      const cfg: Record<string, unknown> = {
        prompt: step.prompt,
        save_to: step.save_to,
      };
      if (step.provider) cfg.provider = step.provider;
      if (step.model) cfg.model = step.model;
      if (step.size) cfg.size = step.size;
      return cfg;
    }
  }
}

export function draftToYaml(draft: WorkflowDraft): string {
  const inputs: Record<string, string> = {};
  for (const { key, default: d } of draft.inputs) {
    if (key.trim()) inputs[key.trim()] = d;
  }
  const top: Record<string, unknown> = {
    name: draft.name,
    version: 1,
  };
  if (draft.description) top.description = draft.description;
  if (Object.keys(inputs).length > 0) top.inputs = inputs;
  top.steps = draft.steps.map((s) => {
    const out: Record<string, unknown> = {
      id: s.id,
      type: s.type,
      config: stepConfig(s),
    };
    if (s.destructive) out.destructive = true;
    if (s.requires_confirmation) out.requires_confirmation = true;
    return out;
  });
  return yaml.dump(top, { lineWidth: 100, noRefs: true });
}

// --------------------------- parse ---------------------------

function parseStep(raw: unknown, idx: number): DraftStep | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const id = typeof r.id === "string" ? r.id : `step_${idx + 1}`;
  const cfg = (r.config as Record<string, unknown>) ?? {};
  const base = {
    id,
    destructive: r.destructive === true,
    requires_confirmation: r.requires_confirmation === true,
  };
  const type = r.type as StepKind | undefined;
  switch (type) {
    case "shell":
      return { ...base, type, command: String(cfg.command ?? "") };
    case "python_step":
      return { ...base, type, code: String(cfg.code ?? "") };
    case "http":
      return {
        ...base,
        type,
        method:
          (cfg.method as HttpStep["method"]) && ["GET", "POST", "PUT", "DELETE", "PATCH"].includes(
            String(cfg.method).toUpperCase(),
          )
            ? (String(cfg.method).toUpperCase() as HttpStep["method"])
            : "GET",
        url: String(cfg.url ?? ""),
        body: typeof cfg.body === "string" ? cfg.body : "",
      };
    case "read_file":
      return { ...base, type, path: String(cfg.path ?? "") };
    case "write_file":
      return {
        ...base,
        type,
        path: String(cfg.path ?? ""),
        content: String(cfg.content ?? ""),
      };
    case "llm":
      return {
        ...base,
        type,
        provider: String(cfg.provider ?? ""),
        model: String(cfg.model ?? ""),
        system: String(cfg.system ?? ""),
        prompt: String(cfg.prompt ?? ""),
        attachments: Array.isArray(cfg.attachments)
          ? cfg.attachments.filter((x): x is string => typeof x === "string")
          : [],
      };
    case "image":
      return {
        ...base,
        type,
        provider: String(cfg.provider ?? ""),
        model: String(cfg.model ?? ""),
        prompt: String(cfg.prompt ?? ""),
        size: String(cfg.size ?? "1024x1024"),
        save_to: String(cfg.save_to ?? ""),
      };
  }
  return null;
}

export interface ParseResult {
  draft: WorkflowDraft | null;
  /** Reasons the YAML can't be edited in the form view (unsupported step type, etc.). */
  reasons: string[];
}

export function yamlToDraft(text: string): ParseResult {
  const reasons: string[] = [];
  let parsed: unknown;
  try {
    parsed = yaml.load(text);
  } catch (e) {
    reasons.push(`YAML parse error: ${e instanceof Error ? e.message : String(e)}`);
    return { draft: null, reasons };
  }
  if (!parsed || typeof parsed !== "object") {
    reasons.push("Top-level YAML is not a mapping");
    return { draft: null, reasons };
  }
  const obj = parsed as Record<string, unknown>;
  const rawSteps = Array.isArray(obj.steps) ? obj.steps : [];
  const steps: DraftStep[] = [];
  rawSteps.forEach((raw, idx) => {
    const step = parseStep(raw, idx);
    if (step) {
      steps.push(step);
    } else {
      const r = raw as Record<string, unknown> | null;
      const typ = r && typeof r.type === "string" ? r.type : "unknown";
      reasons.push(`Step ${idx + 1} (${typ}) isn't supported in the form view yet`);
    }
  });
  const inputsObj =
    obj.inputs && typeof obj.inputs === "object" && !Array.isArray(obj.inputs)
      ? (obj.inputs as Record<string, unknown>)
      : {};
  const inputs = Object.entries(inputsObj).map(([key, value]) => ({
    key,
    default:
      typeof value === "string"
        ? value
        : value == null
          ? ""
          : JSON.stringify(value),
  }));
  return {
    draft: {
      name: typeof obj.name === "string" ? obj.name : "",
      description: typeof obj.description === "string" ? obj.description : "",
      inputs,
      steps,
    },
    reasons,
  };
}
