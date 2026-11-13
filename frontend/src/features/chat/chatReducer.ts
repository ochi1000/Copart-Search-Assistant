import type {
  ChatMessage,
  ChatStatus,
  CompletedResult,
} from "./chatTypes";

export interface ChatState {
  messages: ChatMessage[];
  status: ChatStatus;
  sessionId?: string;
  operationId?: string;
  error?: string;
}

export type ChatAction =
  | { type: "user_message"; message: ChatMessage }
  | { type: "operation_started"; operationId: string; sessionId: string }
  | { type: "status_changed"; status: ChatStatus }
  | { type: "completed"; result: CompletedResult }
  | { type: "failed"; message: string }
  | { type: "cancelled" };

export const initialChatState: ChatState = {
  messages: [],
  status: "idle",
};

function assistantMessage(
  text: string,
  extras: Partial<Pick<ChatMessage, "search" | "vehicle">> = {},
): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    text,
    ...extras,
  };
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "user_message":
      return {
        ...state,
        messages: [...state.messages, action.message],
        error: undefined,
      };
    case "operation_started":
      return {
        ...state,
        operationId: action.operationId,
        sessionId: action.sessionId,
      };
    case "status_changed":
      return { ...state, status: action.status };
    case "completed":
      return {
        ...state,
        status: "idle",
        operationId: undefined,
        messages: [
          ...state.messages,
          assistantMessage(action.result.message, {
            search: action.result.search,
            vehicle: action.result.vehicle,
          }),
        ],
      };
    case "failed":
      return {
        ...state,
        status: "idle",
        operationId: undefined,
        error: action.message,
        messages: [...state.messages, assistantMessage(action.message)],
      };
    case "cancelled":
      return {
        ...state,
        status: "idle",
        operationId: undefined,
        messages: [
          ...state.messages,
          assistantMessage("I stopped that request. You can adjust it and try again."),
        ],
      };
    default:
      return state;
  }
}
