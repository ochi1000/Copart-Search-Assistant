import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("App", () => {
  it("shows the branded home chat and opens the compact assistant", () => {
    render(<App />);

    expect(screen.getAllByAltText("Copart").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { name: "What vehicle are you looking for?" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open Copart assistant" }));
    expect(screen.getByRole("heading", { name: "How can I help?" })).toBeInTheDocument();
  });
});
