// Form-based step builder. Each step type renders as a typed card so
// users never have to write YAML for the common case. The parent owns
// the YAML string; this component edits a `WorkflowDraft` model and
// notifies on every change with the regenerated YAML.

import { useEffect, useMemo, useState } from "react";

import {
  type DraftStep,
  type HttpStep,
  type ImageStep,
  type LLMStep,
  type PythonStep,
  type ReadFileStep,
  type ShellStep,
  type StepKind,
  type WorkflowDraft,
  type WriteFileStep,
  STEP_KINDS,
  draftToYaml,
  newStep,
  yamlToDraft,
} from "../../lib/draftYaml";

interface Props {
  yamlText: string;
  onYamlChange: (yaml: string) => void;
  /** Notifies the parent when the YAML can't round-trip through the form. */
  onUnsupportedReasons?: (reasons: string[]) => void;
}

export default function FormView({ yamlText, onYamlChange, onUnsupportedReasons }: Props) {
  // Parse once when the parent's yaml text changes from outside (template
  // pick, initial load). When the user edits within the form, we drive
  // changes via setDraft and serialize back to YAML — we don't re-parse
  // on every keystroke.
  const initial = useMemo(() => yamlToDraft(yamlText), [yamlText]);
  const [draft, setDraft] = useState<WorkflowDraft>(
    initial.draft ?? { name: "my_workflow", description: "", inputs: [], steps: [] },
  );
  // Track the YAML the parent last gave us so we know when to re-sync.
  const [seedYaml, setSeedYaml] = useState(yamlText);

  useEffect(() => {
    if (yamlText !== seedYaml) {
      const parsed = yamlToDraft(yamlText);
      if (parsed.draft) {
        setDraft(parsed.draft);
        onUnsupportedReasons?.(parsed.reasons);
      } else {
        onUnsupportedReasons?.(parsed.reasons);
      }
      setSeedYaml(yamlText);
    }
  }, [yamlText, seedYaml, onUnsupportedReasons]);

  useEffect(() => {
    onUnsupportedReasons?.(initial.reasons);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function update(next: WorkflowDraft) {
    setDraft(next);
    const yaml = draftToYaml(next);
    setSeedYaml(yaml);
    onYamlChange(yaml);
  }

  function patch(p: Partial<WorkflowDraft>) {
    update({ ...draft, ...p });
  }

  function updateStep(idx: number, next: DraftStep) {
    const steps = [...draft.steps];
    steps[idx] = next;
    update({ ...draft, steps });
  }

  function removeStep(idx: number) {
    update({ ...draft, steps: draft.steps.filter((_, i) => i !== idx) });
  }

  function moveStep(idx: number, dir: -1 | 1) {
    const j = idx + dir;
    if (j < 0 || j >= draft.steps.length) return;
    const steps = [...draft.steps];
    [steps[idx], steps[j]] = [steps[j], steps[idx]];
    update({ ...draft, steps });
  }

  function addStep(kind: StepKind) {
    const id = nextStepId(kind, draft.steps);
    update({ ...draft, steps: [...draft.steps, newStep(kind, id)] });
  }

  return (
    <div className="space-y-5">
      {/* Top-level meta */}
      <section className="rounded-lg border border-ink/10 p-4 space-y-3">
        <FieldLabel label="Name">
          <input
            value={draft.name}
            onChange={(e) => patch({ name: e.target.value })}
            placeholder="my_workflow"
            className="w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm font-mono"
          />
        </FieldLabel>
        <FieldLabel label="Description">
          <input
            value={draft.description}
            onChange={(e) => patch({ description: e.target.value })}
            placeholder="What this workflow does"
            className="w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm"
          />
        </FieldLabel>
        <InputsEditor
          inputs={draft.inputs}
          onChange={(inputs) => patch({ inputs })}
        />
      </section>

      {/* Steps */}
      <section className="space-y-3">
        <h2 className="text-xs uppercase tracking-wider text-ink/50">Steps</h2>
        {draft.steps.length === 0 && (
          <p className="text-sm text-ink/50 italic">
            No steps yet. Pick a type below to add one.
          </p>
        )}
        {draft.steps.map((step, idx) => (
          <StepCard
            key={`${step.id}-${idx}`}
            step={step}
            index={idx}
            total={draft.steps.length}
            onChange={(s) => updateStep(idx, s)}
            onRemove={() => removeStep(idx)}
            onMove={(dir) => moveStep(idx, dir)}
          />
        ))}
        <AddStep onAdd={addStep} />
      </section>
    </div>
  );
}

function nextStepId(kind: StepKind, steps: DraftStep[]): string {
  const taken = new Set(steps.map((s) => s.id));
  const base = kind === "python_step" ? "py" : kind;
  if (!taken.has(base)) return base;
  for (let i = 2; i < 1000; i++) {
    const candidate = `${base}_${i}`;
    if (!taken.has(candidate)) return candidate;
  }
  return `${base}_${Date.now()}`;
}

// --------------------------- shared field helpers ---------------------------

function FieldLabel({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <div className="text-[10px] uppercase tracking-wider text-ink/50">
        {label}
      </div>
      {children}
      {hint && <div className="text-[11px] text-ink/40">{hint}</div>}
    </label>
  );
}

function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      rows={4}
      {...props}
      className={
        "w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm font-mono " +
        (props.className ?? "")
      }
    />
  );
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="text"
      {...props}
      className={
        "w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm " +
        (props.className ?? "")
      }
    />
  );
}

