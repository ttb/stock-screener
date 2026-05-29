from __future__ import annotations

import pytest

from app.domain.markets import market_registry
from app.domain.markets.catalog import MarketCatalogError, get_market_catalog


def test_market_catalog_lists_supported_markets_in_runtime_order() -> None:
    catalog = get_market_catalog()

    assert catalog.supported_market_codes() == list(market_registry.supported_market_codes())


def test_market_catalog_entry_contains_stable_market_facts() -> None:
    catalog = get_market_catalog()

    hk = catalog.get("hk")

    assert hk.code == "HK"
    assert hk.label == "Hong Kong"
    assert hk.currency == "HKD"
    assert hk.timezone == "Asia/Hong_Kong"
    assert hk.calendar_id == "XHKG"
    assert hk.exchanges == ("HKEX", "SEHK", "XHKG")
    assert hk.indexes == ("HSI",)
    assert hk.capabilities.official_universe is True
    assert hk.capabilities.finviz_screening is False


def test_market_catalog_entry_exposes_canonical_mic_and_currency_facts() -> None:
    catalog = get_market_catalog()

    us = catalog.get("US")
    india = catalog.get("IN")

    assert us.primary_mic == "XNYS"
    assert us.mics == ("XNYS", "XNAS", "XASE")
    assert us.supported_currencies == ("USD",)
    assert us.default_currency == "USD"
    assert us.currency == "USD"  # Deprecated compatibility alias.
    assert us.primary_mic_facts.calendar_id == "XNYS"
    assert us.primary_mic_facts.timezone == "America/New_York"
    assert us.primary_mic_facts.default_currency == "USD"
    assert us.mic_facts_for("XNAS").timezone == "America/New_York"

    assert india.primary_mic == "XNSE"
    assert india.mics == ("XNSE", "XBOM")
    assert india.supported_currencies == ("INR",)
    assert india.primary_mic_facts.provider_calendar_id == "NSE"
    assert india.mic_facts_for("XBOM").calendar_id == "XBOM"


def test_market_catalog_rejects_unknown_market() -> None:
    catalog = get_market_catalog()

    with pytest.raises(MarketCatalogError, match="Unsupported market 'EU'"):
        catalog.get("EU")


def test_market_catalog_runtime_payload_is_frontend_ready() -> None:
    payload = get_market_catalog().as_runtime_payload()

    assert payload["version"] == "2026-05-17.v1"
    assert [market["code"] for market in payload["markets"]] == list(
        market_registry.supported_market_codes()
    )
    assert payload["markets"][0] == {
        "code": "US",
        "label": "United States",
        "primary_mic": "XNYS",
        "mics": ["XNYS", "XNAS", "XASE"],
        "supported_currencies": ["USD"],
        "default_currency": "USD",
        "mic_facts": [
            {
                "mic": "XNYS",
                "calendar_id": "XNYS",
                "timezone": "America/New_York",
                "default_currency": "USD",
                "provider_calendar_id": None,
            },
            {
                "mic": "XNAS",
                "calendar_id": "XNAS",
                "timezone": "America/New_York",
                "default_currency": "USD",
                "provider_calendar_id": None,
            },
            {
                "mic": "XASE",
                "calendar_id": "XASE",
                "timezone": "America/New_York",
                "default_currency": "USD",
                "provider_calendar_id": None,
            },
        ],
        "currency": "USD",
        "timezone": "America/New_York",
        "calendar_id": "XNYS",
        "provider_calendar_id": None,
        "exchanges": ["NYSE", "NASDAQ", "AMEX"],
        "indexes": ["SP500"],
        "capabilities": {
            "benchmark": True,
            "breadth": True,
            "fundamentals": True,
            "group_rankings": True,
            "feature_snapshot": True,
            "official_universe": False,
            "finviz_screening": True,
        },
    }
