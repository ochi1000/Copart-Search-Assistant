import type { ChatMessage as Message } from "../chatTypes";
import { VehicleDetails } from "./VehicleDetails";
import { VehicleResults } from "./VehicleResults";
import styles from "./ChatMessage.module.css";

interface ChatMessageProps {
  compact?: boolean;
  message: Message;
  onSend: (message: string) => void;
}

export function ChatMessage({ compact = false, message, onSend }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <article className={`${styles.message} ${isUser ? styles.user : styles.assistant}`}>
      {!isUser && <span className={styles.label}>Copart Search Assistant</span>}
      <div className={styles.text}>{message.text}</div>
      {message.search && (
        <VehicleResults
          compact={compact}
          result={message.search}
          onGetDetails={(lot) => onSend(`Show me the details for lot ${lot}`)}
          onShowMore={() => onSend("Show me more vehicles")}
        />
      )}
      {message.vehicle && <VehicleDetails detail={message.vehicle} />}
    </article>
  );
}
