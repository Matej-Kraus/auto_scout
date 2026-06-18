import { useEffect, useMemo, useState } from "react";
import { fetchListings, fetchStatus } from "./api";
import { Drawer } from "./Drawer";
import {
  czk,
  dealTier,
  drivetrainLabel,
  km,
  modelLabel,
  pct,
  sourceLabel,
  timeAgo,
  transmissionLabel,
} from "./format";
import type { Listing, Status } from "./types";

const MODELS = ["bmw_130i", "audi_s3", "golf_gti"];

export function App() {
  const [listings, setListings] = useState<Listing[] | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

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

  const hero = useMemo(
    () => listings?.find((l) => l.deal_score != null) ?? null,
    [listings],
  );
  const rest = useMemo(
    () => (hero ? listings?.filter((l) => l.id !== hero.id) ?? [] : listings ?? []),
    [listings, hero],
  );

  const hotCount = listings?.filter((l) => dealTier(l.deal_score) === "hot").length ?? 0;

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
          {listings == null ? (
            "SCAN…"
          ) : (
            <>
              <b>{listings.length}</b> aktivních ·{" "}
              <b style={{ color: "var(--hot)" }}>{hotCount}</b> hot
              <br />
              {status?.last_run
                ? `naposledy ${timeAgo(status.last_run)}`
                : "hlídám: 130i · S3 · GTI"}
            </>
          )}
        </div>
      </header>

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

      {error && <div className="state">CHYBA: {error}. Běží FastAPI na :8000?</div>}

      {!error && listings == null && (
        <div className="state">
          <div className="spin" />
          SKENUJI TRH…
        </div>
      )}

      {!error && listings != null && listings.length === 0 && (
        <div className="state">
          ŽÁDNÉ AKTIVNÍ INZERÁTY.
          <br />
          Spusť pipeline: <code>python -m app.run_once</code>
        </div>
      )}

      {hero && (
        <HeroCard listing={hero} onOpen={() => setOpenId(hero.id)} />
      )}

      {listings != null && listings.length > 0 && (
        <>
          <div className="section-head">
            <h3>Žebříček dealů</h3>
            <span className="count">SEŘAZENO DLE SKÓRE ▾</span>
          </div>
          <div className="grid">
            {rest.map((l, i) => (
              <DealRow
                key={l.id}
                listing={l}
                rank={i + (hero ? 2 : 1)}
                delay={i * 0.03}
                onOpen={() => setOpenId(l.id)}
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

function HeroCard({ listing, onOpen }: { listing: Listing; onOpen: () => void }) {
  const below = pct(listing.pct_below);
  return (
    <div className="hero" onClick={onOpen} role="button">
      <div>
        <div className="tag">nejlepší deal teď · {sourceLabel(listing.source)}</div>
        <h2>{listing.title}</h2>
        <div className="specs">
          <span>{listing.year ?? "—"}</span>
          <span>{km(listing.mileage_km)}</span>
          <span>{transmissionLabel(listing.transmission)}</span>
          <span>{drivetrainLabel(listing.drivetrain)}</span>
          <span>· {timeAgo(listing.first_seen)}</span>
        </div>
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
  rank,
  delay,
  onOpen,
}: {
  listing: Listing;
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
        <div className="name">{listing.title}</div>
        <div className="meta">
          <span>{sourceLabel(listing.source)}</span>
          <span>{listing.year ?? "—"}</span>
          <span>{km(listing.mileage_km)}</span>
          <span>{timeAgo(listing.first_seen)}</span>
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
