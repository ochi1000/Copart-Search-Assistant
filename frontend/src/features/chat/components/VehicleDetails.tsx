import { ExternalLink, MapPin } from "lucide-react";

import type { VehicleDetail } from "../chatTypes";
import styles from "./VehicleDetails.module.css";

export function VehicleDetails({ detail }: { detail: VehicleDetail }) {
  const photos = detail.gallery_photos ?? [];
  const primary = detail.primary_image_url || photos[0];
  const remaining = photos.filter((photo) => photo !== primary).slice(0, 5);

  return (
    <article className={styles.details}>
      {primary && <img className={styles.primary} src={primary} alt={detail.vehicle_title} />}
      <div className={styles.body}>
        <div>
          <p className={styles.eyebrow}>Vehicle details</p>
          <h3>{detail.vehicle_title || "Copart vehicle"}</h3>
        </div>
        <dl>
          {detail.vin && <><dt>VIN</dt><dd>{detail.vin}</dd></>}
          {detail.condition && <><dt>Condition</dt><dd>{detail.condition}</dd></>}
          {detail.auction_date && <><dt>Auction</dt><dd>{detail.auction_date}</dd></>}
        </dl>
        {detail.yard_location && (
          <p className={styles.location}><MapPin size={15} /> {detail.yard_location}</p>
        )}
        {remaining.length > 0 && (
          <div className={styles.gallery}>
            {remaining.map((photo) => (
              <img key={photo} src={photo} alt="Additional vehicle view" loading="lazy" />
            ))}
          </div>
        )}
        {detail.lot_url && (
          <a href={detail.lot_url} target="_blank" rel="noreferrer">
            Open lot on Copart <ExternalLink size={14} />
          </a>
        )}
      </div>
    </article>
  );
}
