import { MessageCircle, X } from "lucide-react";
import { useState } from "react";

import { ChatComposer } from "../features/chat/components/ChatComposer";
import { ChatConversation } from "../features/chat/components/ChatConversation";
import { useChatSession } from "../features/chat/hooks/useChatSession";
import { BrandLogo } from "../shared/BrandLogo";
import styles from "./CopartAssistantWidget.module.css";

export function CopartAssistantWidget() {
  const [open, setOpen] = useState(false);
  const chat = useChatSession();

  return (
    <aside className={styles.widget} aria-label="Copart Search Assistant">
      {open && (
        <section className={styles.panel} aria-label="Assistant conversation">
          <header>
            <BrandLogo compact />
            <button type="button" onClick={() => setOpen(false)} aria-label="Close assistant">
              <X size={19} />
            </button>
          </header>

          <div className={styles.body}>
            {chat.messages.length === 0 ? (
              <div className={styles.welcome}>
                <span>Vehicle search, wherever you need it</span>
                <h2>How can I help?</h2>
                <p>
                  Tell me what you’re looking for, or ask me to refine a previous search.
                </p>
                <button
                  type="button"
                  onClick={() => chat.sendMessage("Find Toyota Camrys from 2022")}
                >
                  Find 2022 Toyota Camrys
                </button>
              </div>
            ) : (
              <ChatConversation
                compact
                messages={chat.messages}
                status={chat.status}
                verification={chat.verification}
                onSend={chat.sendMessage}
              />
            )}
          </div>

          <footer>
            <ChatComposer
              compact
              isBusy={chat.isBusy}
              onSend={chat.sendMessage}
              onStop={chat.stop}
            />
          </footer>
        </section>
      )}

      <button
        className={styles.launcher}
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-label={open ? "Close Copart assistant" : "Open Copart assistant"}
      >
        {open ? <X size={22} /> : <MessageCircle size={23} />}
        {!open && <span>Ask Copart Assistant</span>}
      </button>
    </aside>
  );
}
