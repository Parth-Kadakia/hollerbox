import Editor from "@monaco-editor/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getWorkflow,
  upsertWorkflow,
  validateWorkflow,
} from "../api/client";
import type { WorkflowValidateResponse } from "../api/types";
import { ErrorBox } from "./Dashboard";

const STARTER_YAML = `name: my_workflow
version: 1
description: A new workflow.
inputs:
  who: world
steps:
  - id: greet
    type: shell
    config:
      command: "echo Hello, \${inputs.who}!"
`;

export default function EditorPage() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const isNew = !name;

  const [yamlText, setYamlText] = useState<string>(STARTER_YAML);
  const [loading, setLoading] = useState<boolean>(!isNew);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [validation, setValidation] = useState<WorkflowValidateResponse | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load existing workflow once.
  useEffect(() => {
    if (isNew) return;
    getWorkflow(name!)
      .then((wf) => setYamlText(wf.yaml_source))
      .catch((e: unknown) =>
        setLoadError(e instanceof Error ? e.message : String(e)),
      )
      .finally(() => setLoading(false));
  }, [name, isNew]);

  // Debounced live validation as the user types.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      validateWorkflow(yamlText)
        .then(setValidation)
        .catch(() => setValidation(null));
    }, 350);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [yamlText]);

  const targetName = useMemo(() => {
    if (!isNew) return name!;
    return validation?.name ?? "untitled";
  }, [isNew, name, validation?.name]);

  async function save() {
    if (!validation?.valid) return;
    setSaving(true);
    setSaveError(null);
    try {
      await upsertWorkflow(targetName, yamlText);
      navigate("/workflows");
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {isNew ? "New workflow" : `Edit ${name}`}
          </h1>
          <p className="text-sm text-ink/60 mt-1">
            YAML lives on disk. Saving upserts the workflow row in the API DB.
          </p>
        </div>
        <button
          disabled={saving || !validation?.valid}
          onClick={save}
          className="rounded-md bg-terracotta px-3 py-1.5 text-sm font-medium text-white hover:bg-terracotta/90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? "Saving…" : isNew ? `Create ${targetName}` : "Save"}
        </button>
      </header>

      {loadError && <ErrorBox error={loadError} />}
      {saveError && <ErrorBox error={saveError} />}

      <div className="grid grid-cols-[1fr_280px] gap-5">
        <div className="rounded-lg border border-ink/10 overflow-hidden">
          {loading ? (
            <div className="p-6 text-sm text-ink/50">loading workflow…</div>
          ) : (
            <Editor
              height="520px"
              defaultLanguage="yaml"
              value={yamlText}
              onChange={(v) => setYamlText(v ?? "")}
              theme="vs"
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                tabSize: 2,
                scrollBeyondLastLine: false,
                automaticLayout: true,
              }}
            />
          )}
        </div>

        <aside className="space-y-4 text-sm">
          <ValidationPanel v={validation} />
          {validation?.valid && (
            <ReferencesPanel refs={validation.references} />
          )}
          {validation?.valid && validation.step_ids.length > 0 && (
            <StepsPanel ids={validation.step_ids} />
          )}
        </aside>
      </div>
    </div>
  );
}

function ValidationPanel({ v }: { v: WorkflowValidateResponse | null }) {
  if (v === null) {
    return (
      <Card title="Validation">
        <p className="text-xs text-ink/50">typing…</p>
      </Card>
    );
  }
  if (v.valid) {
    return (
      <Card title="Validation">
        <p className="text-xs text-emerald-700">
          ✓ valid · {v.step_ids.length} step
          {v.step_ids.length !== 1 ? "s" : ""}
        </p>
      </Card>
    );
  }
  return (
    <Card title="Validation">
      <ul className="space-y-1 text-xs text-red-700">
        {v.errors.map((e, i) => (
          <li key={i} className="break-words">
            • {e}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ReferencesPanel({ refs }: { refs: string[] }) {
  if (refs.length === 0) {
    return (
      <Card title="References">
        <p className="text-xs text-ink/40">none</p>
      </Card>
    );
  }
  return (
    <Card title="References">
      <ul className="text-xs font-mono space-y-0.5 text-ink/70">
        {refs.map((r) => (
          <li key={r}>${"{"}{r}{"}"}</li>
        ))}
      </ul>
    </Card>
  );
}

function StepsPanel({ ids }: { ids: string[] }) {
  return (
    <Card title="Steps">
      <ol className="text-xs font-mono space-y-0.5 text-ink/70">
        {ids.map((id, i) => (
          <li key={id}>
            {i + 1}. {id}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-ink/10 p-3">
      <div className="text-[10px] uppercase tracking-wider text-ink/50 mb-2">
        {title}
      </div>
      {children}
    </section>
  );
}
