// Export vyfiltrovaných aut do Markdownu — soubor je určený k předání AI
// asistentovi ("mrkni na to a pomoz mi vybrat"), takže musí být čitelný sám o
// sobě: bez odkazu zpět do appky, s vysvětlením, co která hodnota znamená.

import { czk, fuelLabel, km, pct, priceRatingLabel, sourceLabel, transmissionLabel } from "./format";
import type { Cluster } from "./search";
import type { Listing } from "./types";

function fmtDate(d: Date): string {
  return d.toLocaleString("cs-CZ", { dateStyle: "short", timeStyle: "short" });
}

/** Průměrný roční nájezd — rychlý ukazatel, jestli auto stálo nebo jezdilo dálnice. */
function kmPerYear(l: Listing): number | null {
  if (l.year == null || l.mileage_km == null) return null;
  const age = Math.max(new Date().getFullYear() - l.year, 1);
  return Math.round(l.mileage_km / age);
}

/** Jak dlouho inzerát visí — dlouho visící auto bývá předražené nebo má vadu. */
function daysListed(l: Listing): string {
  const days = Math.floor((Date.now() - new Date(l.first_seen).getTime()) / 86_400_000);
  if (days < 1) return "nově naskočil (dnes)";
  if (days === 1) return "1 den";
  return `${days} dní`;
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
  ];

  // km/rok se v zadani vyslovne posuzuje — spocitat to tady je spolehlivejsi,
  // nez to nechat na odhadu z hlavy.
  const perYear = kmPerYear(l);
  if (perYear != null) {
    lines.push(`- **Nájezd na rok:** ~${new Intl.NumberFormat("cs-CZ").format(perYear)} km/rok`);
  }

  lines.push(
    `- **Hodnocení:** ${dealLine(l)}`,
    `- **Zdroj:** ${sourceLabel(l.source)}`,
    `- **Inzerát je v nabídce:** ${daysListed(l)}`,
    `- **Odkaz:** ${l.url}`,
  );
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
    "---",
    "",
    "## ZADÁNÍ",
    "",
    "Pomoz mi vybrat, které z těchhle aut mám jet vidět. Postupuj takhle:",
    "",
    "### 1) Projdi KAŽDÉ auto zvlášť",
    "",
    "U každého napiš 2–4 věty a v nich:",
    "",
    "- **Je cena opravdu dobrá?** Nespoléhej jen na uvedené „% pod odhadem“ —",
    "  posuď sám, jestli cena sedí na ročník, nájezd, výbavu a motorizaci.",
    "  Podezřele levné auto má obvykle důvod; napiš, jaký důvod tipuješ.",
    "- **Nájezd vs. stáří.** Spočítej km/rok. Nad ~25 tis. km/rok je hodně",
    "  (často dálnice = spíš dobré pro motor), pod ~8 tis. km/rok taky varování",
    "  (stání, koroze, ztvrdlé gumy).",
    "- **Co v inzerátu chybí.** Není uvedená převodovka, výkon, servisní historie?",
    "  Napiš, co je potřeba doptat.",
    "- **Varovné signály v názvu.** Import, „bez TP“, nesedící výbava k modelu,",
    "  přeprodejce, podezřele obecný popis.",
    "- **Jak dlouho inzerát visí.** Dlouho neprodané auto bývá předražené nebo",
    "  má vadu, kterou kupci vidí na fotkách. Naopak čerstvý dobrý kus mizí rychle,",
    "  takže u něj má smysl jednat hned.",
    "",
    "### 2) Přidej znalost konkrétního modelu",
    "",
    "U každého auta zmiň **známé bolesti té konkrétní generace a motorizace** —",
    "co se u ní typicky láme, v jakém nájezdu, a kolik oprava stojí. Tohle je",
    "nejcennější část, data z inzerátů to neobsahují.",
    "",
    "### 3) Seřaď a doporuč",
    "",
    "- Vyber **TOP 3** a zdůvodni pořadí. Nemusí to být nejlevnější ani nejvíc",
    "  „pod trhem“ — chci nejlepší poměr cena/stav/riziko.",
    "- Napiš **jasného vítěze** a proč právě on.",
    "- Zvlášť uveď auta, kterým bych se **vyhnul**, a proč.",
    "",
    "### 4) Co dělat dál",
    "",
    "K vítězi (a případně dalším dvěma) přidej:",
    "- **na co se zeptat prodejce** ještě před cestou (3–5 konkrétních otázek),",
    "- **co zkontrolovat při prohlídce** u tohohle konkrétního modelu,",
    "- **jakou cenu zkusit vyjednat** a s jakým argumentem.",
    "",
    "Buď konkrétní a přímý. Když je nabídka slabá, napiš rovnou, že nestojí za",
    "cestu, místo hledání kompromisu.",
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
