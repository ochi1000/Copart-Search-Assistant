import { describe, expect, it } from "vitest";

import { chatReducer, initialChatState } from "./chatReducer";

describe("chatReducer", () => {
  it("stores the generated session only in the current chat state", () => {
    const state = chatReducer(initialChatState, {
      type: "operation_started",
      operationId: "operation-1",
      sessionId: "session-1",
    });

    expect(state.sessionId).toBe("session-1");
    expect(state.operationId).toBe("operation-1");
  });

  it("adds completed search data to one assistant message", () => {
    const state = chatReducer(initialChatState, {
      type: "completed",
      result: {
        message: "I found one vehicle.",
        search: {
          vehicles: [
            {
              title: "2024 Toyota Camry",
              lot_number: "12345678",
              image_url: "https://example.test/camry.jpg",
            },
          ],
        },
      },
    });

    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].text).toBe("I found one vehicle.");
    expect(state.messages[0].search?.vehicles[0].image_url).toContain("camry.jpg");
  });
});
