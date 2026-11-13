import type { ChatStatus as Status } from "../chatTypes";
import type { VerificationRequired } from "../chatTypes";
import styles from "./ChatStatus.module.css";

const statusText: Record<Exclude<Status, "idle">, string> = {
  thinking: "Understanding what you're looking for",
  searching: "Searching Copart inventory",
  verification: "Complete the verification in the Chrome window",
  cancelling: "Stopping the request",
};

interface ChatStatusProps {
  status: Exclude<Status, "idle">;
  verification?: VerificationRequired;
}

export function ChatStatus({ status, verification }: ChatStatusProps) {
  const hasRemoteBrowser = status === "verification" && verification?.live_url;

  return (
    <>
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
        <span>
          {hasRemoteBrowser
            ? "Complete the verification below"
            : statusText[status]}
        </span>
        {status === "verification" && (
          <small>The search will resume automatically when you finish.</small>
        )}
      </div>

      {hasRemoteBrowser && (
        <div className={styles.overlay} role="dialog" aria-modal="true">
          <section className={styles.browserPanel}>
            <header>
              <div>
                <strong>Copart verification</strong>
                <span>Complete the prompt to continue your search.</span>
              </div>
              {verification?.expires_in_seconds && (
                <small>
                  This secure browser session expires in about{" "}
                  {verification.expires_in_seconds} seconds.
                </small>
              )}
            </header>
            <iframe
              src={verification?.live_url}
              title="Copart verification browser"
              sandbox="allow-same-origin allow-scripts"
              allow="clipboard-read; clipboard-write"
            />
          </section>
        </div>
      )}
    </>
  );
}
