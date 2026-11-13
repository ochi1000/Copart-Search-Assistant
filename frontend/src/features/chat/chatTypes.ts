export type ChatRole = "user" | "assistant";
export type ChatStatus =
  | "idle"
  | "thinking"
  | "searching"
  | "verification"
  | "cancelling";

export interface VehicleListing {
  title: string;
  lot_number: string;
  title_status?: string;
  damage?: string;
  odometer?: string;
  odometer_miles?: number;
  yard_location?: string;
  current_bid?: string;
  buy_it_now_price?: string;
  condition?: string;
  link?: string;
  image_url?: string;
}

export interface SearchResult {
  search_id?: string;
  query?: string;
  vehicles: VehicleListing[];
  count_returned?: number;
  has_more?: boolean;
  notice?: string;
  match_status?: string;
  filter_warnings?: string[];
}

export interface VehicleDetail {
  lot_url?: string;
  vehicle_title?: string;
  vin?: string;
  condition?: string;
  auction_date?: string;
  yard_location?: string;
  photo_count?: number;
  primary_image_url?: string;
  gallery_photos?: string[];
  image_status?: string;
}

export interface CompletedResult {
  message: string;
  search_id?: string;
  search?: SearchResult;
  vehicle?: VehicleDetail;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  search?: SearchResult;
  vehicle?: VehicleDetail;
}

export interface OperationEvent<T = Record<string, unknown>> {
  event_id: string;
  operation_id: string;
  type: string;
  timestamp: string;
  data: T;
}

export interface OperationAccepted {
  operation_id: string;
  session_id: string;
  status: "accepted";
}

export interface PublicApiError {
  code?: string;
  message: string;
  retryable?: boolean;
}
