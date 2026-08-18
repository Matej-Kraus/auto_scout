// Export vyfiltrovaných aut do Markdownu — soubor je určený k předání AI
// asistentovi ("mrkni na to a pomoz mi vybrat"), takže musí být čitelný sám o
// sobě: bez odkazu zpět do appky, s vysvětlením, co která hodnota znamená.

import { czk, fuelLabel, km, pct, priceRatingLabel, sourceLabel, transmissionLabel } from "./format";
import type { Cluster } from "./search";
import type { Listing } from "./types";

function fmtDate(d: Date): string {
  return d.toLocaleString("cs-CZ", { dateStyle: "short", timeStyle: "short" });
}

/** Řádek s tím, co dělá auto zajímavým — jen hodnoty, které opravdu máme. */
function dealLine(l: Listing): string {
  if (l.expected_price == null) return "cena vs. trh: neznámé (málo srovnatelných aut)";
  const below = pct(l.pct_below);
  const dir = below != null && below > 0 ? `${below} % POD` : `${Math.abs(below ?? 0)} % NAD`;
  const conf =
    l.confidence >= 0.8 ? "vysoká" : l.confidence >= 0.55 ? "střední" : "nízká";
  const parts = [
    `${dir} odhadem trhu (odhad ${czk(l.expected_price)})`,
    `jistota odhadu ${conf}`,
  ];
  if (l.price_rating) {
    const agree =
      l.portal_agreement === "agree"
        ? ", shoduje se s naším odhadem"
        : l.portal_agreement === "conflict"
          ? ", ROZPOR s naším odhadem"
          : "";
    parts.push(`bazar hodnotí jako "${priceRatingLabel(l.price_rating)}"${agree}`);
  }
  return parts.join(" · ");
}

function carBlock(l: Listing, rank: number, duplicates: Listing[]): string {
  const specs = [
    l.year ?? "rok neznámý",
    km(l.mileage_km),
    l.power_kw != null ? `${l.power_kw} kW` : null,
    transmissionLabel(l.transmission),
    l.fuel_type ? fuelLabel(l.fuel_type) : null,
    l.drivetrain ? l.drivetrain.toUpperCase() : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const lines = [
    `### ${rank}. ${l.title}`,
    "",
    `- **Cena:** ${czk(l.price_czk)}`,
    `- **Parametry:** ${specs}`,
    `- **Hodnocení:** ${dealLine(l)}`,
    `- **Zdroj:** ${sourceLabel(l.source)}`,
    `- **Odkaz:** ${l.url}`,
  ];
  if (duplicates.length > 0) {
    lines.push(
      `- **Stejné auto i na:** ${duplicates.map((d) => `${sourceLabel(d.source)} (${d.url})`).join(", ")}`,
    );
  }
  return lines.join("\n");
}

/** Sestaví celý Markdown dokument. `filterNote` popisuje, co bylo vyfiltrováno. */
export function buildExport(clusters: Cluster[], filterNote: string): string {
  const now = new Date();
  const head = [
    "# Výběr ojetých aut k posouzení",
    "",
    `Exportováno ${fmtDate(now)} · ${clusters.length} aut`,
    `Filtr: ${filterNote}`,
    "",
    "## Kontext pro posouzení",
    "",
    "Tohle je výběr z hlídače inzerátů, který sleduje Sauto, Sbazar, AutoScout24,",
    "Kleinanzeigen a mobile.de. U každého auta je porovnání se **skutečnou tržní",
    "cenou** — odhad se počítá regresí (cena podle roku a nájezdu) přes všechna",
    "srovnatelná auta téhož modelu a generace, ne podle ceníku.",
    "",
    "Co znamenají hodnoty:",
    "- **% pod/nad odhadem trhu** — hlavní ukazatel výhodnosti.",
    "- **jistota odhadu** — kolik srovnatelných aut model měl; u nízké ber % s rezervou.",
    '- **hodnocení bazaru** — vlastní ocenění burzy (staví i na výbavě a historii VIN,',
    "  které nemáme). Shoda s naším odhadem = silnější signál, rozpor = opatrnost.",
    "",
    "Bouraná auta, vraky na díly a inzeráty s nesmyslnými údaji jsou už odfiltrované.",
    "Auta s vysokým nájezdem mají skóre záměrně sníženo (zbývá jim míň života).",
    "",
    "**S čím potřebuju pomoct:** projdi nabídku a řekni, které kusy stojí za",
    "obhlídku a na co si u nich dát pozor. Zajímá mě poměr cena/stav, ne jen",
    "nejnižší číslo.",
    "",
    "---",
    "",
    "## Auta",
    "",
  ].join("\n");

  const body = clusters.map((c, i) => carBlock(c.primary, i + 1, c.duplicates)).join("\n\n");
  return `${head}${body}\n`;
}

/** Spustí stažení souboru v prohlížeči. */
export function downloadExport(markdown: string, count: number): void {
  const stamp = new Date().toISOString().slice(0, 10);
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `auta-${stamp}-${count}ks.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
