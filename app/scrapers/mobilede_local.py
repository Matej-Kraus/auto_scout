"""Mobile.de scraper pro LOKÁLNÍ běh (rezidenční IP) přes Scrapling StealthyFetcher.

Mobile.de chrání Akamai: síťová/TLS vrstva blokuje Chromium okamžitě (403 bez
JS challenge), zpevněný Firefox (Camoufox) ji projde a dostane se k
behaviorální JS výzvě, kterou vyřeší jako reálný prohlížeč (ověřeno 8/2026).
Proto vyžaduje `scrapling[fetchers]==0.3.12` — poslední verze, jejíž
StealthyFetcher ještě jede na Camoufoxu; od 0.3.13 přešli na patchright
(patchnuté Chromium), které tu selže stejně jako čistý Playwright Chromium.
Diagnostika obou slepých uliček (Chromium i curl_cffi bez JS): `scripts/mobilede_probe.py`.

  - NEběží v hodinovém cronu; spouští ho `scripts/run_daily_local.py`
    (launchd na uživatelově Macu, 1× denně, spolu s ostatními portály) a
    zapisuje do stejné DB.
  - Jeden požadavek na watch + dlouhé pauzy; při challenge měkce přeskočí
    (žádný failure alert — občasná blokace je očekávaný stav).

Parser je záměrně obecný (harvest z odkazů na details.html, ne z jednoho
konkrétního data-testid), protože markup se mění — mezi dvěma běhy v 8/2026
mobile.de tiše přejmenoval kartu inzerátu z "listing-title-card-view" na
"result-listing-N" a starý parser by na nové variantě dostal 0 shod.

DŮLEŽITÉ (oprava 8/2026): fulltext hledání (`modelDescription.modelDescription`)
mobile.de při kanonizaci URL tiše ZAHODÍ — výsledná stránka je pak "nejnovější
auta v ceně/roce" bez filtru na značku/model, takže name_includes na první
stránce skoro nikdy nic nenajde (proto předtím 0 inzerátů i u BMW 130i/Audi S3/
Golf GTI, i když jich na trhu reálně je spousta). Skutečný filtr chce
strukturované `makeModelVariant1.makeId`/`.modelId` (numerické, interní ID
mobile.de — zjištěno z <select name="mk"/"md"> na search formu, viz
scripts/mobilede_probe.py). Proto: pokud portal_params["mobilede"] obsahuje
make+model, který umíme přeložit (_MAKE_IDS/_MODEL_IDS níže), použije se
strukturovaný filtr; jinak fallback na starý fulltext (degradovaný, ale funkční
pro necílené watche).

portal_params["mobilede"]:
  make, model    — pro presny filtr (napr. "VW"/"Golf", "BMW"/"130i") — viz _resolve_ids
  text           — fallback fulltext, pouzije se jen kdyz make/model nejde prelozit
  name_includes  — klientska pojistka (napr. "gti"/"s3") — nutna, model "Golf"/"320" pokryva vic motorizaci
  year_from/to, price_to (EUR)
  transmission   — "manual" zahodi inzeraty, kde title+atributy vyzni jako automat
                   (DSG/Automatik/Tiptronic apod.). Filtr prevodovky v UI mobile.de
                   je schovany v modalu bez stabilniho URL parametru (overeno), takze
                   se resi az po stazeni pres app.normalize.parse_transmission.
  power_from_kw  — zahodi inzeraty se znamym vykonem pod tuto hranici (kW).
                   Spolehlivejsi nez name_includes na "gti"/"m3" apod. — vykon je
                   v atributech skoro vzdy, title se pise kazdy jinak. Stejny
                   duvod jako u transmission: filtr vykonu je taky jen v modalu.
  fuel           — "petrol"/"diesel"/... (viz normalize._FUEL_HINTS). Zahodi
                   nesedici palivo — pro modely, kde mobile.de miha vic motorizaci
                   pod jednim cislem (napr. BMW "320" = 320i i 320d dohromady).

Poznamka k razeni: kdykoli je nastaveny power_from_kw/transmission/fuel/
name_includes (= filtrujeme uzsi trim v ramci sirsiho "model" bucketu), radi se
podle ceny sestupne misto "nejnovejsi" — hledany trim je typicky drazsi nez
zaklad stejneho modelu, takze se v ramci nasi strankove kapacity (MAX_PAGES)
nakupi driv. Bez toho by "nejnovejsi" razeni bylo z valne vetsiny zaklad. verze
a hledany trim by se ztratil hluboko ve strankach (overeno na Golf GTI: 6 → 36
nalezenych po prechodu na razeni cenou).
"""

