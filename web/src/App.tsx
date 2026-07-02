import { useEffect, useMemo, useState } from "react";
import { fetchListings, fetchStatus } from "./api";
import { Drawer } from "./Drawer";
import {
  czk,
  dealTier,
  drivetrainLabel,
  fuelLabel,
  km,
  modelLabel,
  pct,
  sourceLabel,
  timeAgo,
  transmissionLabel,
} from "./format";
import {
  applySearch,
  clusterListings,
  type Cluster,
  EMPTY_SEARCH,
  isSearchActive,
  type SearchState,
} from "./search";
import type { Listing, Status } from "./types";

const MODELS = ["bmw_130i", "audi_s3", "golf_gti"];
const PRICE_STEPS = [200_000, 250_000, 300_000, 400_000];
const FUELS = ["petrol", "diesel", "hybrid", "electric"];

function yearOptions(min: number, max: number): number[] {
  const out: number[] = [];
  for (let y = max; y >= min; y--) out.push(y);
  return out;
}

export function App() {
  const [listings, setListings] = useState<Listing[] | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [search, setSearch] = useState<SearchState>(EMPTY_SEARCH);

  useEffect(() => {
    setListings(null);
    setError(null);
    fetchListings({ active: true, model: filter ?? undefined })
      .then(setListings)
      .catch((e) => setError(String(e)));
  }, [filter]);

  useEffect(() => {
    fetchStatus().then(setStatus).catch(() => {});
  }, []);

  // Zdroje + paliva pro filtr (dynamicky z dat).
  const sources = useMemo(
    () => Array.from(new Set((listings ?? []).map((l) => l.source))).sort(),
    [listings],
  );
  const fuels = useMemo(
    () => FUELS.filter((f) => (listings ?? []).some((l) => l.fuel_type === f)),
    [listings],
  );
  const years = useMemo(() => {
    const ys = (listings ?? []).map((l) => l.year).filter((y): y is number => y != null);
    return ys.length ? { min: Math.min(...ys), max: Math.max(...ys) } : null;
  }, [listings]);

  // Vyhledávání + filtry běží client-side nad staženými inzeráty (okamžitá odezva).
  const matched = useMemo(
    () => (listings ? applySearch(listings, search) : null),
    [listings, search],
  );

  // Sloučení stejného auta z víc bazarů (dedupe) → clustery seřazené podle skóre.
  const clusters = useMemo<Cluster[] | null>(() => {
    if (matched == null) return null;
    if (!search.dedupe) return matched.map((l) => ({ primary: l, duplicates: [] }));
    return clusterListings(matched);
  }, [matched, search.dedupe]);

  const heroCluster = useMemo(
    () => clusters?.find((c) => c.primary.deal_score != null) ?? null,
    [clusters],
  );
  const restClusters = useMemo(
    () =>
      heroCluster
        ? clusters?.filter((c) => c.primary.id !== heroCluster.primary.id) ?? []
        : clusters ?? [],
    [clusters, heroCluster],
  );

  const hotCount =
    clusters?.filter((c) => dealTier(c.primary.deal_score) === "hot").length ?? 0;
  const searchActive = isSearchActive(search);

  return (
    <div className="shell">
      <header className="masthead">
        <div className="brand">
          <div className="brand-mark">DH</div>
          <div>
            <h1>
              Deal <span>Hunter</span>
            </h1>
            <div className="sub">telemetrie ojetých · cz + de</div>
          </div>
        </div>
        <div className="readout">
          {matched == null ? (
            "SCAN…"
          ) : (
            <>
              <b>{clusters?.length ?? matched.length}</b> aut ·{" "}
              <b style={{ color: "var(--hot)" }}>{hotCount}</b> hot
              <br />
              {status?.last_run
                ? `naposledy ${timeAgo(status.last_run)}`
                : "hlídám: 130i · S3 · GTI"}
            </>
          )}
        </div>
      </header>

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

      <div className="controls">
        <span className="lbl">Garáž</span>
        <button
          className={`pill ${filter === null ? "active" : ""}`}
          onClick={() => setFilter(null)}
        >
          Vše
        </button>
        {MODELS.map((m) => (
          <button
            key={m}
            className={`pill ${filter === m ? "active" : ""}`}
            onClick={() => setFilter(m)}
          >
            {modelLabel(m)}
          </button>
        ))}
      </div>

      <div className="controls">
        <span className="lbl">Filtr</span>
        <button
          className={`pill ${search.manualOnly ? "active" : ""}`}
          onClick={() => setSearch((s) => ({ ...s, manualOnly: !s.manualOnly }))}
        >
          Jen manuál
        </button>
        {PRICE_STEPS.map((p) => (
          <button
            key={p}
            className={`pill ${search.maxPrice === p ? "active" : ""}`}
            onClick={() =>
              setSearch((s) => ({ ...s, maxPrice: s.maxPrice === p ? null : p }))
            }
          >
            do {Math.round(p / 1000)}k
          </button>
        ))}
        {sources.length > 1 &&
          sources.map((src) => (
            <button
              key={src}
              className={`pill ${search.source === src ? "active" : ""}`}
              onClick={() =>
                setSearch((s) => ({ ...s, source: s.source === src ? null : src }))
              }
            >
              {sourceLabel(src)}
            </button>
          ))}
      </div>

      {(fuels.length > 0 || years) && (
        <div className="controls">
          <span className="lbl">Palivo · rok</span>
          {fuels.map((f) => (
            <button
              key={f}
              className={`pill ${search.fuel === f ? "active" : ""}`}
              onClick={() => setSearch((s) => ({ ...s, fuel: s.fuel === f ? null : f }))}
            >
              {fuelLabel(f)}
            </button>
          ))}
          {years && (
            <>
              <select
                className="yearsel"
                value={search.yearFrom ?? ""}
                onChange={(e) =>
                  setSearch((s) => ({
                    ...s,
                    yearFrom: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              >
                <option value="">rok od</option>
                {yearOptions(years.min, years.max).map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
              <select
                className="yearsel"
                value={search.yearTo ?? ""}
                onChange={(e) =>
                  setSearch((s) => ({
                    ...s,
                    yearTo: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              >
                <option value="">rok do</option>
                {yearOptions(years.min, years.max).map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </>
          )}
          <button
            className={`pill ${search.dedupe ? "active" : ""}`}
            title="Sloučit stejné auto nabízené na víc bazarech do jednoho"
            onClick={() => setSearch((s) => ({ ...s, dedupe: !s.dedupe }))}
          >
            ⛓ Sloučit duplicity
          </button>
        </div>
      )}

      {error && <div className="state">CHYBA: {error}. Běží FastAPI na :8000?</div>}

      {!error && listings == null && (
        <div className="state">
          <div className="spin" />
          SKENUJI TRH…
        </div>
      )}

      {!error && matched != null && matched.length === 0 && (
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
              Spusť pipeline: <code>python -m app.run_once</code>
            </>
          )}
        </div>
      )}

      {heroCluster && (
        <HeroCard
          listing={heroCluster.primary}
          duplicates={heroCluster.duplicates}
          onOpen={() => setOpenId(heroCluster.primary.id)}
        />
      )}

      {clusters != null && clusters.length > 0 && (
        <>
          <div className="section-head">
            <h3>{searchActive ? "Výsledky hledání" : "Žebříček dealů"}</h3>
            <span className="count">SEŘAZENO DLE SKÓRE ▾</span>
          </div>
          <div className="grid">
            {restClusters.map((c, i) => (
              <DealRow
                key={c.primary.id}
                listing={c.primary}
                duplicates={c.duplicates}
                rank={i + (heroCluster ? 2 : 1)}
                delay={i * 0.03}
                onOpen={() => setOpenId(c.primary.id)}
              />
            ))}
          </div>
        </>
      )}

      {openId != null && <Drawer id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function Gauge({ score }: { score: number }) {
  const p = Math.max(0, Math.min(1, score / 0.3)); // 30 % = plný gauge
  const r = 64;
  const c = Math.PI * r; // půlkruh
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
      <div className="val">{Math.round(score * 100)}</div>
      <div className="unit">deal index</div>
    </div>
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

function HeroCard({
  listing,
  duplicates,
  onOpen,
}: {
  listing: Listing;
  duplicates: Listing[];
  onOpen: () => void;
}) {
  const below = pct(listing.pct_below);
  return (
    <div className="hero" onClick={onOpen} role="button">
      <div>
        <div className="tag">nejlepší deal teď · {sourceLabel(listing.source)}</div>
        {listing.image_url && (
          <img className="hero-thumb" src={listing.image_url} alt="" loading="lazy" />
        )}
        <h2>{listing.title}</h2>
        <div className="specs">
          <span>{listing.year ?? "—"}</span>
          <span>{km(listing.mileage_km)}</span>
          <span>{transmissionLabel(listing.transmission)}</span>
          <span>{drivetrainLabel(listing.drivetrain)}</span>
          <span>{fuelLabel(listing.fuel_type)}</span>
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
        <a className="cta" href={listing.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
          Otevřít inzerát ↗
        </a>
      </div>
      {listing.deal_score != null && <Gauge score={listing.deal_score} />}
    </div>
  );
}

function DealRow({
  listing,
  duplicates,
  rank,
  delay,
  onOpen,
}: {
  listing: Listing;
  duplicates: Listing[];
  rank: number;
  delay: number;
  onOpen: () => void;
}) {
  const tier = dealTier(listing.deal_score);
  const below = pct(listing.pct_below);
  return (
    <div
      className={`row tier-${tier}`}
      style={{ animationDelay: `${delay}s` }}
      onClick={onOpen}
      role="button"
    >
      <div className="rank">{String(rank).padStart(2, "0")}</div>
      <div className="car">
        {listing.image_url ? (
          <img className="thumb" src={listing.image_url} alt="" loading="lazy" />
        ) : (
          <div className="thumb thumb-empty">—</div>
        )}
        <div className="car-text">
          <div className="name">{listing.title}</div>
          <div className="meta">
            <span>{sourceLabel(listing.source)}</span>
            <span>{listing.year ?? "—"}</span>
            <span>{km(listing.mileage_km)}</span>
            {listing.fuel_type && <span>{fuelLabel(listing.fuel_type)}</span>}
            <span>{timeAgo(listing.first_seen)}</span>
          </div>
          <AlsoOn duplicates={duplicates} />
        </div>
      </div>
      <div className="tags">
        {listing.transmission === "manual" && <span className="chip man">MANUÁL</span>}
        {listing.drivetrain && listing.drivetrain !== "fwd" && (
          <span className={`chip ${listing.drivetrain}`}>{drivetrainLabel(listing.drivetrain)}</span>
        )}
      </div>
      <div className="col-num col-price">
        <div className="price-num">{czk(listing.price_czk)}</div>
        {listing.expected_price != null && (
          <div className="exp-num">odhad {czk(listing.expected_price)}</div>
        )}
      </div>
      <div className="col-num col-exp">
        {below != null && below > 0 ? (
          <div className="price-num" style={{ color: "var(--good)" }}>
            −{below} %
          </div>
        ) : (
          <div className="exp-num">v ceně</div>
        )}
      </div>
      <div className={`scorecell tier-${tier}`}>
        <div className="big">
          {listing.deal_score != null ? Math.round(listing.deal_score * 100) : "—"}
        </div>
        <div className="sub">{listing.score_method === "median" ? "medián" : "index"}</div>
      </div>
    </div>
  );
}
