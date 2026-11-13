import { ExternalLink, Gauge, MapPin } from "lucide-react";

import type { VehicleListing } from "../chatTypes";
import styles from "./VehicleCard.module.css";

interface VehicleCardProps {
  compact?: boolean;
  vehicle: VehicleListing;
  onGetDetails: (lotNumber: string) => void;
}

export function VehicleCard({
  compact = false,
  vehicle,
  onGetDetails,
}: VehicleCardProps) {
  return (
    <article className={`${styles.card} ${compact ? styles.compact : ""}`}>
      <div className={styles.imageFrame}>
        {vehicle.image_url ? (
          <img src={vehicle.image_url} alt={vehicle.title} loading="lazy" />
        ) : (
          <div className={styles.imageFallback}>Image unavailable</div>
        )}
        {vehicle.title_status && (
          <span className={styles.titleBadge}>{vehicle.title_status}</span>
        )}
      </div>

      <div className={styles.body}>
        <div>
          <p className={styles.lot}>Lot {vehicle.lot_number}</p>
          <h3>{vehicle.title}</h3>
        </div>

        <div className={styles.meta}>
          {vehicle.odometer && (
            <span><Gauge size={14} /> {vehicle.odometer}</span>
          )}
          {vehicle.yard_location && (
            <span><MapPin size={14} /> {vehicle.yard_location}</span>
          )}
        </div>

        {vehicle.damage && <p className={styles.damage}>{vehicle.damage}</p>}

        <div className={styles.footer}>
          <div className={styles.pricing}>
            <span>
              <small>Current bid</small>
              <strong>{vehicle.current_bid || "Not available"}</strong>
            </span>
            {vehicle.buy_it_now_price && (
              <span>
                <small>Buy it now</small>
                <strong>{vehicle.buy_it_now_price}</strong>
              </span>
            )}
          </div>
          <div className={styles.actions}>
            <button type="button" onClick={() => onGetDetails(vehicle.lot_number)}>
              Details
            </button>
            {vehicle.link && (
              <a href={vehicle.link} target="_blank" rel="noreferrer">
                View lot <ExternalLink size={13} />
              </a>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