// --------------------------- inputs editor ---------------------------

function InputsEditor({
  inputs,
  onChange,
}: {
  inputs: WorkflowDraft["inputs"];
  onChange: (inputs: WorkflowDraft["inputs"]) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-ink/50">
        Inputs
      </div>
      {inputs.length === 0 && (
        <p className="text-xs text-ink/40">
          No inputs. Add one for a value the user (or chat) can override at run
          time.
        </p>
      )}
      {inputs.map((row, idx) => (
        <div key={idx} className="grid grid-cols-[1fr_1fr_auto] gap-2">
          <TextInput
            value={row.key}
            placeholder="name"
            onChange={(e) => {
              const next = [...inputs];
              next[idx] = { ...row, key: e.target.value };
              onChange(next);
            }}
            className="font-mono"
          />
          <TextInput
            value={row.default}
            placeholder="default value"
            onChange={(e) => {
              const next = [...inputs];
              next[idx] = { ...row, default: e.target.value };
              onChange(next);
            }}
          />
          <button
            type="button"
            onClick={() => onChange(inputs.filter((_, i) => i !== idx))}
            className="text-ink/40 hover:text-red-600 text-sm px-2"
            aria-label="Remove input"
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...inputs, { key: "", default: "" }])}
        className="text-xs text-terracotta hover:underline"
      >
        + Add input
      </button>
    </div>
  );
}

// --------------------------- step card ---------------------------

const KIND_LABEL: Record<StepKind, string> = {
  shell: "Shell",
  http: "HTTP",
  llm: "LLM",
  image: "Image",
  read_file: "Read file",
  write_file: "Write file",
  python_step: "Python",
};

function StepCard({
  step,
  index,
  total,
  onChange,
  onRemove,
  onMove,
}: {
  step: DraftStep;
  index: number;
  total: number;
  onChange: (s: DraftStep) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
}) {
  return (
    <div className="rounded-lg border border-ink/10 bg-white/30">
      <header className="flex items-center justify-between px-4 py-2 border-b border-ink/5 bg-ink/[0.02]">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-ink/40 w-5">{index + 1}.</span>
          <span className="text-xs uppercase tracking-wider text-terracotta font-medium">
            {KIND_LABEL[step.type]}
          </span>
          <input
            value={step.id}
            onChange={(e) => onChange({ ...step, id: e.target.value })}
            className="font-mono text-xs rounded border border-ink/15 px-2 py-0.5 bg-white/60"
            aria-label="Step id"
          />
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled={index === 0}
            onClick={() => onMove(-1)}
            className="text-xs text-ink/40 hover:text-ink px-1 disabled:opacity-30"
            aria-label="Move up"
            title="Move up"
          >
            ↑
          </button>
          <button
            type="button"
            disabled={index === total - 1}
            onClick={() => onMove(1)}
            className="text-xs text-ink/40 hover:text-ink px-1 disabled:opacity-30"
            aria-label="Move down"
            title="Move down"
          >
            ↓
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="text-xs text-ink/40 hover:text-red-600 px-1"
            aria-label="Remove step"
            title="Remove step"
          >
            ×
          </button>
        </div>
      </header>
      <div className="px-4 py-3 space-y-3">
        <StepFields step={step} onChange={onChange} />
        <DestructiveToggle step={step} onChange={onChange} />
      </div>
    </div>
  );
}

