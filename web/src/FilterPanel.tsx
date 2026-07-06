import { bodyLabel, fuelLabel } from "./format";
import { EMPTY_SEARCH, isSearchActive, type SearchState } from "./search";
import type { Listing } from "./types";

const TRANSMISSIONS = [
  { value: "manual", label: "Manuál" },
  { value: "auto", label: "Automat" },
];
const DRIVETRAINS = [
  { value: "fwd", label: "Přední" },
  { value: "rwd", label: "Zadní" },
  { value: "awd", label: "4×4" },
];
const FUELS = ["petrol", "diesel", "hybrid", "electric", "lpg", "cng"];
const BODIES = ["hatchback", "kombi", "sedan", "suv", "coupe", "cabrio", "mpv"];

type Patch = Partial<SearchState>;

/** Přehledný filtrační panel (styl mobile.de): rozsahy od–do + výběrové chipy. */
export function FilterPanel({
  search,
  setSearch,
  listings,
  onClose,
}: {
  search: SearchState;
  setSearch: (fn: (s: SearchState) => SearchState) => void;
  listings: Listing[];
  onClose: () => void;
}) {
  const patch = (p: Patch) => setSearch((s) => ({ ...s, ...p }));
  const has = (pred: (l: Listing) => boolean) => listings.some(pred);

  // jen hodnoty, které v datech reálně jsou
  const fuels = FUELS.filter((f) => has((l) => l.fuel_type === f));
  const bodies = BODIES.filter((b) => has((l) => l.body_type === b));
  const sources = Array.from(new Set(listings.map((l) => l.source))).sort();
  const hasKw = has((l) => l.power_kw != null);
  const hasDrivetrain = has((l) => l.drivetrain != null);

  return (
    <div className="fpanel">
      <div className="fpanel-head">
        <h3>Filtry</h3>
        {isSearchActive(search) && (
          <button className="fpanel-reset" onClick={() => patch(EMPTY_SEARCH)}>
            ✕ Zrušit vše
          </button>
        )}
        <button className="fpanel-close" onClick={onClose} aria-label="zavřít filtry">
          ✕
        </button>
      </div>

      <div className="fpanel-body">
        <RangeRow
          label="Cena"
          unit="Kč"
          step={10000}
          from={search.priceFrom}
          to={search.priceTo}
          onFrom={(v) => patch({ priceFrom: v })}
          onTo={(v) => patch({ priceTo: v })}
        />
        <RangeRow
          label="Rok"
          from={search.yearFrom}
          to={search.yearTo}
          onFrom={(v) => patch({ yearFrom: v })}
          onTo={(v) => patch({ yearTo: v })}
        />
        <RangeRow
          label="Nájezd"
          unit="km"
          step={10000}
          from={search.kmFrom}
          to={search.kmTo}
          onFrom={(v) => patch({ kmFrom: v })}
          onTo={(v) => patch({ kmTo: v })}
        />
        {hasKw && (
          <RangeRow
            label="Výkon"
            unit="kW"
            from={search.kwFrom}
            to={search.kwTo}
            onFrom={(v) => patch({ kwFrom: v })}
            onTo={(v) => patch({ kwTo: v })}
          />
        )}

        <ChipRow
          label="Převodovka"
          options={TRANSMISSIONS}
          value={search.transmission}
          onPick={(v) => patch({ transmission: v })}
        />
        {hasDrivetrain && (
          <ChipRow
            label="Pohon"
            options={DRIVETRAINS}
            value={search.drivetrain}
            onPick={(v) => patch({ drivetrain: v })}
          />
        )}
        {fuels.length > 0 && (
          <ChipRow
            label="Palivo"
            options={fuels.map((f) => ({ value: f, label: fuelLabel(f) }))}
            value={search.fuel}
            onPick={(v) => patch({ fuel: v })}
          />
        )}
        {bodies.length > 0 && (
          <ChipRow
            label="Karoserie"
            options={bodies.map((b) => ({ value: b, label: bodyLabel(b) }))}
            value={search.body}
            onPick={(v) => patch({ body: v })}
          />
        )}
        {sources.length > 1 && (
          <ChipRow
            label="Bazar"
            options={sources.map((s) => ({ value: s, label: srcLabel(s) }))}
            value={search.source}
            onPick={(v) => patch({ source: v })}
          />
        )}
      </div>
    </div>
  );
}

function RangeRow({
  label,
  unit,
  step,
  from,
  to,
  onFrom,
  onTo,
}: {
  label: string;
  unit?: string;
  step?: number;
  from: number | null;
  to: number | null;
  onFrom: (v: number | null) => void;
  onTo: (v: number | null) => void;
}) {
  const parse = (s: string) => (s.trim() === "" ? null : Number(s.replace(/\s/g, "")));
  return (
    <div className="frow">
      <span className="frow-label">{label}</span>
      <div className="frow-inputs">
        <input
          className="frow-num"
          inputMode="numeric"
          placeholder="od"
          step={step}
          value={from ?? ""}
          onChange={(e) => onFrom(parse(e.target.value))}
        />
        <span className="frow-dash">–</span>
        <input
          className="frow-num"
          inputMode="numeric"
          placeholder="do"
          step={step}
          value={to ?? ""}
          onChange={(e) => onTo(parse(e.target.value))}
        />
        {unit && <span className="frow-unit">{unit}</span>}
      </div>
    </div>
  );
}

function ChipRow({
  label,
  options,
  value,
  onPick,
}: {
  label: string;
  options: { value: string; label: string }[];
  value: string | null;
  onPick: (v: string | null) => void;
}) {
  return (
    <div className="frow">
      <span className="frow-label">{label}</span>
      <div className="frow-chips">
        {options.map((o) => (
          <button
            key={o.value}
            className={`fchip ${value === o.value ? "on" : ""}`}
            onClick={() => onPick(value === o.value ? null : o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function srcLabel(s: string): string {
  return (
    { sauto: "Sauto", sbazar: "Sbazar", autoscout24: "AutoScout24", kleinanzeigen: "Kleinanz.", mobilede: "Mobile.de" }[
      s
    ] ?? s
  );
}
