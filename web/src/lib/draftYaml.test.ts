import { describe, expect, it } from "vitest";
import yaml from "js-yaml";

import { draftToYaml, newStep, yamlToDraft, type WorkflowDraft } from "./draftYaml";

function basicDraft(overrides: Partial<WorkflowDraft> = {}): WorkflowDraft {
  return {
    name: "demo",
    description: "test",
    inputs: [{ key: "who", default: "world" }],
    steps: [newStep("shell", "greet")],
    ...overrides,
  };
}

describe("draftYaml", () => {
  it("serializes a basic draft with inputs + a shell step", () => {
    const out = draftToYaml(basicDraft());
    const parsed = yaml.load(out) as Record<string, unknown>;
    expect(parsed.name).toBe("demo");
    expect(parsed.description).toBe("test");
    expect(parsed.inputs).toEqual({ who: "world" });
    const steps = parsed.steps as Array<Record<string, unknown>>;
    expect(steps).toHaveLength(1);
    expect(steps[0].id).toBe("greet");
    expect(steps[0].type).toBe("shell");
    expect((steps[0].config as Record<string, unknown>).command).toBe("echo hello");
  });

  it("omits empty description / inputs from the YAML", () => {
    const draft = basicDraft({ description: "", inputs: [] });
    const out = draftToYaml(draft);
    const parsed = yaml.load(out) as Record<string, unknown>;
    expect(parsed.description).toBeUndefined();
    expect(parsed.inputs).toBeUndefined();
  });

  it("flags destructive + requires_confirmation on steps that opt in", () => {
    const draft = basicDraft({
      steps: [{ ...newStep("write_file", "save") }],
    });
    const out = draftToYaml(draft);
    const parsed = yaml.load(out) as Record<string, unknown>;
    const step = (parsed.steps as Array<Record<string, unknown>>)[0];
    expect(step.destructive).toBe(true);
    expect(step.requires_confirmation).toBe(true);
  });

  it("round-trips: yamlToDraft(draftToYaml(d)) gives back the same shape", () => {
    const draft = basicDraft({
      steps: [
        newStep("shell", "a"),
        newStep("llm", "b"),
        newStep("write_file", "c"),
      ],
    });
    const yamlStr = draftToYaml(draft);
    const { draft: roundtripped, reasons } = yamlToDraft(yamlStr);
    expect(reasons).toEqual([]);
    expect(roundtripped).not.toBeNull();
    expect(roundtripped!.name).toBe("demo");
    expect(roundtripped!.steps.map((s) => s.type)).toEqual([
      "shell",
      "llm",
      "write_file",
    ]);
    expect(roundtripped!.inputs).toEqual([{ key: "who", default: "world" }]);
  });

  it("flags unsupported step types with a reason", () => {
    const yamlStr = `
name: x
steps:
  - id: a
    type: shell
    config:
      command: "echo hi"
  - id: b
    type: branch
    config:
      cases: []
`;
    const { draft, reasons } = yamlToDraft(yamlStr);
    expect(draft?.steps).toHaveLength(1);
    expect(reasons.some((r) => r.includes("branch"))).toBe(true);
  });

  it("preserves non-string input defaults as JSON strings", () => {
    const yamlStr = `
name: x
inputs:
  n: 5
  flag: true
steps:
  - id: a
    type: shell
    config:
      command: "echo"
`;
    const { draft } = yamlToDraft(yamlStr);
    expect(draft).not.toBeNull();
    const lookup = Object.fromEntries(draft!.inputs.map((i) => [i.key, i.default]));
    expect(lookup.n).toBe("5");
    expect(lookup.flag).toBe("true");
  });
});
