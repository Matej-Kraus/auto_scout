"""Deal scoring: jak dobra je tahle nabidka vuci trhu.

NAVRH (prepis 8/2026). Skore stoji na DVOU NEZAVISLYCH DUKAZECH:

  1. Nas vlastni tržní model — robustni regrese pres nas cross-portal dataset.
  2. Hodnoceni burzy — mobile.de/AutoScout24 pocitaji vlastni ocenu z dat, ktera
     NEMAME (vybava, VIN historie, realne prodejni ceny). Kdyz oba nezavisle
     rikaji "levne", je to mnohem silnejsi signal nez kterykoli sam o sobe.
     Kdyz si odporuji, je to varovani (nase data mohou byt spatne, nebo ma auto
     skrytou vadu) → skore se stahne ke stredu.

Proc log-cena a robustni fit:
  - Cena aut klesa multiplikativne, ne linearne: sleva 10 % znamena totez u
    200k i 400k Kc. Proto model predikuje log(cena), ne cenu.
  - Prvnich 50 tis. km ubere z hodnoty mnohem vic nez km 200→250 tis. → log1p(km).
  - Bourane kusy a nesmyslne ceny (vraky za 30k, omylem pretazene inzeraty)
    tahnou obycejny lstsq fit. Huber IRLS jim da malou vahu misto toho, aby
    kazily predikci vsem ostatnim.

Proc z-skore (a ne jen "% pod cenou"):
  Skupina, kde jsou vsechna auta v ±5 %, je jina nez skupina s rozptylem ±40 %.
  Byt 10 % pod trhem je v prvni mimoradne, ve druhe sum. `pct_below` to nerozlisi,
  z-skore (odchylka delena rozptylem skupiny) ano — a diky tomu jdou prahy
  nastavit jednou a plati napric modely. Tohle je klic ke kalibraci: driv byl
  prah natvrdo 0.18 a oznacoval 20 % vsech aut jako "hot", coz je bezcenne.

Vysledne tieru se prideluje na DVE podminky zaroven (relativni i absolutni):
statisticka vyraznost (z) A soucasne smysluplna uspora v % — aby se "hot"
nedaval ani v skupine, kde nic dobreho neni, ani u kosmetickych rozdilu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app.config import (
    BUDGET_MAX_CZK,
    MIN_SAMPLES_FOR_REGRESSION,
    PORTAL_RATING_WEIGHT,
    SCORE_CONFIDENCE_K,
    TIER_THRESHOLDS,
)
from app.models import Listing

logger = logging.getLogger(__name__)

# Hodnoceni burzy prevedene na "o kolik z-jednotek pod/nad trhem" to znamena.
# Skala je 5stupnova a zhruba symetricka kolem "fair" (= presne na trhu).
_RATING_TO_Z: dict[str, float] = {
    "great": 1.2,
    "good": 0.6,
    "fair": 0.0,
    "elevated": -0.6,
    "high": -1.2,
}

# Bonusy za preference (CLAUDE.md §2). Drzime je ODDELENE od cenoveho skore a
# strope, aby nikdy nedokazaly udelat "dobry deal" z predrazeneho auta —
# odpovidaji na jinou otazku ("chci tohle auto?"), ne "je to levne?".
_MATCH_WEIGHT = 0.35  # jak moc smi preference posunout finalni poradi
_EQUIPMENT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("serviska", ("servisní knížka", "serviska", "scheckheft", "servisni")),
    ("xenon_led", ("xenon", "bixenon", "bi-xenon", " led", "matrix")),
    ("panorama", ("panorama", "pano ", "panorámou", "schiebedach")),
    ("navi", ("navi", "navigace", "navigation")),
    ("performance", ("performance", "akrapovic", "dcc", "dynaudio")),
    ("top_stav", ("top stav", "1. majitel", "1.majitel", "unfallfrei", "garážované", "garazovane")),
)

# --- kontrola duveryhodnosti inzeratu ---
# Bez tohohle filtru jsou "nejlepsi dealy" temer vyhradne vadna data: bouracky,
# vraky na dily, prekliky v cene a chyby v parsovani najezdu (BMW 2011 s "270 km"
# = ve skutecnosti 270 000). Model je pak poslusne vyhodnoti jako zivotni
# prilezitost a zaroven mu rozhodi predikci pro vsechny ostatni ve skupine.
# Proto: podezrele inzeraty se NEPOUZIJI pro fit trhu a dostanou tier "none".

_DAMAGE_HINTS = (
    # DE
    "unfall",
    "schaden",  # pokryje front-/heck-/motor-/getriebe-/hagel-/wasserschaden
    "bastler",
    "schlachtfest",
    "ersatzteil",
    "teilespender",
    "defekt",
    "export",
    "bj-teile",
    # CZ
    "bourane",
    "bourané",
    "bouraný",
    "borany",
    "havarovane",
    "havarované",
    "poskozene",
    "poškozené",
    "poškozeny",
    "na dily",
    "na díly",
    "nepojizdne",
    "nepojízdné",
    "nepojizdny",
    "po nehode",
    "po nehodě",
    "vrak",
    "k renovaci",
    "neni pojizdne",
    "není pojízdné",
)
# Pozor na inzeraty, ktere se vadou CHLUBI opacne: "unfallfrei" (= bez nehody)
# obsahuje "unfall", "scheckheftgepflegt" neobsahuje schaden, ale "schadenfrei" ano.
_DAMAGE_EXCEPTIONS = (
    "unfallfrei",
    "schadenfrei",
    "unfallschadenfrei",
    "kein unfall",
    "nebourane",
    "nebourané",
    "nehavarovane",
    "nehavarované",
)

MIN_PLAUSIBLE_KM_PER_YEAR = 700  # pod tim je najezd u starsiho auta nevěrohodný
MIN_PLAUSIBLE_PRICE_RATIO = 0.35  # pod 35 % medianu skupiny = dily/vrak/preklik


def implausibility_reason(listing: Listing, group_median_price: float | None) -> str | None:
    """Proc inzeratu neverit (nebo None kdyz je v poradku).

    Zamerne konzervativni — radeji pustit dal neco sporneho, nez schovat
    skutecny deal. Chytat ma jen do oci bijici pripady.
    """
    title = (listing.title or "").lower()
    if any(h in title for h in _DAMAGE_HINTS) and not any(e in title for e in _DAMAGE_EXCEPTIONS):
        return "damage"

    # Najezd nesedici na stari = skoro vzdy chyba parsovani ("270 km" u auta z 2011).
    if listing.year is not None and listing.mileage_km is not None:
        age = max(datetime.now().year - listing.year, 0)
        if age >= 3 and listing.mileage_km < age * MIN_PLAUSIBLE_KM_PER_YEAR:
            return "mileage"

    if (
        group_median_price
        and listing.price_czk
        and listing.price_czk < group_median_price * MIN_PLAUSIBLE_PRICE_RATIO
    ):
        return "price"

    return None


@dataclass
class DealScore:
    """Vysledek bodovani jednoho inzeratu."""

    value: float  # finalni skore pro razeni (cenova slozka + omezeny vliv preferenci)
    expected_price: float | None  # predikovana cena trhu
    pct_below: float | None  # kolik % pod ocekavanou cenou (0.22 = 22 % pod) — pro cloveka
    method: str  # "regression" | "median" | "insufficient"
    tier: str = "none"  # "hot" | "good" | "fair" | "none" — kalibrovane, viz _tier_for
    z_score: float | None = None  # o kolik smerodatnych odchylek pod trhem — pro razeni
    confidence: float = 0.0  # 0-1: jak moc datum verime (pocet vzorku + kvalita fitu)
    portal_rating: str | None = None  # hodnoceni burzy, pokud ho dodala
    portal_agreement: str | None = None  # "agree" | "conflict" — shoduje se s nasim modelem?
    match_score: float = 0.0  # 0-1: jak sedi na preference (manual, pohon, km, vybava)
    # "damage" | "mileage" | "price" — proc inzeratu neverime (jinak None).
    # Takovy inzerat nikdy nedostane tier a nepouziva se pro fit trhu.
    implausible: str | None = None
    bonuses: dict[str, float] = field(default_factory=dict)

    @property
    def is_alertable(self) -> bool:
        return self.method != "insufficient" and self.implausible is None


def _mad_sigma(resid: np.ndarray) -> float:
    """Robustni odhad smerodatne odchylky pres MAD (odolny vuci odlehlym hodnotam)."""
    med = float(np.median(resid))
    mad = float(np.median(np.abs(resid - med)))
    return mad * 1.4826  # konstanta prevadi MAD na sigma pro normalni rozdeleni


def _robust_fit(x: np.ndarray, y: np.ndarray, iters: int = 8) -> tuple[np.ndarray, float]:
    """Huber IRLS regrese. Vraci (koeficienty, robustni sigma reziduii).

    Odlehle inzeraty (vraky, prekliky v cene) dostanou malou vahu misto toho,
    aby posunuly predikci vsem ostatnim.
    """
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    huber_k = 1.345  # standardni volba: 95% efektivita na normalnich datech
    for _ in range(iters):
        resid = y - x @ coef
        sigma = _mad_sigma(resid)
        if sigma <= 1e-9:
            break
        u = np.abs(resid / sigma)
        w = np.where(u <= huber_k, 1.0, huber_k / np.maximum(u, 1e-9))
        sw = np.sqrt(w)
        coef, *_ = np.linalg.lstsq(x * sw[:, None], y * sw, rcond=None)

    resid = y - x @ coef
    return coef, _mad_sigma(resid)


def _features(year: int, mileage_km: int, now_year: int) -> list[float]:
    """[1, stari, log1p(km)] — viz docstring modulu, proc prave takhle."""
    age = max(now_year - year, 0)
    return [1.0, float(age), float(np.log1p(max(mileage_km, 0)))]


def _market_model(samples: list[Listing], target: Listing) -> tuple[float | None, float, str]:
    """Predikce ceny pro `target` z dat skupiny. Vraci (expected, sigma_log, method)."""
    now_year = datetime.now().year

    rows = [
        (s.year, s.mileage_km, s.price_czk)
        for s in samples
        if s.year is not None and s.mileage_km is not None and s.price_czk and s.price_czk > 0
    ]

    if (
        len(rows) >= MIN_SAMPLES_FOR_REGRESSION
        and target.year is not None
        and target.mileage_km is not None
    ):
        arr = np.array(rows, dtype=float)
        x = np.array([_features(int(r[0]), int(r[1]), now_year) for r in arr])
        y = np.log(arr[:, 2])
        coef, sigma = _robust_fit(x, y)
        pred_log = float(coef @ np.array(_features(target.year, target.mileage_km, now_year)))
        expected = float(np.exp(pred_log))
        if np.isfinite(expected) and expected > 0:
            # Sigma pod ~2 % je numericky artefakt (skoro identicka data) — dolni
            # zastropovani brani tomu, aby drobny rozdil vyrobil obri z-skore.
            return expected, max(sigma, 0.02), "regression"

    # Fallback: median srovnatelnych (podobny rocnik), az pak globalni median.
    prices = [s.price_czk for s in samples if s.price_czk and s.price_czk > 0]
    if len(prices) < MIN_SAMPLES_FOR_REGRESSION:
        return None, 0.0, "insufficient"

    if target.year is not None:
        near = [
            s.price_czk
            for s in samples
            if s.price_czk and s.year is not None and abs(s.year - target.year) <= 2
        ]
        if len(near) >= MIN_SAMPLES_FOR_REGRESSION:
            prices = near

    logs = np.log(np.array(prices, dtype=float))
    return float(np.exp(np.median(logs))), max(_mad_sigma(logs), 0.05), "median"


def equipment_bonus(title: str | None) -> tuple[float, list[str]]:
    """Bonus za vybavu vyctenou z nazvu inzeratu. Vraci (bonus, nalezene klice)."""
    if not title:
        return 0.0, []
    low = f" {title.lower()} "
    found = [key for key, hints in _EQUIPMENT_HINTS if any(h in low for h in hints)]
    return min(len(found) * 0.01, 0.04), found


def _match(listing: Listing, samples: list[Listing]) -> tuple[float, dict[str, float]]:
    """Jak auto sedi na preference (0-1) + rozpad bonusu. Nezavisle na cene."""
    bonuses: dict[str, float] = {}

    if listing.transmission == "manual":
        bonuses["manual"] = 0.05
    if listing.drivetrain in ("rwd", "awd"):
        bonuses["drivetrain"] = 0.03

    eq_bonus, _found = equipment_bonus(listing.title)
    if eq_bonus > 0:
        bonuses["equipment"] = eq_bonus

    if listing.mileage_km is not None:
        mileages = [s.mileage_km for s in samples if s.mileage_km is not None]
        if len(mileages) >= MIN_SAMPLES_FOR_REGRESSION:
            median_km = float(np.median(mileages))
            if median_km > 0 and listing.mileage_km < median_km:
                ratio = (median_km - listing.mileage_km) / median_km
                bonuses["low_mileage"] = round(min(ratio, 1.0) * 0.05, 4)

    # max mozny soucet je 0.17 → normalizace na 0-1
    return min(sum(bonuses.values()) / 0.17, 1.0), bonuses


def _tier_for(z: float, pct_below: float | None, confidence: float) -> str:
    """Kalibrovane zarazeni. Vyzaduje ZAROVEN statistickou vyraznost i realnou uspornu.

    Duvod dvou podminek: samotne z by oznacilo "nejlepsi z paté" i ve skupine,
    kde nic dobreho neni; samotne % zase neodlisi tesny trh od rozhazeneho.
    """
    if pct_below is None or confidence < 0.35:
        return "none"
    for tier, (z_min, pct_min) in TIER_THRESHOLDS:
        if z >= z_min and pct_below >= pct_min:
            return tier
    return "none"


def score_listing(listing: Listing, samples: list[Listing]) -> DealScore:
    """Spocita deal skore inzeratu vuci datasetu `samples` (stejny model+generace)."""
    priced = [s for s in samples if s.price_czk]
    group_median = float(np.median([s.price_czk for s in priced])) if priced else None

    # Vraky/prekliky/chybne km ven z trzniho modelu — jinak kazi predikci vsem.
    usable = [s for s in priced if implausibility_reason(s, group_median) is None]
    if len(usable) < MIN_SAMPLES_FOR_REGRESSION:
        usable = priced  # radeji sirsi (spinavy) vzorek nez zadny model

    match_score, bonuses = _match(listing, usable)
    implausible = implausibility_reason(listing, group_median)

    expected, sigma, method = _market_model(usable, listing)

    if expected is None or not listing.price_czk:
        return DealScore(
            value=round(_MATCH_WEIGHT * match_score, 4),
            tier="none",
            expected_price=None,
            pct_below=None,
            z_score=None,
            confidence=0.0,
            method="insufficient",
            portal_rating=listing.price_rating,
            portal_agreement=None,
            match_score=round(match_score, 4),
            implausible=implausible,
            bonuses=bonuses,
        )

    pct_below = (expected - listing.price_czk) / expected
    z_model = float((np.log(expected) - np.log(listing.price_czk)) / sigma)

    # --- fuze s hodnocenim burzy (druhy nezavisly nazor) ---
    portal_rating = listing.price_rating
    z_portal = _RATING_TO_Z.get(portal_rating) if portal_rating else None
    agreement: str | None = None

    if z_portal is not None:
        # OMEZENY POSUN, ne vazeny prumer. Skala burzy je hruba a shora omezena
        # ("great" je maximum, co umi rict), takze prumerovanim by kazdy opravdu
        # vyjimecny nalez (nas z = 4+) stahla dolu ke svemu stropu — presne ta
        # auta, kvuli kterym to cele stavime. Aditivni posun naopak funguje
        # spravne ve vsech kombinacich znamenek: potvrzeni pomuze, rozpor uskodi,
        # a nikdy neprebije vlastni mereni.
        w_portal = PORTAL_RATING_WEIGHT if method == "regression" else PORTAL_RATING_WEIGHT * 1.6
        z_combined = z_model + w_portal * z_portal
        # "conflict"/"agree" jen pri jasnem stanovisku obou stran
        if z_model >= 0.5 and z_portal <= -0.6:
            agreement = "conflict"
        elif z_model <= -0.5 and z_portal >= 0.6:
            agreement = "conflict"
        elif (z_model >= 0.5 and z_portal >= 0.6) or (z_model <= -0.5 and z_portal <= -0.6):
            agreement = "agree"
    else:
        z_combined = z_model

    # --- duvera: malo dat nesmi vyrobit "hot deal" ---
    n = len(usable)
    conf = n / (n + SCORE_CONFIDENCE_K)
    if method != "regression":
        conf *= 0.6  # medianovy fallback nezna vliv roku/km na cenu
    if listing.year is None or listing.mileage_km is None:
        conf *= 0.7  # u auta bez roku/km je i predikce slabsi
    if agreement == "agree":
        conf = min(conf * 1.15, 1.0)  # dva nezavisle zdroje se shoduji
    elif agreement == "conflict":
        conf *= 0.7

    z_final = z_combined * conf
    # Nedůveryhodny inzerat nikdy nedostane tier — jinak by vraky a prekliky
    # v cene obsadily cely zebricek "nejlepsich dealu" (overeno na realnych datech).
    tier = "none" if implausible else _tier_for(z_final, pct_below, conf)

    # Finalni hodnota pro razeni: cenova slozka + omezeny prispevek preferenci.
    value = z_final + _MATCH_WEIGHT * match_score
    if implausible:
        value = min(value, 0.0)  # at neplavou nahore v serazenem seznamu

    return DealScore(
        value=round(value, 4),
        tier=tier,
        expected_price=round(expected, 0),
        pct_below=round(pct_below, 4),
        z_score=round(z_final, 4),
        confidence=round(conf, 3),
        method=method,
        portal_rating=portal_rating,
        portal_agreement=agreement,
        match_score=round(match_score, 4),
        implausible=implausible,
        bonuses=bonuses,
    )


def in_budget(listing: Listing) -> bool:
    """Je inzerat v rozpoctu (horni hranice)? Pro fallback 'novy v rozpoctu'."""
    return bool(listing.price_czk) and listing.price_czk <= BUDGET_MAX_CZK
