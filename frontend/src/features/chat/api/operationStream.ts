import { operationEventsUrl } from "./chatApi";
import type {
  CompletedResult,
  OperationEvent,
  PublicApiError,
  VerificationRequired,
} from "../chatTypes";

interface StreamHandlers {
  onThinking: () => void;
  onSearchStarted: () => void;
  onVerificationRequired: (verification: VerificationRequired) => void;
  onVerificationCompleted: () => void;
  onCompleted: (result: CompletedResult) => void;
  onFailed: (error: PublicApiError) => void;
  onCancelled: () => void;
}

function payload<T>(event: MessageEvent<string>): OperationEvent<T> {
  return JSON.parse(event.data) as OperationEvent<T>;
}

export function openOperationStream(
  operationId: string,
  handlers: StreamHandlers,
): () => void {
  const stream = new EventSource(operationEventsUrl(operationId));

  stream.addEventListener("thinking", handlers.onThinking);
  stream.addEventListener("search_started", handlers.onSearchStarted);
  stream.addEventListener("verification_required", (event) => {
    const verification = payload<VerificationRequired>(
      event as MessageEvent<string>,
    );
    handlers.onVerificationRequired(verification.data);
  });
  stream.addEventListener(
    "verification_completed",
    handlers.onVerificationCompleted,
  );
  stream.addEventListener("completed", (event) => {
    const completed = payload<{ result: CompletedResult }>(
      event as MessageEvent<string>,
    );
    handlers.onCompleted(completed.data.result);
    stream.close();
  });
  stream.addEventListener("failed", (event) => {
    const failed = payload<PublicApiError>(event as MessageEvent<string>);
    handlers.onFailed(failed.data);
    stream.close();
  });
  stream.addEventListener("cancelled", () => {
    handlers.onCancelled();
    stream.close();
  });

  return () => stream.close();
}
