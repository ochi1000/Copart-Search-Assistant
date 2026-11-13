import type { OperationAccepted, PublicApiError } from "../chatTypes";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

async function readError(response: Response): Promise<PublicApiError> {
  try {
    const payload = (await response.json()) as PublicApiError;
    return {
      ...payload,
      message: payload.message || "The request could not be completed.",
    };
  } catch {
    if (response.status >= 500) {
      return {
        code: "BACKEND_UNAVAILABLE",
        message:
          "I can’t reach the search service. Make sure the backend is running, then try again.",
        retryable: true,
      };
    }
    return { message: "The request could not be completed." };
  }
}

export async function createMessageOperation(
  message: string,
  sessionId?: string,
): Promise<OperationAccepted> {
  const response = await fetch(`${API_BASE_URL}/api/v1/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      ...(sessionId ? { session_id: sessionId } : {}),
    }),
  });

  if (!response.ok) {
    throw await readError(response);
  }
  return response.json() as Promise<OperationAccepted>;
}

export async function cancelOperation(operationId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/operations/${operationId}/cancel`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw await readError(response);
  }
}

export function operationEventsUrl(operationId: string): string {
  return `${API_BASE_URL}/api/v1/operations/${operationId}/events`;
}
