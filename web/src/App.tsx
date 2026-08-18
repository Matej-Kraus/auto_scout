import { useCallback, useEffect, useMemo, useState } from "react";
import {
  addWatch,
  type CatalogMake,
  deleteWatch,
  fetchListings,
  fetchMakes,
  fetchModels,
  fetchStatus,
  fetchWatches,
  runScan,
} from "./api";
import { Drawer } from "./Drawer";
import { buildExport, downloadExport } from "./export";
import { FilterPanel } from "./FilterPanel";
import {
  bodyLabel,
  czk,
  dealIndex,
  implausibleLabel,
  drivetrainLabel,
  fuelLabel,
  km,
  kw,
  pct,
  priceRatingLabel,
  sourceLabel,
  timeAgo,
  transmissionLabel,
} from "./format";
import {
  loadFavorites,
  loadHidden,
  saveFavorites,
  saveHidden,
  toggleIn,
} from "./prefs";
import {
  applySearch,
  clusterListings,
  type Cluster,
  EMPTY_SEARCH,
  isNew,
  describeSearch,
  isSearchActive,
  type SearchState,
  SORT_LABELS,
  type SortKey,
  sortClusters,
} from "./search";
import type { Listing, Status, Watch } from "./types";


export function App() {
  const [listings, setListings] = useState<Listing[] | null>(null);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string | null>(null); // model_key
  const [openId, setOpenId] = useState<number | null>(null);
  const [search, setSearch] = useState<SearchState>(EMPTY_SEARCH);
  const [showAdd, setShowAdd] = useState(false);
  const [scanning, setScanning] = useState<string | null>(null); // model_key prave prohledavany
  const [visibleCount, setVisibleCount] = useState(48);
  const [favorites, setFavorites] = useState<Set<string>>(loadFavorites);
  const [hidden, setHidden] = useState<Set<string>>(loadHidden);
  const [showFilters, setShowFilters] = useState(false);

  const toggleFavorite = useCallback((url: string) => {
    setFavorites((prev) => {
      const next = toggleIn(prev, url);
      saveFavorites(next);
      return next;
    });
  }, []);
  const toggleHidden = useCallback((url: string) => {
    setHidden((prev) => {
      const next = toggleIn(prev, url);
      saveHidden(next);
      return next;
    });
  }, []);

  const loadListings = useCallback(() => {
    setListings(null);
    setError(null);
    fetchListings({ active: true, model: filter ?? undefined })
      .then(setListings)
      .catch((e) => setError(String(e)));
  }, [filter]);

  const loadWatches = useCallback(() => {
    fetchWatches().then(setWatches).catch(() => {});
  }, []);

  useEffect(loadListings, [loadListings]);
  useEffect(() => {
    loadWatches();
    fetchStatus().then(setStatus).catch(() => {});
  }, [loadWatches]);


  // Fulltext + filtry client-side, pak slouceni stejneho auta z vic bazaru.
  const matched = useMemo(
    () => (listings ? applySearch(listings, search, favorites, hidden) : null),
    [listings, search, favorites, hidden],
  );

  const hiddenCount = useMemo(
    () => (listings ?? []).filter((l) => hidden.has(l.url)).length,
    [listings, hidden],
  );
  const newCount = useMemo(
    () => (listings ?? []).filter((l) => isNew(l) && !hidden.has(l.url)).length,
    [listings, hidden],
  );
  // kolik filtrů v panelu je aktivních (rozsahy + výběry, bez toggle přepínačů)
  const activeFilterCount = useMemo(() => {
    const s = search;
    const vals = [
      s.priceFrom,
      s.priceTo,
      s.yearFrom,
      s.yearTo,
      s.kmFrom,
      s.kmTo,
      s.kwFrom,
      s.kwTo,
      s.transmission,
      s.drivetrain,
      s.fuel,
      s.body,
      s.source,
    ];
    return vals.filter((v) => v != null).length;
  }, [search]);

  // Zmena hledani/filtru resetuje strankovani.
  useEffect(() => setVisibleCount(48), [search, filter]);
  const clusters = useMemo<Cluster[] | null>(() => {
    if (matched == null) return null;
    const grouped = search.dedupe
      ? clusterListings(matched)
      : matched.map((l) => ({ primary: l, duplicates: [] }));
    return sortClusters(grouped, search.sort);
  }, [matched, search.dedupe, search.sort]);

  // Hero = nejlepsi deal, ale jen kdyz radime podle dealu; pri jinem razeni by
  // vytrzene auto nahore matlo (uzivatel chce videt sve poradi).
  const heroCluster = useMemo(
    () =>
      search.sort === "deal"
        ? clusters?.find((c) => c.primary.deal_tier === "hot" || c.primary.deal_score != null) ??
          null
        : null,
    [clusters, search.sort],
  );
  const restClusters = useMemo(
    () =>
      heroCluster
        ? clusters?.filter((c) => c.primary.id !== heroCluster.primary.id) ?? []
        : clusters ?? [],
    [clusters, heroCluster],
  );

  const hotCount =
    clusters?.filter((c) => c.primary.deal_tier === "hot").length ?? 0;
  const searchActive = isSearchActive(search);

  const labelFor = useCallback(
    (modelKey: string) => watches.find((w) => w.model_key === modelKey)?.label ?? modelKey,
    [watches],
  );

  async function handleRemoveWatch(w: Watch) {
    if (!window.confirm(`Přestat hlídat ${w.label}? Smažou se i jeho inzeráty.`)) return;
    await deleteWatch(w.id, true).catch((e) => alert(String(e)));
    if (filter === w.model_key) setFilter(null);
    loadWatches();
    loadListings();
  }

  async function handleScanNow(
    modelKey: string,
    opts: { refresh?: boolean; includeMobilede?: boolean } = { includeMobilede: true },
  ) {
    setScanning(modelKey);
    try {
      await runScan(modelKey, opts);
      loadListings();
      loadWatches();
    } catch {
      alert(
        "Auto je uložené v garáži. Prohledání teď neběží (nespuštěné lokální API?) — " +
          "cron ho najde při dalším běhu.",
      );
      loadWatches();
    } finally {
      setScanning(null);
    }
  }

  async function handleReset(w: Watch) {
    if (
      !window.confirm(
        `Najít ${w.label} znovu? Smažou se stará data a prohledají se všechny bazary ` +
          `(vč. mobile.de) načisto. Chvíli to trvá.`,
      )
    )
      return;
    await handleScanNow(w.model_key, { refresh: true, includeMobilede: true });
  }

  return (
    <div className="shell">
      <header className="masthead">
        <div className="brand">
          <div className="brand-mark">DH</div>
          <div>
            <h1>
              Deal <span>Hunter</span>
            </h1>
            <div className="sub">sauto · sbazar · autoscout24 · cz + de</div>
          </div>
        </div>
        <div className="readout">
          {clusters == null ? (
            "SCAN…"
          ) : (
            <>
              <b>{clusters.length}</b> aut ·{" "}
              <b style={{ color: "var(--hot)" }}>{hotCount}</b> hot
              {newCount > 0 && (
                <>
                  {" "}
                  · <b style={{ color: "var(--good)" }}>{newCount}</b> nových
                </>
              )}
              <br />
              {status?.last_run ? `naposledy ${timeAgo(status.last_run)}` : " "}
              {status?.median_days_to_sell != null && (
                <>
                  <br />
                  prodej typicky za {status.median_days_to_sell} d
                </>
              )}
            </>
          )}
        </div>
      </header>

      <div className="deck">
        <div className="searchbar">
          <span className="search-ico">⌕</span>
          <input
            className="search-input"
            placeholder="Hledej: golf gti 2013 manual…"
            value={search.query}
            onChange={(e) => setSearch((s) => ({ ...s, query: e.target.value }))}
          />
          {searchActive && (
            <button className="search-clear" onClick={() => setSearch(EMPTY_SEARCH)}>
              ✕ zrušit
            </button>
          )}
        </div>

        <div className="deck-row">
          <span className="lbl">Garáž</span>
          <button
            className={`pill ${filter === null ? "active" : ""}`}
            onClick={() => setFilter(null)}
          >
            Vše
          </button>
          {watches.map((w) => (
            <span key={w.model_key} className="garage-pill">
              <button
                className={`pill ${filter === w.model_key ? "active" : ""}`}
                onClick={() => setFilter(filter === w.model_key ? null : w.model_key)}
                title={`${w.active_listings} aktivních inzerátů`}
              >
                {w.label}
                <em>{w.active_listings}</em>
              </button>
              <button
                className="pill-x pill-reset"
                title={`Najít ${w.label} znovu (smaže staré, prohledá vč. mobile.de)`}
                disabled={scanning === w.model_key}
                onClick={() => handleReset(w)}
              >
                {scanning === w.model_key ? "…" : "⟳"}
              </button>
              {!w.curated && (
                <button
                  className="pill-x"
                  title={`Přestat hlídat ${w.label}`}
                  onClick={() => handleRemoveWatch(w)}
                >
                  ✕
                </button>
              )}
            </span>
          ))}
          <button className="pill pill-add" onClick={() => setShowAdd((v) => !v)}>
            {showAdd ? "− zavřít" : "+ Přidat auto"}
          </button>
        </div>

        {showAdd && (
          <AddWatchForm
            onAdded={(w) => {
              setShowAdd(false);
              loadWatches();
              handleScanNow(w.model_key);
            }}
          />
        )}

        <div className="deck-row">
          <span className="lbl">Filtr</span>
          <button
            className={`pill ${showFilters || activeFilterCount > 0 ? "active" : ""}`}
            onClick={() => setShowFilters((v) => !v)}
          >
            ⚙ Filtry{activeFilterCount > 0 && <em>{activeFilterCount}</em>}
          </button>
          {newCount > 0 && (
            <button
              className={`pill pill-new ${search.newOnly ? "active" : ""}`}
              title="Jen auta naskočená za posledních 48 h"
              onClick={() => setSearch((s) => ({ ...s, newOnly: !s.newOnly }))}
            >
              🆕 Nové<em>{newCount}</em>
            </button>
          )}
          <button
            className={`pill ${search.favoritesOnly ? "active" : ""}`}
            title="Jen auta označená hvězdičkou"
            onClick={() => setSearch((s) => ({ ...s, favoritesOnly: !s.favoritesOnly }))}
          >
            ★ Oblíbené{favorites.size > 0 && <em>{favorites.size}</em>}
          </button>
          <button
            className={`pill ${search.dedupe ? "active" : ""}`}
            title="Stejné auto nabízené na víc bazarech ukázat jen jednou"
            onClick={() => setSearch((s) => ({ ...s, dedupe: !s.dedupe }))}
          >
            ⛓ Bez duplicit
          </button>
          {hiddenCount > 0 && (
            <button
              className={`pill ${search.showHidden ? "active" : ""}`}
              title="Zobrazit i skrytá auta"
              onClick={() => setSearch((s) => ({ ...s, showHidden: !s.showHidden }))}
            >
              Skryté<em>{hiddenCount}</em>
            </button>
          )}
          <button
            className="pill"
            title="Stáhne zobrazená auta jako .md soubor — dá se rovnou předat AI k posouzení"
            disabled={!clusters || clusters.length === 0}
            onClick={() => {
              if (!clusters) return;
              const shown = clusters.slice(0, visibleCount);
              const note = describeSearch(search, filter ? labelFor(filter) : undefined);
              downloadExport(buildExport(shown, note), shown.length);
            }}
          >
            ⬇ Export{clusters && clusters.length > 0 && <em>{Math.min(clusters.length, visibleCount)}</em>}
          </button>
          <label className="sortwrap">
            <span className="sortlbl">Řadit</span>
            <select
              className="sortbtn"
              value={search.sort}
              onChange={(e) => setSearch((s) => ({ ...s, sort: e.target.value as SortKey }))}
            >
              {Object.entries(SORT_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {showFilters && (
          <FilterPanel
            search={search}
            setSearch={setSearch}
            listings={listings ?? []}
            onClose={() => setShowFilters(false)}
          />
        )}
      </div>

      {scanning && (
        <div className="state">
          <div className="spin" />
          PROHLEDÁVÁM BAZARY PRO {labelFor(scanning).toUpperCase()}… (~1 min)
        </div>
      )}

      {error && <div className="state">CHYBA: {error}. Běží FastAPI na :8000?</div>}

      {!error && listings == null && !scanning && (
        <div className="state">
          <div className="spin" />
          SKENUJI TRH…
        </div>
      )}

      {!error && clusters != null && clusters.length === 0 && !scanning && (
        <div className="state">
          {listings && listings.length > 0 ? (
            <>
              ŽÁDNÝ INZERÁT NEODPOVÍDÁ HLEDÁNÍ.
              <br />
              Zkus volnější dotaz nebo zruš filtry.
            </>
          ) : (
            <>
              ŽÁDNÉ AKTIVNÍ INZERÁTY.
              <br />
              Přidej auto tlačítkem „+ Přidat auto“, nebo spusť:{" "}
              <code>python -m app.run_once</code>
            </>
          )}
        </div>
      )}

      {heroCluster && (
        <HeroCard
          listing={heroCluster.primary}
          duplicates={heroCluster.duplicates}
          isFav={favorites.has(heroCluster.primary.url)}
          onFav={() => toggleFavorite(heroCluster.primary.url)}
          onOpen={() => setOpenId(heroCluster.primary.id)}
        />
      )}

      {clusters != null && clusters.length > 0 && (
        <>
          <div className="section-head">
            <h3>{searchActive ? "Výsledky hledání" : "Žebříček dealů"}</h3>
            <span className="count">SEŘAZENO DLE SKÓRE ▾</span>
          </div>
          <div className="cards">
            {restClusters.slice(0, visibleCount).map((c, i) => (
              <CarCard
                key={c.primary.id}
                listing={c.primary}
                duplicates={c.duplicates}
                rank={i + (heroCluster ? 2 : 1)}
                delay={Math.min(i % 48, 12) * 0.04}
                isFav={favorites.has(c.primary.url)}
                isHidden={hidden.has(c.primary.url)}
                onFav={() => toggleFavorite(c.primary.url)}
                onHide={() => toggleHidden(c.primary.url)}
                onOpen={() => setOpenId(c.primary.id)}
              />
            ))}
          </div>
          {restClusters.length > visibleCount && (
            <div className="loadmore">
              <button
                className="pill"
                onClick={() => setVisibleCount((n) => n + 48)}
              >
                Načíst další ({restClusters.length - visibleCount} zbývá)
              </button>
            </div>
          )}
        </>
      )}

      {openId != null && <Drawer id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function AddWatchForm({ onAdded }: { onAdded: (w: Watch) => void }) {
  const [makes, setMakes] = useState<CatalogMake[]>([]);
  const [topIds, setTopIds] = useState<number[]>([]);
  const [models, setModels] = useState<CatalogMake[] | null>(null); // null = nenačteno
  const [makeId, setMakeId] = useState<number | "">("");
  const [model, setModel] = useState("");
  const [variant, setVariant] = useState("");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [priceTo, setPriceTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchMakes()
      .then((d) => {
        setMakes(d.makes);
        setTopIds(d.top_make_ids);
      })
      .catch(() => setErr("Katalog značek se nenačetl — zkus obnovit stránku."));
  }, []);

  // Po výběru značky natáhni její modely.
  useEffect(() => {
    setModel("");
    setModels(null);
    if (makeId === "") return;
    fetchModels(makeId)
      .then(setModels)
      .catch(() => setModels([])); // katalog nedostupný → ruční zadání
  }, [makeId]);

  const makeName = makes.find((m) => m.id === makeId)?.name ?? "";
  const topMakes = topIds
    .map((id) => makes.find((m) => m.id === id))
    .filter((m): m is CatalogMake => !!m);
  const restMakes = makes.filter((m) => !topIds.includes(m.id));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!makeName || !model) return;
    setErr(null);
    setBusy(true);
    try {
      const w = await addWatch({
        make: makeName,
        model,
        variant,
        year_from: yearFrom ? Number(yearFrom) : null,
        year_to: yearTo ? Number(yearTo) : null,
        price_to_czk: priceTo ? Number(priceTo) : null,
      });
      onAdded(w);
    } catch (ex) {
      setErr(String(ex instanceof Error ? ex.message : ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="addform" onSubmit={submit}>
      <select
        required
        value={makeId}
        onChange={(e) => setMakeId(e.target.value ? Number(e.target.value) : "")}
      >
        <option value="">Značka *</option>
        {topMakes.length > 0 && (
          <optgroup label="Nejčastější">
            {topMakes.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </optgroup>
        )}
        <optgroup label="Všechny značky">
          {restMakes.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </optgroup>
      </select>

      {models && models.length > 0 ? (
        <select required value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">Model *</option>
          {models.map((m) => (
            <option key={m.id} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
      ) : (
        <input
          required
          placeholder={
            makeId === ""
              ? "Model * (nejdřív vyber značku)"
              : models === null
                ? "Načítám modely…"
                : "Model * (napiš ručně)"
          }
          disabled={makeId === "" || models === null}
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />
      )}

      <input
        placeholder="Upřesnění (RS, GTI, quattro…)"
        value={variant}
        onChange={(e) => setVariant(e.target.value)}
      />
      <input
        required
        placeholder="Rok od * (např. 2013)"
        inputMode="numeric"
        pattern="(19|20)\d{2}"
        title="Rok 1980–2030 — jedna generace = smysluplné skóre vůči trhu"
        value={yearFrom}
        onChange={(e) => setYearFrom(e.target.value)}
      />
      <input
        required
        placeholder="Rok do * (např. 2020)"
        inputMode="numeric"
        pattern="(19|20)\d{2}"
        title="Rok 1980–2030 — jedna generace = smysluplné skóre vůči trhu"
        value={yearTo}
        onChange={(e) => setYearTo(e.target.value)}
      />
      <input
        placeholder="Cena do (Kč)"
        inputMode="numeric"
        value={priceTo}
        onChange={(e) => setPriceTo(e.target.value)}
      />
      <div className="addform-hint">
        Roky vymezují generaci — bez nich se do porovnání cen míchají stará a nová auta.
      </div>
      <button className="pill pill-add" type="submit" disabled={busy || !makeName || !model}>
        {busy ? "Přidávám…" : "Hlídat a prohledat"}
      </button>
      {err && <div className="addform-err">{err}</div>}
    </form>
  );
}

function AlsoOn({ duplicates }: { duplicates: Listing[] }) {
  if (duplicates.length === 0) return null;
  return (
    <span className="alsoon" title="Stejné auto nalezené i na těchto bazarech">
      také na {duplicates.map((d) => sourceLabel(d.source)).join(", ")}
    </span>
  );
}

function Gauge({ score }: { score: number }) {
  const idx = dealIndex(score);
  const p = idx / 100;
  const c = Math.PI * 64;
  const dash = c * p;
  return (
    <div className="gauge">
      <svg width="160" height="100" viewBox="0 0 160 100">
        <path
          d="M16 92 A 64 64 0 0 1 144 92"
          fill="none"
          stroke="#232c35"
          strokeWidth="10"
          strokeLinecap="round"
        />
        <path
          d="M16 92 A 64 64 0 0 1 144 92"
          fill="none"
          stroke="#2fe39b"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          style={{ filter: "drop-shadow(0 0 6px rgba(47,227,155,0.6))" }}
        />
      </svg>
      <div className="val">{idx}</div>
      <div className="unit">deal index</div>
    </div>
  );
}

function HeroCard({
  listing,
  duplicates,
  isFav,
  onFav,
  onOpen,
}: {
  listing: Listing;
  duplicates: Listing[];
  isFav: boolean;
  onFav: () => void;
  onOpen: () => void;
}) {
  const below = pct(listing.pct_below);
  return (
    <div className="hero" onClick={onOpen} role="button">
      <button
        className={`starbtn hero-star ${isFav ? "on" : ""}`}
        title={isFav ? "Odebrat z oblíbených" : "Přidat do oblíbených"}
        onClick={(e) => {
          e.stopPropagation();
          onFav();
        }}
      >
        {isFav ? "★" : "☆"}
      </button>
      <div>
        <div className="tag">nejlepší deal teď · {sourceLabel(listing.source)}</div>
        {listing.image_url && (
          <img className="hero-thumb" src={listing.image_url} alt="" loading="lazy" />
        )}
        <h2>{listing.title}</h2>
        <div className="specs">
          <span>{listing.year ?? "—"}</span>
          <span>{km(listing.mileage_km)}</span>
          {listing.power_kw != null && <span>{kw(listing.power_kw)}</span>}
          <span>{transmissionLabel(listing.transmission)}</span>
          <span>{drivetrainLabel(listing.drivetrain)}</span>
          <span>{fuelLabel(listing.fuel_type)}</span>
          {listing.body_type && <span>{bodyLabel(listing.body_type)}</span>}
          <span>· {timeAgo(listing.first_seen)}</span>
        </div>
        {duplicates.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <AlsoOn duplicates={duplicates} />
          </div>
        )}
        <div className="price">
          {czk(listing.price_czk)}
          {below != null && below > 0 && (
            <span style={{ color: "var(--good)", fontSize: 18, marginLeft: 12 }}>
              {below} % pod trhem
            </span>
          )}
        </div>
        <a
          className="cta"
          href={listing.url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
        >
          Otevřít inzerát ↗
        </a>
      </div>
      {listing.deal_score != null && <Gauge score={listing.deal_score} />}
    </div>
  );
}

function CarCard({
  listing,
  duplicates,
  rank,
  delay,
  isFav,
  isHidden,
  onFav,
  onHide,
  onOpen,
}: {
  listing: Listing;
  duplicates: Listing[];
  rank: number;
  delay: number;
  isFav: boolean;
  isHidden: boolean;
  onFav: () => void;
  onHide: () => void;
  onOpen: () => void;
}) {
  const tier = listing.deal_tier;
  const below = pct(listing.pct_below);
  return (
    <article
      className={`card tier-${tier}`}
      style={{ animationDelay: `${delay}s` }}
      onClick={onOpen}
      role="button"
    >
      <div className="card-photo">
        {listing.image_url ? (
          <img src={listing.image_url} alt="" loading="lazy" />
        ) : (
          <div className="card-noimg">
            <CarSilhouette />
            <span>foto na inzerátu</span>
          </div>
        )}
        <span className="card-rank">{String(rank).padStart(2, "0")}</span>
        {isNew(listing) && <span className="card-new">NOVÉ</span>}
        <span className="card-actions">
          <button
            className={`starbtn ${isFav ? "on" : ""}`}
            title={isFav ? "Odebrat z oblíbených" : "Přidat do oblíbených"}
            onClick={(e) => {
              e.stopPropagation();
              onFav();
            }}
          >
            {isFav ? "★" : "☆"}
          </button>
          <button
            className="hidebtn"
            title={isHidden ? "Zobrazit zpět" : "Skrýt (nezajímá mě)"}
            onClick={(e) => {
              e.stopPropagation();
              onHide();
            }}
          >
            {isHidden ? "↩" : "✕"}
          </button>
        </span>
        {listing.deal_score != null && (
          <span className={`card-score tier-${tier}`}>
            {dealIndex(listing.deal_score)}
          </span>
        )}
      </div>
      <div className="card-body">
        <div className="card-title">{listing.title}</div>
        <div className="card-meta">
          <span>{listing.year ?? "—"}</span>
          <span>{km(listing.mileage_km)}</span>
          {listing.power_kw != null && <span>{kw(listing.power_kw)}</span>}
          <span>{transmissionLabel(listing.transmission)}</span>
          {listing.fuel_type && <span>{fuelLabel(listing.fuel_type)}</span>}
          {listing.body_type && <span>{bodyLabel(listing.body_type)}</span>}
        </div>
        <div className="card-priceline">
          <span className="card-price-group">
            <span className="card-price">{czk(listing.price_czk)}</span>
            {below != null && below > 0 ? (
              <span className="card-below">−{below} %</span>
            ) : (
              <span className="card-inprice">v ceně</span>
            )}
          </span>
          {listing.implausible ? (
            <span
              className="price-warn"
              title="Podezřelý inzerát — nezapočítává se do skóre ani do odhadu trhu"
            >
              ⚠ {implausibleLabel(listing.implausible)}
            </span>
          ) : (
            listing.price_rating && (
              <span
                className={`price-rating price-rating-${listing.price_rating}`}
                title={
                  listing.portal_agreement === "agree"
                    ? "Bazar i náš model se shodují — silnější signál"
                    : listing.portal_agreement === "conflict"
                      ? "Bazar hodnotí cenu opačně než náš model — opatrně"
                      : "Hodnocení ceny podle bazaru (doplňkový signál k našemu skóre)"
                }
              >
                {priceRatingLabel(listing.price_rating)}
                {listing.portal_agreement === "agree" && " ✓"}
                {listing.portal_agreement === "conflict" && " ?"}
              </span>
            )
          )}
        </div>
        <WhyDeal listing={listing} />
        <div className="card-foot">
          <span className="card-src">{sourceLabel(listing.source)}</span>
          {listing.drivetrain && listing.drivetrain !== "fwd" && (
            <span className={`chip ${listing.drivetrain}`}>
              {drivetrainLabel(listing.drivetrain)}
            </span>
          )}
          {listing.transmission === "manual" && <span className="chip man">MANUÁL</span>}
          <AlsoOn duplicates={duplicates} />
          <span className="card-age">{timeAgo(listing.first_seen)}</span>
        </div>
      </div>
    </article>
  );
}

/**
 * Jednorádkové vysvětlení, PROČ je (nebo není) auto deal. Backend teď počítá
 * odhad trhu, důvěru i shodu s bazarem — bez tohohle by to zůstalo skryté a
 * uživatel by musel skóre věřit naslepo.
 */
function WhyDeal({ listing }: { listing: Listing }) {
  if (listing.implausible || listing.expected_price == null) return null;
  const below = pct(listing.pct_below);
  if (below == null || below <= 0) return null;

  const conf =
    listing.confidence >= 0.8 ? "vysoká" : listing.confidence >= 0.55 ? "střední" : "nízká";

  return (
    <div className="why" title={`Jistota odhadu: ${conf} (podle množství srovnatelných aut)`}>
      <span className="why-main">
        −{below} % proti odhadu {czk(listing.expected_price)}
      </span>
      <span className={`why-conf why-conf-${conf === "vysoká" ? "hi" : conf === "střední" ? "mid" : "lo"}`}>
        jistota {conf}
      </span>
      {listing.portal_agreement === "agree" && (
        <span className="why-agree">✓ bazar souhlasí</span>
      )}
    </div>
  );
}

function CarSilhouette() {
  return (
    <svg viewBox="0 0 120 48" width="86" height="34" aria-hidden="true">
      <path
        d="M8 34 C10 26 16 22 26 20 L38 12 C42 9 48 8 58 8 L74 8 C82 8 88 11 93 16 L99 21 C108 22 112 26 112 31 L112 34 L104 34 A8 8 0 0 0 88 34 L44 34 A8 8 0 0 0 28 34 L8 34 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <circle cx="36" cy="34" r="5.5" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <circle cx="96" cy="34" r="5.5" fill="none" stroke="currentColor" strokeWidth="2.5" />
    </svg>
  );
}
