import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  enqueueRun,
  listWorkflows,
  setSecret,
  validateWorkflow,
} from "./client";

describe("api/client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("listWorkflows GETs /api/workflows", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ name: "demo", version: 1 }],
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await listWorkflows();
    expect(result).toEqual([{ name: "demo", version: 1 }]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workflows",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("enqueueRun POSTs with default payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "abc", status: "queued" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await enqueueRun("demo");

    const call = fetchMock.mock.calls[0];
    expect(call[0]).toBe("/api/workflows/demo/run");
    expect(JSON.parse(call[1].body)).toEqual({
      inputs: {},
      dry_run: false,
      trigger_kind: "manual",
    });
  });

  it("setSecret never returns the value", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ name: "K", set: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const out = await setSecret("K", "super-secret");
    expect(out).toEqual({ name: "K", set: true });
    // Belt-and-suspenders — the response object literally has no `value` key.
    expect((out as unknown as Record<string, unknown>).value).toBeUndefined();
  });

  it("validateWorkflow accepts invalid YAML without throwing", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ valid: false, errors: ["bad"], name: null, step_ids: [], references: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const v = await validateWorkflow("garbage");
    expect(v.valid).toBe(false);
    expect(v.errors).toContain("bad");
  });

  it("throws ApiError with detail on non-2xx", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "workflow 'x' not found" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(listWorkflows()).rejects.toBeInstanceOf(ApiError);
    await expect(listWorkflows()).rejects.toMatchObject({
      status: 404,
      detail: "workflow 'x' not found",
    });
  });
});
