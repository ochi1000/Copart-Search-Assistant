import styles from "./BrandLogo.module.css";

interface BrandLogoProps {
  compact?: boolean;
}

export function BrandLogo({ compact = false }: BrandLogoProps) {
  return (
    <div className={styles.brand}>
      <img
        className={compact ? styles.compactLogo : styles.logo}
        src="/copart-logo.svg"
        alt="Copart"
      />
      <span className={styles.divider} aria-hidden="true" />
      <span className={styles.name}>Search Assistant</span>
    </div>
  );
}
