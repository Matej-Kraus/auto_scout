const MODEL_LABELS: Record<string, string> = {
  bmw_130i: "BMW 130i",
  audi_s3: "Audi S3",
  golf_gti: "Golf GTI",
};

export const modelLabel = (m: string) => MODEL_LABELS[m] ?? m.toUpperCase();

export const czk = (n: number) =>
  new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 }).format(n) + " Kč";

export const km = (n: number | null) =>
  n == null ? "—" : new Intl.NumberFormat("cs-CZ").format(n) + " km";

export const pct = (p: number | null) =>
  p == null ? null : Math.round(p * 100);

export const transmissionLabel = (t: string | null) =>
  t === "manual" ? "MANUÁL" : t === "auto" ? "AUTOMAT" : "—";

export const drivetrainLabel = (d: string | null) => (d ? d.toUpperCase() : "—");

export const sourceLabel = (s: string) =>
  ({ sauto: "SAUTO", autoscout24: "AS24", mobilede: "MOBILE.DE" })[s] ?? s.toUpperCase();

// Barva podle kvality dealu (deal_score)
export function dealTier(score: number | null): "hot" | "good" | "fair" | "none" {
  if (score == null) return "none";
  if (score >= 0.18) return "hot";
  if (score >= 0.1) return "good";
  if (score >= 0.03) return "fair";
  return "none";
}

export const timeAgo = (iso: string) => {
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3.6e6);
  if (h < 1) return "před chvílí";
  if (h < 24) return `před ${h} h`;
  const d = Math.floor(h / 24);
  return `před ${d} d`;
};
