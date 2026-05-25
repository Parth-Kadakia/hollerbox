import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("App", () => {
  it("renders the HollerBox brand name", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: /hollerbox/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("renders the logo with the right alt text", () => {
    render(<App />);
    const logo = screen.getByAltText("HollerBox") as HTMLImageElement;
    expect(logo).toBeInTheDocument();
    expect(logo.getAttribute("src")).toBe("/logo.png");
  });

  it("shows the version + open-source tagline", () => {
    render(<App />);
    expect(screen.getByText(/open source/i)).toBeInTheDocument();
    expect(screen.getByText(/v0\.0\.1/i)).toBeInTheDocument();
  });
});
