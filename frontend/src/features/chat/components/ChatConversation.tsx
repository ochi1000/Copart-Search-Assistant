import { useEffect, useRef } from "react";

import type {
  ChatMessage as Message,
  ChatStatus,
  VerificationRequired,
} from "../chatTypes";
import { ChatMessage } from "./ChatMessage";
import { ChatStatus as Status } from "./ChatStatus";
import styles from "./ChatConversation.module.css";

interface ChatConversationProps {
  compact?: boolean;
  messages: Message[];
  status: ChatStatus;
  verification?: VerificationRequired;
  onSend: (message: string) => void;
}

export function ChatConversation({
  compact = false,
  messages,
  status,
  verification,
  onSend,
}: ChatConversationProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, status]);

  return (
    <div className={`${styles.conversation} ${compact ? styles.compact : ""}`}>
      {messages.map((message) => (
        <ChatMessage
          compact={compact}
          key={message.id}
          message={message}
          onSend={onSend}
        />
      ))}
      {status !== "idle" && (
        <Status status={status} verification={verification} />
      )}
      <div ref={endRef} />
    </div>
  );
}
