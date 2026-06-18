import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchListing } from "./api";
import {
  czk,
  dealTier,
  drivetrainLabel,
  km,
  pct,
  sourceLabel,
  transmissionLabel,
} from "./format";
import type { ListingDetail } from "./types";

export function Drawer({ id, onClose }: { id: number; onClose: () => void }) {
  const [data, setData] = useState<ListingDetail | null>(null);

  useEffect(() => {
    setData(null);
    fetchListing(id).then(setData).catch(() => onClose());
  }, [id, onClose]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const chartData =
    data?.price_history.map((p) => ({
      t: new Date(p.seen_at).toLocaleDateString("cs-CZ", { day: "2-digit", month: "2-digit" }),
      price: p.price_czk,
    })) ?? [];

  const below = pct(data?.pct_below ?? null);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer">
        <button className="close" onClick={onClose} aria-label="zavřít">
          ✕
        </button>
        {!data ? (
          <div className="state">
            <div className="spin" />
            NAČÍTÁM TELEMETRII…
          </div>
        ) : (
          <>
            <div className="src">{sourceLabel(data.source)}</div>
            <h2>{data.title}</h2>

            <div className="statrow">
              <div className="stat">
                <div className="k">Cena</div>
                <div className="v">{czk(data.price_czk)}</div>
              </div>
              <div className="stat">
                <div className="k">Rok</div>
                <div className="v">{data.year ?? "—"}</div>
              </div>
              <div className="stat">
                <div className="k">Nájezd</div>
                <div className="v">{km(data.mileage_km)}</div>
              </div>
              <div className="stat">
                <div className="k">Převod.</div>
                <div className="v">{transmissionLabel(data.transmission)}</div>
              </div>
            </div>

            {data.expected_price != null && (
              <div className="statrow" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
                <div className="stat">
                  <div className="k">Odhad trhu</div>
                  <div className="v">{czk(data.expected_price)}</div>
                </div>
                <div className="stat">
                  <div className="k">Pod trhem</div>
                  <div className="v" style={{ color: "var(--good)" }}>
                    {below != null && below > 0 ? `${below} %` : "—"}
                  </div>
                </div>
                <div className="stat">
                  <div className="k">Pohon</div>
                  <div className="v">{drivetrainLabel(data.drivetrain)}</div>
                </div>
              </div>
            )}

            <div className="chart-wrap">
              <div className="ch-title">Vývoj ceny · {chartData.length} bodů</div>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={chartData} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#ff6a17" stopOpacity={0.5} />
                      <stop offset="100%" stopColor="#ff6a17" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#232c35" strokeDasharray="2 4" vertical={false} />
                  <XAxis
                    dataKey="t"
                    stroke="#59636d"
                    tick={{ fontSize: 10, fontFamily: "Spline Sans Mono" }}
                  />
                  <YAxis
                    stroke="#59636d"
                    tick={{ fontSize: 10, fontFamily: "Spline Sans Mono" }}
                    width={54}
                    tickFormatter={(v) => `${Math.round(v / 1000)}k`}
                    domain={["dataMin - 10000", "dataMax + 10000"]}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#0a0c0f",
                      border: "1px solid #303d49",
                      borderRadius: 8,
                      fontFamily: "Spline Sans Mono",
                      fontSize: 12,
                    }}
                    labelStyle={{ color: "#8b97a3" }}
                    formatter={(v: number) => [czk(v), "cena"]}
                  />
                  <Area
                    type="stepAfter"
                    dataKey="price"
                    stroke="#ff6a17"
                    strokeWidth={2}
                    fill="url(#g)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            <a className="visit" href={data.url} target="_blank" rel="noreferrer">
              Otevřít inzerát ↗
            </a>
            <p
              style={{
                fontFamily: "Spline Sans Mono",
                fontSize: 11,
                color: "var(--text-faint)",
                letterSpacing: "0.08em",
                textAlign: "center",
                marginTop: 14,
              }}
            >
              tier: {dealTier(data.deal_score).toUpperCase()} · metoda:{" "}
              {data.score_method ?? "—"}
            </p>
          </>
        )}
      </aside>
    </>
  );
}