from __future__ import annotations

import html as html_mod
import logging
import random
import re
import time

from app.mobilede_catalog import resolve_ids
from app.normalize import parse_fuel, parse_power_kw, parse_transmission
from app.scrapers.base import RawListing, Scraper, SearchQuery, title_matches

logger = logging.getLogger(__name__)

BASE = "https://suchen.mobile.de"
# mobile.de/Akamai pusti z rezidencni IP ~1 pozadavek, pak IP na chvili flagne.
# Proto: JEDEN pokus na watch (retry jen flag prodluzuje) + dlouha pauza mezi watchi,
# aby se stihla reputace srovnat. Po prvni challenge uz dalsi watche nezkousime.
DELAY_RANGE = (60.0, 120.0)

# Jeden inzerat = jeden <a href="...details.html?id=...">...</a> odkaz (stabilni
# napric variantami markupu, na rozdil od konkretniho data-testid karty, ktery
# se mezi variantami lisi - "listing-title-card-view" vs "result-listing-N").
_BLOCK_SPLIT = re.compile(r'(?=<a\b[^>]*href="[^"]*details\.html\?id=\d+[^"]*"[^>]*>)')
# Nazev = hlavni ("Volkswagen Golf") + podtitul ("GTI 2.0 TSI DSG") - v obou
# variantach markupu dva <span title="...">...</span> uvnitr <h2>...</h2>.
# Podtitul nese motorizaci → klicovy pro name_includes.
_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
_TITLE_ATTR_RE = re.compile(r'title="([^"]*)"')
_PRICE_RE = re.compile(r'data-testid="price-label"[^>]*>(.*?)</span>', re.S)
# mobile.de vlastni hodnoceni ceny vuci trhu ("Fairer Preis"/"Hoher Preis" apod.).
# Neni v HTML karte (tu delime na bloky pres _BLOCK_SPLIT), ale v JSON blobu
# nekde jinde na strance (hydratacni data) - jeden objekt na inzerat, tvar:
# ..."priceRating":{"rating":"VERY_GOOD_PRICE","ratingLabel":"Sehr guter Preis",...}
# ...,"id":461773380,"kba":{...}... (id je nejblizsi NASLEDUJICI vyskyt "id"+"kba").
# Parsuje se proto zvlast pres celou stranku, ne per-blok. Bereme ENUM (ne label) —
# je jazykove nezavisly, takze prezije i zmenu jazyka stranky.
_PRICE_RATING_JSON_RE = re.compile(r'"priceRating":\{"rating":"([A-Z_]+)"')
_LISTING_ID_JSON_RE = re.compile(r'"id":(\d+),"kba":')


def _extract_price_ratings(page_html: str) -> dict[str, str]:
    """{source_id: rating_enum} pro celou stranku - parovani podle pozice v JSON blobu."""
    ratings = [(m.start(), m.group(1)) for m in _PRICE_RATING_JSON_RE.finditer(page_html)]
    if not ratings:
        return {}
    ids = [(m.start(), m.group(1)) for m in _LISTING_ID_JSON_RE.finditer(page_html)]
    out: dict[str, str] = {}
    for pos, rating in ratings:
        # nejblizsi nasledujici id+kba po pozici priceRating patri ke stejnemu objektu
        for id_pos, source_id in ids:
            if id_pos > pos:
                out[source_id] = rating
                break
    return out