function DestructiveToggle({
  step,
  onChange,
}: {
  step: DraftStep;
  onChange: (s: DraftStep) => void;
}) {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-ink/60 pt-1">
      <label className="inline-flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={step.destructive === true}
          onChange={(e) => onChange({ ...step, destructive: e.target.checked })}
        />
        destructive
      </label>
      <label className="inline-flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={step.requires_confirmation === true}
          onChange={(e) =>
            onChange({ ...step, requires_confirmation: e.target.checked })
          }
        />
        require confirmation (pause for approval)
      </label>
    </div>
  );
}

function StepFields({
  step,
  onChange,
}: {
  step: DraftStep;
  onChange: (s: DraftStep) => void;
}) {
  switch (step.type) {
    case "shell":
      return <ShellFields step={step} onChange={onChange} />;
    case "python_step":
      return <PythonFields step={step} onChange={onChange} />;
    case "http":
      return <HttpFields step={step} onChange={onChange} />;
    case "read_file":
      return <ReadFileFields step={step} onChange={onChange} />;
    case "write_file":
      return <WriteFileFields step={step} onChange={onChange} />;
    case "llm":
      return <LlmFields step={step} onChange={onChange} />;
    case "image":
      return <ImageFields step={step} onChange={onChange} />;
  }
}

function ShellFields({ step, onChange }: { step: ShellStep; onChange: (s: ShellStep) => void }) {
  return (
    <FieldLabel label="Command" hint="Use ${inputs.X} to reference a workflow input.">
      <TextArea
        value={step.command}
        rows={2}
        onChange={(e) => onChange({ ...step, command: e.target.value })}
        placeholder='echo "hello ${inputs.who}"'
      />
    </FieldLabel>
  );
}

function PythonFields({ step, onChange }: { step: PythonStep; onChange: (s: PythonStep) => void }) {
  return (
    <FieldLabel
      label="Python code"
      hint="Set `output = {...}` for a dict, or `output = value` for a plain value. `steps` is available."
    >
      <TextArea
        value={step.code}
        rows={6}
        onChange={(e) => onChange({ ...step, code: e.target.value })}
      />
    </FieldLabel>
  );
}

function HttpFields({ step, onChange }: { step: HttpStep; onChange: (s: HttpStep) => void }) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3">
      <FieldLabel label="Method">
        <select
          value={step.method}
          onChange={(e) =>
            onChange({ ...step, method: e.target.value as HttpStep["method"] })
          }
          className="w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm"
        >
          {["GET", "POST", "PUT", "DELETE", "PATCH"].map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </FieldLabel>
      <FieldLabel label="URL">
        <TextInput
          value={step.url}
          onChange={(e) => onChange({ ...step, url: e.target.value })}
          placeholder="https://example.com/api"
          className="font-mono"
        />
      </FieldLabel>
      <div className="col-span-2">
        <FieldLabel label="Body (optional)">
          <TextArea
            value={step.body}
            onChange={(e) => onChange({ ...step, body: e.target.value })}
            placeholder='{"key": "value"}'
          />
        </FieldLabel>
      </div>
    </div>
  );
}

function ReadFileFields({
  step,
  onChange,
}: {
  step: ReadFileStep;
  onChange: (s: ReadFileStep) => void;
}) {
  return (
    <FieldLabel label="Path">
      <TextInput
        value={step.path}
        onChange={(e) => onChange({ ...step, path: e.target.value })}
        placeholder="/tmp/in.txt"
        className="font-mono"
      />
    </FieldLabel>
  );
}

