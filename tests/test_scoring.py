"""Testy scoring enginu — chovani modelu trhu, fuze s burzou, kalibrace tieru.

Tohle je jadro produktu, takze testy hlidaji hlavne VLASTNOSTI, ktere musi platit
(levnejsi auto ma lepsi skore, vraky se neoznacuji jako dealy, malo dat = zadny
hot deal), ne konkretni cisla — ta se ladi a menily by testy pri kazdem doladeni.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Listing
from app.scoring.engine import (
    DealScore,
    implausibility_reason,
    score_listing,
)

NOW = datetime.now(timezone.utc)
THIS_YEAR = datetime.now().year


def make(
    price: int,
    *,
    year: int = 2015,
    km: int = 120_000,
    title: str = "Volkswagen Golf GTI",
    transmission: str | None = "manual",
    drivetrain: str | None = "fwd",
    price_rating: str | None = None,
    source_id: str = "x",
) -> Listing:
    return Listing(
        source="sauto",
        source_id=source_id,
        model="golf_gti",
        generation="mk7",
        year=year,
        mileage_km=km,
        transmission=transmission,
        drivetrain=drivetrain,
        price_rating=price_rating,
        price_czk=price,
        price_original=price,
        currency="CZK",
        url=f"https://x/{source_id}",
        title=title,
        first_seen=NOW,
        last_seen=NOW,
        is_active=True,
    )


def market(n: int = 60) -> list[Listing]:
    """Realisticky trh: starsi a najetejsi auta levnejsi, mirny sum."""
    out = []
    for i in range(n):
        year = 2013 + (i % 7)
        km = 60_000 + (i % 10) * 20_000
        # zaklad 420k, -18k za rok stari, -0.5 Kc/km, drobny sum podle indexu
        price = int(420_000 - (THIS_YEAR - year) * 18_000 - km * 0.5 + (i % 5) * 3_000)
        out.append(make(price, year=year, km=km, source_id=f"m{i}"))
    return out


# --- zakladni vlastnosti modelu trhu ---


def test_cheaper_car_scores_higher():
    group = market()
    target_cheap = make(150_000, year=2016, km=100_000, source_id="cheap")
    target_pricey = make(400_000, year=2016, km=100_000, source_id="pricey")
    group = group + [target_cheap, target_pricey]

    cheap = score_listing(target_cheap, group)
    pricey = score_listing(target_pricey, group)

    assert cheap.value > pricey.value
    assert cheap.pct_below > 0 > pricey.pct_below


def test_uses_regression_when_enough_data():
    group = market()
    sc = score_listing(group[0], group)
    assert sc.method == "regression"
    assert sc.confidence > 0.5


def test_thin_data_never_produces_hot_deal():
    """Par vzorku nesmi stacit na 'hot' — i kdyz cena vypada skvele."""
    small = [make(300_000, source_id=f"s{i}") for i in range(9)]
    bargain = make(120_000, source_id="bargain")
    sc = score_listing(bargain, small + [bargain])
    assert sc.tier != "hot"


def test_insufficient_samples_marked():
    tiny = [make(300_000, source_id="a"), make(310_000, source_id="b")]
    sc = score_listing(tiny[0], tiny)
    assert sc.method == "insufficient"
    assert sc.tier == "none"
    assert not sc.is_alertable


def test_year_and_km_affect_expected_price():
    """Novejsi auto s nizsim najezdem ma vyssi ocekavanou cenu."""
    group = market()
    young = score_listing(make(300_000, year=2019, km=60_000, source_id="y"), group)
    old = score_listing(make(300_000, year=2013, km=240_000, source_id="o"), group)
    assert young.expected_price > old.expected_price


def test_outlier_does_not_wreck_market_model():
    """Jeden vrak za pakatel nesmi stlacit ocekavanou cenu vsem ostatnim."""
    group = market()
    baseline = score_listing(group[0], group).expected_price

    wrecks = [make(15_000, title="Golf GTI Motorschaden", source_id=f"w{i}") for i in range(5)]
    with_wrecks = score_listing(group[0], group + wrecks).expected_price

    # Huber fit + vyrazeni neduveryhodnych → posun radove male, ne o desitky %
    assert abs(with_wrecks - baseline) / baseline < 0.05


# --- duveryhodnost inzeratu ---


@pytest.mark.parametrize(
    "title,reason",
    [
        ("Golf GTI Motorschaden", "damage"),
        ("Golf GTI Unfallschaden", "damage"),
        ("Golf GTI Bastlerfahrzeug", "damage"),
        ("Golf GTI Hagelschaden", "damage"),
        ("Golf GTI Getriebe defekt", "damage"),
        ("Golf GTI na díly", "damage"),
        ("Golf GTI po nehodě", "damage"),
        ("Golf GTI bouraný", "damage"),
        ("Golf GTI vrak", "damage"),
        # inzeraty, ktere se chlubi OPAKEM — nesmi se chytit
        ("Golf GTI unfallfrei", None),
        ("Golf GTI schadenfrei", None),
        ("Golf GTI nebourané", None),
        ("Volkswagen Golf GTI", None),
    ],
)
def test_damage_detection(title, reason):
    assert implausibility_reason(make(300_000, title=title), 300_000) == reason


def test_implausible_mileage_flagged():
    """2011 auto s '270 km' = chyba parsovani, ne zazrak."""
    sc = implausibility_reason(make(300_000, year=2011, km=270), 300_000)
    assert sc == "mileage"


def test_absurd_price_flagged():
    """Octavia RS za 24k Kc pri medianu 400k = dily/preklik."""
    assert implausibility_reason(make(24_000), 400_000) == "price"


def test_implausible_listing_never_gets_tier():
    group = market()
    wreck = make(60_000, title="Golf GTI Frontschaden", source_id="wreck")
    sc = score_listing(wreck, group + [wreck])
    assert sc.implausible == "damage"
    assert sc.tier == "none"
    assert not sc.is_alertable
    assert sc.value <= 0  # nesmi plavat nahore v zebricku


# --- fuze s hodnocenim burzy ---


# Vychozi auto (2015, 120 tis. km) ma na syntetickem trhu ocekavanou cenu ~162k,
# takze 110k je vyrazne pod ni.
BELOW_MARKET = 110_000


def test_portal_agreement_boosts_confidence():
    group = market()
    plain_l = make(BELOW_MARKET, source_id="p1")
    plain = score_listing(plain_l, group + [plain_l])
    rated = make(BELOW_MARKET, price_rating="great", source_id="p2")
    agreed = score_listing(rated, group + [rated])

    assert agreed.portal_agreement == "agree"
    assert agreed.confidence > plain.confidence
    assert agreed.value > plain.value


def test_portal_conflict_damps_score():
    """Kdyz burza rika 'drahe' a nas model 'levne', skore se stahne."""
    group = market()
    plain_l = make(BELOW_MARKET, source_id="c1")
    plain = score_listing(plain_l, group + [plain_l])
    conflicted_l = make(BELOW_MARKET, price_rating="high", source_id="c2")
    conflicted = score_listing(conflicted_l, group + [conflicted_l])

    assert conflicted.portal_agreement == "conflict"
    assert conflicted.value < plain.value


def test_portal_rating_alone_does_not_create_hot_deal():
    """Hodnoceni burzy je doplnek, ne nahrada — na trzni cene 'great' nestaci."""
    group = market()
    at_market = make(int(sum(g.price_czk for g in group) / len(group)), price_rating="great")
    sc = score_listing(at_market, group + [at_market])
    assert sc.tier != "hot"


# --- kalibrace tieru ---


def test_tier_calibration_is_selective():
    """Na realistickem trhu smi byt 'hot' jen mala mensina nabidky."""
    group = market(120)
    tiers = [score_listing(g, group).tier for g in group]
    hot_share = tiers.count("hot") / len(tiers)
    assert hot_share <= 0.15, f"hot je {hot_share:.0%} — prah je moc volny"


def test_clear_bargain_gets_hot():
    group = market(120)
    # ~40 % pod trhem pro svuj rocnik/najezd
    bargain = make(170_000, year=2018, km=80_000, source_id="steal")
    sc = score_listing(bargain, group + [bargain])
    assert sc.tier == "hot"
    assert sc.pct_below > 0.15


def test_market_priced_car_is_not_a_deal():
    group = market(120)
    typical = [g for g in group if g.year == 2016][0]
    sc = score_listing(typical, group)
    assert sc.tier in ("none", "fair")


# --- preference (oddelena osa) ---


def test_preferences_do_not_turn_overpriced_into_deal():
    """Manual + AWD + vybava nesmi udelat 'deal' z predrazeneho auta."""
    group = market(120)
    overpriced = make(
        430_000,
        year=2014,
        km=200_000,
        title="Golf GTI manual servisní knížka xenon panorama navi",
        transmission="manual",
        drivetrain="awd",
        source_id="over",
    )
    sc = score_listing(overpriced, group + [overpriced])
    assert sc.match_score > 0.5  # preference sedi
    assert sc.tier == "none"  # ale cena je spatna → zadny deal


def test_match_score_rewards_preferences():
    group = market(60)
    plain = make(300_000, transmission="auto", drivetrain="fwd", title="Golf GTI", source_id="a")
    loaded = make(
        300_000,
        transmission="manual",
        drivetrain="awd",
        title="Golf GTI servisní knížka xenon",
        source_id="b",
    )
    assert score_listing(loaded, group).match_score > score_listing(plain, group).match_score


def test_deal_score_dataclass_defaults():
    """DealScore jde postavit s minimem argumentu (pouziva notifikace i testy)."""
    sc = DealScore(value=0.2, expected_price=300_000, pct_below=0.1, method="regression")
    assert sc.tier == "none"
    assert sc.confidence == 0.0
    assert sc.is_alertable