_ATTR_RE = re.compile(
    r'data-testid="listing-details-attributes"[^>]*>(.*?)'
    r'(?=data-testid="seller-info"|data-testid="listing-action)',
    re.S,
)
_HREF_RE = re.compile(r'href="([^"]*details\.html[^"]*)"')
_IMG_RE = re.compile(r'src="(https://img\.classistatic\.de/[^"\s]+)"')
_ID_RE = re.compile(r"[?&]id=(\d+)")
_EZ_RE = re.compile(r"EZ\s*(?:\d{2}/)?((?:19|20)\d{2})")
_KM_RE = re.compile(r"([\d.]{2,})\s*km", re.IGNORECASE)

# Interni numericka ID mobile.de drzi app/mobilede_catalog.py (JSON vedle kodu).
# Bez spravneho ID mobile.de klic TISE IGNORUJE a vrati nesouvisejici auta
# (overeno: textove "VW"/"Golf" vratilo Mercedes GLA, Ford Focus, Citroën C4).
# Nove znacky/modely doplni `python -m scripts.mobilede_catalog_sync`.
_resolve_ids = resolve_ids


MAX_PAGES = 10  # ~24 inzeratu/stranka -> az ~240; dalsi stranky jsou jen navigace
# uvnitr uz projite Akamai vyzvy (levne, viz _paginate - pageNumber= primo v URL)


class MobileDeLocalScraper(Scraper):
    """Scrapling StealthyFetcher (Camoufox); jeden pokus na watch, měkké selhání při challenge."""

    name = "mobilede"

    def __init__(self) -> None:
        self._challenged = False  # po prvni challenge uz dalsi watche nezkousej

    def fetch_listings(self, query: SearchQuery) -> list[RawListing]:
        if self._challenged:
            logger.info("mobilede[%s]: preskakuji (IP challenge v tomto behu)", query.model)
            return []
        try:
            from scrapling.fetchers import StealthyFetcher
        except ImportError:
            logger.warning("mobilede: Scrapling neni nainstalovany, preskakuji")
            return []

        url = _build_url(query)
        pages: list[str] = []

        def _paginate(page):
            # Consent modal blokuje kliky na "Weiter" - odklikni, pokud se objevi.
            try:
                page.click(".mde-consent-accept-btn", timeout=4000)
            except Exception:  # noqa: BLE001 — modal se nemusi objevit vubec
                pass
            pages.append(page.content())
            # Klikani na "Weiter" bylo nespolehlive (prekryvajici prvky, timeouty
            # i s force=True). mobile.de sam po kliku kanonizuje URL na
            # "...&pageNumber=N" - primo tam navigovat je stabilnejsi a rychlejsi.
            base_url = page.url
            for page_num in range(2, MAX_PAGES + 1):
                try:
                    page.goto(
                        f"{base_url}&pageNumber={page_num}",
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )
                    page.wait_for_timeout(2000)
                except Exception as exc:  # noqa: BLE001
                    logger.info(
                        "mobilede: navigace na stranku %d selhala: %s", page_num, str(exc)[:150]
                    )
                    break
                html = page.content()
                if "details.html?id=" not in html:
                    break  # posledni stranka
                pages.append(html)
            return page

        # JEDEN pokus (viz DELAY_RANGE komentar) - zadny retry pri chybe/challenge.
        # Strankovani (page_action) bezi uvnitr TOHOTO jednoho projeti Akamai
        # vyzvy - dalsi stranky uz nejsou nove pozadavky/dalsi flag riziko.
        response = StealthyFetcher.fetch(
            url,
            headless=True,
            humanize=True,
            os_randomize=True,
            block_webrtc=True,
            google_search=False,
            network_idle=True,
            wait=8000,
            timeout=45000,
            page_action=_paginate,
        )
        title = (response.css("title::text").get() or "") if pages else ""
        blocked = not pages or "verweigert" in title.lower() or "denied" in title.lower()

        if blocked:
            logger.warning(
                "mobilede[%s]: Akamai challenge, preskakuji (IP potrebuje klid)", query.model
            )
            self._challenged = True
            return []

        raws: list[RawListing] = []
        seen_ids: set[str] = set()
        for page_html in pages:
            for raw in parse_listings(page_html, query):
                if raw.source_id in seen_ids:
                    continue
                seen_ids.add(raw.source_id)
                raws.append(raw)

        logger.info("mobilede[%s]: %d inzeratu (%d stranek)", query.model, len(raws), len(pages))
        time.sleep(random.uniform(*DELAY_RANGE))
        return raws