function WriteFileFields({
  step,
  onChange,
}: {
  step: WriteFileStep;
  onChange: (s: WriteFileStep) => void;
}) {
  return (
    <div className="space-y-3">
      <FieldLabel label="Path">
        <TextInput
          value={step.path}
          onChange={(e) => onChange({ ...step, path: e.target.value })}
          placeholder="/tmp/out.txt"
          className="font-mono"
        />
      </FieldLabel>
      <FieldLabel label="Content">
        <TextArea
          value={step.content}
          rows={4}
          onChange={(e) => onChange({ ...step, content: e.target.value })}
          placeholder="Hello ${inputs.who}"
        />
      </FieldLabel>
    </div>
  );
}

function LlmFields({ step, onChange }: { step: LLMStep; onChange: (s: LLMStep) => void }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <FieldLabel label="Provider">
        <select
          value={step.provider}
          onChange={(e) => onChange({ ...step, provider: e.target.value })}
          className="w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm"
        >
          {["", "anthropic", "openai", "ollama", "mock"].map((p) => (
            <option key={p} value={p}>
              {p || "(workflow default)"}
            </option>
          ))}
        </select>
      </FieldLabel>
      <FieldLabel label="Model (optional)">
        <TextInput
          value={step.model}
          onChange={(e) => onChange({ ...step, model: e.target.value })}
          placeholder="leave blank for provider default"
          className="font-mono"
        />
      </FieldLabel>
      <div className="col-span-2">
        <FieldLabel label="System prompt (optional)">
          <TextArea
            value={step.system}
            rows={2}
            onChange={(e) => onChange({ ...step, system: e.target.value })}
            placeholder="You are a concise summarizer."
          />
        </FieldLabel>
      </div>
      <div className="col-span-2">
        <FieldLabel label="Prompt">
          <TextArea
            value={step.prompt}
            rows={5}
            onChange={(e) => onChange({ ...step, prompt: e.target.value })}
            placeholder="Summarize the following in 5 bullets:\n\n${steps.read.output.content}"
          />
        </FieldLabel>
      </div>
    </div>
  );
}

function ImageFields({ step, onChange }: { step: ImageStep; onChange: (s: ImageStep) => void }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <FieldLabel label="Provider">
        <select
          value={step.provider}
          onChange={(e) => onChange({ ...step, provider: e.target.value })}
          className="w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm"
        >
          {["", "openai", "gemini"].map((p) => (
            <option key={p} value={p}>
              {p || "(workflow default)"}
            </option>
          ))}
        </select>
      </FieldLabel>
      <FieldLabel label="Size">
        <TextInput
          value={step.size}
          onChange={(e) => onChange({ ...step, size: e.target.value })}
          placeholder="1024x1024"
          className="font-mono"
        />
      </FieldLabel>
      <div className="col-span-2">
        <FieldLabel label="Prompt">
          <TextArea
            value={step.prompt}
            rows={3}
            onChange={(e) => onChange({ ...step, prompt: e.target.value })}
          />
        </FieldLabel>
      </div>
      <div className="col-span-2">
        <FieldLabel label="Save to">
          <TextInput
            value={step.save_to}
            onChange={(e) => onChange({ ...step, save_to: e.target.value })}
            placeholder="/tmp/hollerbox-image.png"
            className="font-mono"
          />
        </FieldLabel>
      </div>
    </div>
  );
}

// --------------------------- add step ---------------------------

function AddStep({ onAdd }: { onAdd: (kind: StepKind) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-dashed border-ink/15 p-3">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="w-full text-sm text-terracotta hover:underline"
        >
          + Add step
        </button>
      ) : (
        <div className="space-y-2">
          <div className="text-[10px] uppercase tracking-wider text-ink/50">
            Pick a step type
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {STEP_KINDS.map((k) => (
              <button
                key={k.kind}
                type="button"
                onClick={() => {
                  onAdd(k.kind);
                  setOpen(false);
                }}
                className="text-left rounded-md border border-ink/10 hover:border-terracotta/50 hover:bg-terracotta/5 px-3 py-2"
              >
                <div className="text-sm font-medium">{k.label}</div>
                <div className="text-[11px] text-ink/50 mt-0.5">{k.hint}</div>
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="text-xs text-ink/40 hover:text-ink"
          >
            cancel
          </button>
        </div>
      )}
    </div>
  );
}
