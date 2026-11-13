import type { ChatStatus as Status } from "../chatTypes";
import styles from "./ChatStatus.module.css";

const statusText: Record<Exclude<Status, "idle">, string> = {
  thinking: "Understanding what you’re looking for",
  searching: "Searching Copart inventory",
  verification: "Complete the verification in the Chrome window",
  cancelling: "Stopping the request",
};

export function ChatStatus({ status }: { status: Exclude<Status, "idle"> }) {
  return (
    <div
      className={`${styles.status} ${status === "verification" ? styles.verification : ""}`}
      role="status"
      aria-live="polite"
    >
      <span className={styles.dots} aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span>{statusText[status]}</span>
      {status === "verification" && (
        <small>The search will resume automatically when you finish.</small>
      )}
    </div>
  );
}
