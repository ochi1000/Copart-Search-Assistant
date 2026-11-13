import { FormEvent, KeyboardEvent, useState } from "react";
import { ArrowUp, Square } from "lucide-react";

import styles from "./ChatComposer.module.css";

interface ChatComposerProps {
  compact?: boolean;
  isBusy: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
}

export function ChatComposer({
  compact = false,
  isBusy,
  onSend,
  onStop,
}: ChatComposerProps) {
  const [value, setValue] = useState("");

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const message = value.trim();
    if (!message || isBusy) return;
    onSend(message);
    setValue("");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      className={`${styles.composer} ${compact ? styles.compact : ""}`}
      onSubmit={submit}
    >
      <textarea
        aria-label="Message the Copart Search Assistant"
        placeholder={
          compact
            ? "What vehicle can I help you find?"
            : "Describe the vehicle you’re looking for…"
        }
        rows={compact ? 2 : 1}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isBusy}
      />
      {isBusy ? (
        <button
          className={styles.stopButton}
          type="button"
          onClick={onStop}
          aria-label="Stop response"
        >
          <Square size={15} fill="currentColor" />
        </button>
      ) : (
        <button
          className={styles.sendButton}
          type="submit"
          disabled={!value.trim()}
          aria-label="Send message"
        >
          <ArrowUp size={19} strokeWidth={2.4} />
        </button>
      )}
    </form>
  );
}
