export interface Listing {
  id: number;
  source: string;
  model: string;
  generation: string;
  year: number | null;
  mileage_km: number | null;
  transmission: string | null;
  drivetrain: string | null;
  price_czk: number;
  currency: string;
  url: string;
  title: string;
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
