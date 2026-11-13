import type { SearchResult } from "../chatTypes";
import { VehicleCard } from "./VehicleCard";
import styles from "./VehicleResults.module.css";

interface VehicleResultsProps {
  compact?: boolean;
  result: SearchResult;
  onGetDetails: (lotNumber: string) => void;
  onShowMore: () => void;
}

export function VehicleResults({
  compact = false,
  result,
  onGetDetails,
  onShowMore,
}: VehicleResultsProps) {
  return (
    <section className={styles.results} aria-label="Vehicle search results">
      <div className={`${styles.grid} ${compact ? styles.compactGrid : ""}`}>
        {result.vehicles.slice(0, 4).map((vehicle) => (
          <VehicleCard
            compact={compact}
            key={vehicle.lot_number || vehicle.link}
            vehicle={vehicle}
            onGetDetails={onGetDetails}
          />
        ))}
      </div>
      {result.has_more && (
        <button className={styles.moreButton} type="button" onClick={onShowMore}>
          Show me more vehicles
        </button>
      )}
    </section>
  );
}
