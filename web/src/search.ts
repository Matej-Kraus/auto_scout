import type { Listing } from "./types";

export interface SearchState {
  query: string;
  manualOnly: boolean;
  maxPrice: number | null;
  source: string | null; // "sauto" | "sbazar" | ... | null = vše
  fuel: string | null; // "petrol" | "diesel" | ... | null = vše
  yearFrom: number | null;
  yearTo: number | null;
  dedupe: boolean; // sloučit stejné auto z víc bazarů do jednoho
}

export const EMPTY_SEARCH: SearchState = {
  query: "",
  manualOnly: false,
  maxPrice: null,
  source: null,
  fuel: null,
  yearFrom: null,
  yearTo: null,
  dedupe: true,
};

export function isSearchActive(s: SearchState): boolean {
  return (
    s.query.trim() !== "" ||
    s.manualOnly ||
    s.maxPrice != null ||
    s.source != null ||
    s.fuel != null ||
    s.yearFrom != null ||
    s.yearTo != null
  );
}

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
    if (s.fuel && l.fuel_type !== s.fuel) return false;
    if (s.yearFrom != null && (l.year == null || l.year < s.yearFrom)) return false;
    if (s.yearTo != null && (l.year == null || l.year > s.yearTo)) return false;
    if (!matchesQuery(l, s.query)) return false;
    return true;
  });
}

/** Jeden vůz, případně nabízený na víc bazarech. `primary` = ten nejlepší/nejlevnější. */
export interface Cluster {
  primary: Listing;
  duplicates: Listing[]; // stejné auto z jiných bazarů
}

const MILEAGE_TOL_KM = 3000;
const PRICE_TOL = 0.08;

function similar(a: number, b: number, tol: number): boolean {
  const hi = Math.max(Math.abs(a), Math.abs(b));
  return hi === 0 || Math.abs(a - b) / hi <= tol;
}

/** Stejná heuristika jako v backendu (app/dedup.py same_car) — bez VINu. */
function sameCar(a: Listing, b: Listing): boolean {
  if (a.year == null || a.mileage_km == null || b.year == null || b.mileage_km == null)
    return false;
  return (
    a.model === b.model &&
    a.generation === b.generation &&
    a.year === b.year &&
    Math.abs(a.mileage_km - b.mileage_km) <= MILEAGE_TOL_KM &&
    similar(a.price_czk, b.price_czk, PRICE_TOL)
  );
}

/**
 * Sloučí stejný vůz nabízený na víc bazarech do jednoho clusteru.
 * Vstup se předpokládá seřazený podle skóre (nejlepší první) → první výskyt je primary.
 */
export function clusterListings(listings: Listing[]): Cluster[] {
  const clusters: Cluster[] = [];
  const taken = new Set<number>();

  for (const l of listings) {
    if (taken.has(l.id)) continue;
    const cluster: Cluster = { primary: l, duplicates: [] };
    taken.add(l.id);
    for (const other of listings) {
      if (taken.has(other.id)) continue;
      if (sameCar(l, other)) {
        cluster.duplicates.push(other);
        taken.add(other.id);
      }
    }
    clusters.push(cluster);
  }
  return clusters;
}
