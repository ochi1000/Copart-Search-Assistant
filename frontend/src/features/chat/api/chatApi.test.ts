import { afterEach, describe, expect, it, vi } from "vitest";

import { createMessageOperation } from "./chatApi";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("chatApi", () => {
  it("reports a useful message when the backend proxy is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("Proxy connection failed", {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        }),
      ),
    );

    await expect(createMessageOperation("Find a hybrid")).rejects.toMatchObject({
      code: "BACKEND_UNAVAILABLE",
      message: expect.stringContaining("backend is running"),
    });
  });
});
