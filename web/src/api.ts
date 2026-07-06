import type { Listing, ListingDetail, Status, Watch, WatchInput } from "./types";

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

export async function fetchStatus(): Promise<Status> {
  const res = await fetch(`${BASE}/api/status`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export async function fetchWatches(): Promise<Watch[]> {
  const res = await fetch(`${BASE}/api/watches`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export async function addWatch(data: WatchInput): Promise<Watch> {
  const res = await fetch(`${BASE}/api/watches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `API ${res.status}`);
  }
  return res.json();
}

export async function deleteWatch(id: number, purge = true): Promise<void> {
  const res = await fetch(`${BASE}/api/watches/${id}?purge=${purge}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status}`);
}

export interface CatalogMake {
  id: number;
  name: string;
}

export async function fetchMakes(): Promise<{ top_make_ids: number[]; makes: CatalogMake[] }> {
  const res = await fetch(`${BASE}/api/catalog/makes`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export async function fetchModels(makeId: number): Promise<CatalogMake[]> {
  const res = await fetch(`${BASE}/api/catalog/models/${makeId}`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export interface RunResult {
  status: string;
  summary: string;
  alerts: number;
}

/** Prohledá auto na všech bazarech. Volitelně smaže stará data (refresh) a
 *  připojí mobile.de (běží lokálně z domácí IP, pomalejší). */
export async function runScan(
  modelKey: string,
  opts: { refresh?: boolean; includeMobilede?: boolean } = {},
): Promise<RunResult> {
  const q = new URLSearchParams({ model_key: modelKey });
  if (opts.refresh) q.set("refresh", "true");
  if (opts.includeMobilede) q.set("include_mobilede", "true");
  const res = await fetch(`${BASE}/api/run?${q.toString()}`, { method: "POST" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
