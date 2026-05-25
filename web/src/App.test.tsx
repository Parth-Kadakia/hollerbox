import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

// Pages issue fetches on mount; in jsdom there is no global fetch unless
// we provide one. A blanket stub keeps these smoke renders deterministic.
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    }),
  );
  // Same for EventSource (used by RunDetail SSE).
  vi.stubGlobal(
    "EventSource",
    vi.fn().mockImplementation(() => ({
      close: vi.fn(),
      addEventListener: vi.fn(),
    })),
  );
});

describe("App shell", () => {
  it("renders the brand and sidebar navigation", async () => {
    render(<App />);
    // findBy* waits for the Dashboard's effect to settle before asserting,
    // which keeps React from logging an act() warning.
    expect(
      await screen.findByRole("link", { name: /dashboard/i }),
    ).toBeInTheDocument();
    // Dashboard also links "Workflows" / "Runs" inline, so getAllByRole.
    expect(screen.getAllByRole("link", { name: /workflows/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /runs/i }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /settings/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /chat/i })).toBeInTheDocument();
  });

  it("shows the version + brand strapline", async () => {
    render(<App />);
    expect(await screen.findByText(/v0\.0\.1/i)).toBeInTheDocument();
    expect(
      screen.getByText(/open source · runs on your machine/i),
    ).toBeInTheDocument();
  });

  it("lands on Dashboard at /", async () => {
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: /^dashboard$/i, level: 1 }),
    ).toBeInTheDocument();
  });
});
