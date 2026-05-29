from __future__ import annotations

from app.domain.universe.listing_tiers import listing_tier_registry


def test_listing_tier_registry_normalizes_source_aliases_by_market() -> None:
    assert listing_tier_registry.normalize("HK", "Main Board") == "main_board"
    assert listing_tier_registry.normalize("HK", "GEM") == "gem"
    assert listing_tier_registry.normalize("SG", "Catalist") == "catalist"


def test_listing_tier_registry_returns_none_for_unknown_or_blank_tiers() -> None:
    assert listing_tier_registry.normalize("HK", "") is None
    assert listing_tier_registry.normalize("HK", "Not A Tier") is None
    assert listing_tier_registry.normalize("US", "Main Board") is None