def _build_url(query: SearchQuery) -> str:
    p = query.params
    # Kdyz filtrujeme na vyssi motorizaci (power_from_kw) nebo prevodovku, radeji
    # radit podle ceny sestupne (v ramci price_to stropu) nez podle novosti:
    # hledany trim (GTI apod.) je typicky drazsi nez zakladni verze stejneho
    # modelu, takze se v ramci nasi strankove kapacity nakupi driv - "nejnovejsi"
    # razeni je z valne vetsiny obycejne Golfy/etc a hledany trim se v nem ztrati.
    # Pozn.: "sortOption.sortBy=price" mobile.de tise ignoruje (jen creationTime
    # umi tenhle dlouhy tvar) - funkcni je zkraceny "sb=p&od=down" ze select
    # menu na strance (zjisteno 8/2026).
    if p.get("power_from_kw") or p.get("transmission") or p.get("fuel") or p.get("name_includes"):
        sort = "sb=p&od=down"
    else:
        sort = "sb=doc&od=down"
    parts = [f"{BASE}/fahrzeuge/search.html?isSearchRequest=true&scopeId=C&usage=USED&{sort}"]
    ids = _resolve_ids(p.get("make"), p.get("model"))
    if ids:
        make_id, model_id = ids
        parts.append(f"makeModelVariant1.makeId={make_id}&makeModelVariant1.modelId={model_id}")
    else:
        text = p.get("text")
        if text:
            parts.append("modelDescription.modelDescription=" + text.replace(" ", "+"))
    if p.get("year_from"):
        parts.append(f"minFirstRegistrationDate={p['year_from']}-01-01")
    if p.get("year_to"):
        parts.append(f"maxFirstRegistrationDate={p['year_to']}-12-31")
    if p.get("price_to"):
        parts.append(f"maxPrice={p['price_to']}")
    return "&".join(parts)


def _extract_title(blk: str) -> str | None:
    """Hlavni nazev + podtitul (motorizace) z prvniho <h2>...</h2> v bloku.

    Obe pozorovane varianty markupu maji title+subtitul jako dva
    <span title="...">...</span> uvnitr <h2>, jen s jinymi (obfuskovanymi)
    class jmeny - proto se necilime na tridu, jen na title atribut.
    """
    h2 = _H2_RE.search(blk)
    if not h2:
        return None
    titles = [html_mod.unescape(t) for t in _TITLE_ATTR_RE.findall(h2.group(1)) if t]
    return _clean(" ".join(titles)) if titles else None


