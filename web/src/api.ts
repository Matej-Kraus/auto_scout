import type { Listing, ListingDetail } from "./types";

// V produkci (Vercel) lze pres VITE_API_BASE smerovat na serverless endpoint.
const BASE = import.meta.env.VITE_API_BASE ?? "";

export async function fetchListings(params: {
  active?: boolean;
  model?: string;
}): Promise<Listing[]> {
  const q = new URLSearchParams();
  q.set("active", String(params.active ?? true));
  if (params.model) q.set("model", params.model);
  const res = await fetch(`${BASE}/api/listings?${q.toString()}`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export async function fetchListing(id: number): Promise<ListingDetail> {
  const res = await fetch(`${BASE}/api/listings/${id}`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
