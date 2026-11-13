import { CarFront, MapPinned, Sparkles } from "lucide-react";

import { BrandLogo } from "../../../shared/BrandLogo";
import styles from "./EmptyChat.module.css";

const prompts = [
  {
    icon: CarFront,
    label: "Find 2022 or newer Toyota Camrys in Texas",
  },
  {
    icon: MapPinned,
    label: "Show clean-title SUVs near Dallas under 100k miles",
  },
  {
    icon: Sparkles,
    label: "Find hybrid vehicles with Buy It Now options",
  },
];

export function EmptyChat({ onPrompt }: { onPrompt: (prompt: string) => void }) {
  return (
    <section className={styles.empty}>
      <BrandLogo />
      <div className={styles.intro}>
        <p className={styles.eyebrow}>A simpler way to search inventory</p>
        <h1>What vehicle are you looking for?</h1>
        <p>
          Tell me what matters to you. I can search, refine results, show more
          listings, and pull details for a specific lot.
        </p>
      </div>
      <div className={styles.prompts} aria-label="Suggested searches">
        {prompts.map(({ icon: Icon, label }) => (
          <button key={label} type="button" onClick={() => onPrompt(label)}>
            <Icon size={17} />
            <span>{label}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
