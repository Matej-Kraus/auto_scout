import type { Listing } from "./types";

export interface SearchState {
  query: string;
  manualOnly: boolean;
  maxPrice: number | null;
  source: string | null; // "sauto" | "sbazar" | ... | null = vše
}

export const EMPTY_SEARCH: SearchState = {
  query: "",
  manualOnly: false,
  maxPrice: null,
  source: null,
};

const MANUAL_WORDS = new Set(["manual", "manuál", "manualni", "manuální", "mt"]);
const AUTO_WORDS = new Set(["automat", "auto", "dsg", "at", "tiptronic"]);
const AWD_WORDS = new Set(["awd", "quattro", "4x4", "4motion", "xdrive", "4matic", "allrad"]);

/**
 * Chytrý fulltext nad inzeráty: rozdělí dotaz na tokeny a každý musí sedět.
 * - 4místné číslo  → ročník (year)
 * - manual/automat → převodovka
 * - awd/rwd/fwd/quattro… → pohon
 * - ostatní slova  → musí být v názvu inzerátu
 * Takže "golf gti 2013 manual" = název má golf+gti, ročník 2013, manuál.
 */
function matchesQuery(l: Listing, query: string): boolean {
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return true;
  const title = (l.title ?? "").toLowerCase();

  for (const tok of tokens) {
    if (/^(19|20)\d{2}$/.test(tok)) {
      if (String(l.year ?? "") !== tok) return false;
    } else if (MANUAL_WORDS.has(tok)) {
      if (l.transmission !== "manual") return false;
    } else if (AUTO_WORDS.has(tok)) {
      if (l.transmission !== "auto") return false;
    } else if (AWD_WORDS.has(tok)) {
      if (l.drivetrain !== "awd") return false;
    } else if (tok === "rwd") {
      if (l.drivetrain !== "rwd") return false;
    } else if (tok === "fwd") {
      if (l.drivetrain !== "fwd") return false;
    } else if (!title.includes(tok)) {
      return false;
    }
  }
  return true;
}

export function applySearch(listings: Listing[], s: SearchState): Listing[] {
  return listings.filter((l) => {
    if (s.manualOnly && l.transmission !== "manual") return false;
    if (s.maxPrice != null && l.price_czk > s.maxPrice) return false;
    if (s.source && l.source !== s.source) return false;
    if (!matchesQuery(l, s.query)) return false;
    return true;
  });
}
