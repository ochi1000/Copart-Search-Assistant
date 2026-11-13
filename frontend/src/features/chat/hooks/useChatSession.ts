import { useCallback, useEffect, useReducer, useRef } from "react";

import { cancelOperation, createMessageOperation } from "../api/chatApi";
import { openOperationStream } from "../api/operationStream";
import { chatReducer, initialChatState } from "../chatReducer";
import type { PublicApiError } from "../chatTypes";

function errorMessage(error: unknown): string {
  if (error instanceof TypeError) {
    return "I can’t reach the search service. Make sure the backend is running, then try again.";
  }
  if (typeof error === "object" && error && "message" in error) {
    return String((error as PublicApiError).message);
  }
  return "I couldn’t complete that request. Please try again.";
}

export function useChatSession() {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const closeStream = useRef<(() => void) | undefined>();

  useEffect(() => () => closeStream.current?.(), []);

  const sendMessage = useCallback(
    async (value: string) => {
      const message = value.trim();
      if (!message || state.status !== "idle") return;

      dispatch({
        type: "user_message",
        message: {
          id: crypto.randomUUID(),
          role: "user",
          text: message,
        },
      });
      dispatch({ type: "status_changed", status: "thinking" });

      try {
        const operation = await createMessageOperation(message, state.sessionId);
        dispatch({
          type: "operation_started",
          operationId: operation.operation_id,
          sessionId: operation.session_id,
        });
        closeStream.current = openOperationStream(operation.operation_id, {
          onThinking: () =>
            dispatch({ type: "status_changed", status: "thinking" }),
          onSearchStarted: () =>
            dispatch({ type: "status_changed", status: "searching" }),
          onVerificationRequired: (verification) =>
            dispatch({ type: "verification_required", verification }),
          onVerificationCompleted: () =>
            dispatch({ type: "verification_completed" }),
          onCompleted: (result) => dispatch({ type: "completed", result }),
          onFailed: (error) =>
            dispatch({ type: "failed", message: error.message }),
          onCancelled: () => dispatch({ type: "cancelled" }),
        });
      } catch (error) {
        dispatch({ type: "failed", message: errorMessage(error) });
      }
    },
    [state.sessionId, state.status],
  );

  const stop = useCallback(async () => {
    if (!state.operationId || state.status === "idle") return;
    dispatch({ type: "status_changed", status: "cancelling" });
    try {
      await cancelOperation(state.operationId);
    } catch (error) {
      dispatch({ type: "failed", message: errorMessage(error) });
    }
  }, [state.operationId, state.status]);

  return {
    ...state,
    isBusy: state.status !== "idle",
    sendMessage,
    stop,
  };
}
