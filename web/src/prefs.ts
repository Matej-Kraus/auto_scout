// Oblíbené a skryté inzeráty — localStorage (osobní nástroj, žádný login).
// Klíč = URL inzerátu (stabilní napříč přegenerováním DB, unikátní per portál).

const FAV_KEY = "carscout.favorites";
const HIDDEN_KEY = "carscout.hidden";

function load(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function save(key: string, set: Set<string>) {
  try {
    localStorage.setItem(key, JSON.stringify([...set]));
  } catch {
    // storage plný/nedostupný — ignoruj, jde o pohodlí, ne o data
  }
}

export function loadFavorites(): Set<string> {
  return load(FAV_KEY);
}

export function loadHidden(): Set<string> {
  return load(HIDDEN_KEY);
}

export function toggleIn(set: Set<string>, url: string): Set<string> {
  const next = new Set(set);
  if (next.has(url)) next.delete(url);
  else next.add(url);
  return next;
}

export function saveFavorites(set: Set<string>) {
  save(FAV_KEY, set);
}

export function saveHidden(set: Set<string>) {
  save(HIDDEN_KEY, set);
}
