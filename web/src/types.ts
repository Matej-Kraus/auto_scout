export interface Listing {
  id: number;
  source: string;
  model: string;
  generation: string;
  year: number | null;
  mileage_km: number | null;
  transmission: string | null;
  drivetrain: string | null;
  fuel_type: string | null;
  power_kw: number | null;
  body_type: string | null;
  price_rating: string | null; // "great" | "good" | "fair" | "high" — jen kde to portal nabizi
  price_czk: number;
  currency: string;
  url: string;
  title: string;
  image_url: string | null;
  first_seen: string;
  last_seen: string;
  is_active: boolean;
  deal_score: number | null;
  expected_price: number | null;
  pct_below: number | null;
  score_method: string | null;
}

export interface PricePoint {
  price_czk: number;
  seen_at: string;
}

export interface ListingDetail extends Listing {
  price_history: PricePoint[];
}

export interface Watch {
  id: number;
  make: string;
  model: string;
  variant: string;
  year_from: number | null;
  year_to: number | null;
  price_from_czk: number | null;
  price_to_czk: number | null;
  model_key: string;
  label: string;
  enabled: boolean;
  curated: boolean;
  active_listings: number;
}

export interface WatchInput {
  make: string;
  model: string;
  variant?: string;
  year_from?: number | null;
  year_to?: number | null;
  price_from_czk?: number | null;
  price_to_czk?: number | null;
}

export interface Status {
  last_run: string | null;
  last_alert: string | null;
  total_listings: number;
  active_listings: number;
  hot_deals: number;
  by_model: Record<string, number>;
  median_days_to_sell: number | null;
}
