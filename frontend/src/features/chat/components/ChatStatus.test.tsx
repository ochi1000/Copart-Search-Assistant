import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatStatus } from "./ChatStatus";

describe("ChatStatus", () => {
  it("embeds an interactive remote browser for verification", () => {
    render(
      <ChatStatus
        status="verification"
        verification={{
          live_url: "https://browser.example/live/session",
          expires_in_seconds: 90,
        }}
      />,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTitle("Copart verification browser")).toHaveAttribute(
      "src",
      "https://browser.example/live/session",
    );
  });
});
