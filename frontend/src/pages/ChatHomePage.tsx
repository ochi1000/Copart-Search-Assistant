import { useChatSession } from "../features/chat/hooks/useChatSession";
import { ChatComposer } from "../features/chat/components/ChatComposer";
import { ChatConversation } from "../features/chat/components/ChatConversation";
import { EmptyChat } from "../features/chat/components/EmptyChat";
import { BrandLogo } from "../shared/BrandLogo";
import styles from "./ChatHomePage.module.css";

export function ChatHomePage() {
  const chat = useChatSession();
  const hasMessages = chat.messages.length > 0;

  return (
    <main className={`${styles.page} ${hasMessages ? styles.active : ""}`}>
      <header className={styles.header}>
        <BrandLogo />
        <span className={styles.newChatHint}>Refresh to begin a new chat</span>
      </header>

      <section className={styles.workspace}>
        {!hasMessages ? (
          <div className={styles.landing}>
            <EmptyChat onPrompt={chat.sendMessage} />
            <div className={styles.landingComposer}>
              <ChatComposer
                isBusy={chat.isBusy}
                onSend={chat.sendMessage}
                onStop={chat.stop}
              />
            </div>
          </div>
        ) : (
          <>
            <div className={styles.messages}>
              <ChatConversation
                messages={chat.messages}
                status={chat.status}
                onSend={chat.sendMessage}
              />
            </div>
            <div className={styles.dockedComposer}>
              <ChatComposer
                isBusy={chat.isBusy}
                onSend={chat.sendMessage}
                onStop={chat.stop}
              />
              <p>Inventory and auction information may change. Confirm details on Copart.</p>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