def _clean(fragment: str) -> str:
    """HTML fragment → čistý text (bez tagů, dekódované entity, sjednocené mezery)."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_mod.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_listings(page_html: str, query: SearchQuery) -> list[RawListing]:
    """Rozparsuje HTML výsledovky mobile.de na RawListing. Testovatelné bez sítě."""
    blocks = _BLOCK_SPLIT.split(page_html)
    price_ratings = _extract_price_ratings(page_html)
    params = query.params
    name_includes = params.get("name_includes", [])
    out: list[RawListing] = []
    seen: set[str] = set()

    for blk in blocks:
        title = _extract_title(blk)
        price_m = _PRICE_RE.search(blk)
        href_m = _HREF_RE.search(blk)
        if not (title and price_m and href_m):
            continue

        href = html_mod.unescape(href_m.group(1))
        id_m = _ID_RE.search(href)
        if not id_m or id_m.group(1) in seen:
            continue
        source_id = id_m.group(1)

        if not title_matches(title, name_includes):
            continue

        price = int(re.sub(r"[^\d]", "", _clean(price_m.group(1))) or 0)
        if price < 500:  # sponzorovaný blok / bez ceny
            continue
        # Cenovy strop posilame i v URL (maxPrice), ale kontrolujeme i tady:
        # mobile.de uz jednou parametr tise zahodil (modelDescription), takze
        # se na server-side filtr nespolehame.
        if params.get("price_to") and price > params["price_to"]:
            continue

        attrs_m = _ATTR_RE.search(blk)
        attrs = _clean(attrs_m.group(1)) if attrs_m else ""

        # Prevodovka (DSG/Automatik apod.) byva jen v titulku, ne v atributech
        # ("EZ .. • km • kW • palivo") - kombinuj oboje pro spolehlivou klasifikaci.
        if params.get("transmission") == "manual":
            if parse_transmission(f"{attrs} {title}") == "auto":
                continue

        # Vykon je spolehlivejsi diskriminator vyssich motorizaci (GTI/M/S apod.)
        # nez text v titulku - ten se pise ruzne ("GTI", "2.0 TSI", zdvojene atd.)
        # a filtr vykonu v UI mobile.de je jen v modalu bez stabilniho URL parametru.
        if params.get("power_from_kw"):
            power_kw = parse_power_kw(attrs)
            # Na rozdil od transmission tu neznamy vykon NEPROPOUSTIME - u vsech
            # overenych GTI se vykon parsuje spolehlive, takze "neznamo" tady
            # skoro vzdy znamena low-trim Golf, kde v atributech kW jednoduse neni.
            if power_kw is None or power_kw < params["power_from_kw"]:
                continue

        # Palivo (Benzin/Diesel) je posledni polozka v atributech skoro vzdy
        # pritomna - pouzij se tam, kde jeden mobile.de "model" bucket mixuje
        # vice motorizaci se stejnym cislem (napr. BMW "320" = 320i i 320d).
        if params.get("fuel"):
            if parse_fuel(attrs) != params["fuel"]:
                continue

        year = None
        ez = _EZ_RE.search(attrs)
        if ez:
            year = int(ez.group(1))
        if year is not None:
            if params.get("year_from") and year < params["year_from"]:
                continue
            if params.get("year_to") and year > params["year_to"]:
                continue
        elif params.get("year_from") or params.get("year_to"):
            continue

        km = None
        km_m = _KM_RE.search(attrs)
        if km_m:
            val = int(re.sub(r"[^\d]", "", km_m.group(1)) or 0)
            if 1_000 <= val <= 1_000_000:
                km = val

        img_m = _IMG_RE.search(blk)
        seen.add(source_id)
        out.append(
            RawListing(
                source="mobilede",
                source_id=source_id,
                title=title,
                url=f"{BASE}/fahrzeuge/details.html?id={source_id}",
                price=price,
                currency="EUR",
                year=year,
                mileage_km=km,
                transmission_text=f"{attrs} {title}",  # normalize vytáhne manual/automat
                drivetrain_text=title,
                fuel_text=attrs,  # Benzin/Diesel je v atributech
                power_text=attrs,  # "92 kW (125 PS)" je v atributech
                body_text=title,
                price_rating_text=price_ratings.get(source_id),
                image_url=img_m.group(1) if img_m else None,
                raw={"attrs": attrs},
            )
        )
    return out
