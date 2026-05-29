"""Stable Market Catalog facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .mic import MicFacts

CATALOG_VERSION = "2026-05-17.v1"


class MarketCatalogError(ValueError):
    """Raised when a caller asks for an unsupported Market."""


@dataclass(frozen=True)
class MarketCapabilities:
    benchmark: bool
    breadth: bool
    fundamentals: bool
    group_rankings: bool
    feature_snapshot: bool
    official_universe: bool
    finviz_screening: bool


@dataclass(frozen=True)
class MarketCatalogEntry:
    code: str
    label: str
    primary_mic: str
    mics: tuple[str, ...]
    supported_currencies: tuple[str, ...]
    default_currency: str
    mic_facts: tuple[MicFacts, ...]
    exchanges: tuple[str, ...]
    indexes: tuple[str, ...]
    capabilities: MarketCapabilities

    def __post_init__(self) -> None:
        if self.primary_mic not in self.mics:
            raise ValueError(f"{self.code} primary MIC must be present in mics")
        if self.default_currency not in self.supported_currencies:
            raise ValueError(
                f"{self.code} default currency must be present in supported_currencies"
            )
        fact_mics = {facts.mic for facts in self.mic_facts}
        missing_facts = set(self.mics) - fact_mics
        if missing_facts:
            raise ValueError(
                f"{self.code} missing MIC facts for: {', '.join(sorted(missing_facts))}"
            )

    @property
    def primary_mic_facts(self) -> MicFacts:
        return self.mic_facts_for(self.primary_mic)

    @property
    def currency(self) -> str:
        """Deprecated compatibility alias for fallback/default row currency."""
        return self.default_currency

    @property
    def timezone(self) -> str:
        """Deprecated compatibility alias for primary MIC display timezone."""
        return self.primary_mic_facts.timezone

    @property
    def display_timezone(self) -> str:
        return self.primary_mic_facts.timezone

    @property
    def calendar_id(self) -> str:
        """Deprecated compatibility alias for primary MIC calendar ID."""
        return self.primary_mic_facts.calendar_id

    @property
    def provider_calendar_id(self) -> str | None:
        return self.primary_mic_facts.provider_calendar_id

    def mic_facts_for(self, mic: str | None = None) -> MicFacts:
        target = (mic or self.primary_mic).strip().upper()
        for facts in self.mic_facts:
            if facts.mic == target:
                return facts
        supported = ", ".join(self.mics)
        raise MarketCatalogError(
            f"Unsupported MIC {mic!r} for market {self.code}. Supported: {supported}"
        )

    def as_runtime_payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "label": self.label,
            "primary_mic": self.primary_mic,
            "mics": list(self.mics),
            "supported_currencies": list(self.supported_currencies),
            "default_currency": self.default_currency,
            "mic_facts": [asdict(facts) for facts in self.mic_facts],
            # Compatibility fields for existing frontend/runtime consumers.
            "currency": self.currency,
            "timezone": self.timezone,
            "calendar_id": self.calendar_id,
            "provider_calendar_id": self.provider_calendar_id,
            "exchanges": list(self.exchanges),
            "indexes": list(self.indexes),
            "capabilities": asdict(self.capabilities),
        }


class MarketCatalog:
    """Stable Market facts; mutable runtime state lives elsewhere."""

    def __init__(self, entries: Iterable[MarketCatalogEntry]) -> None:
        self._entries = tuple(entries)
        self._by_code = {entry.code: entry for entry in self._entries}

    def supported_market_codes(self) -> list[str]:
        return [entry.code for entry in self._entries]

    def get(self, market: str | None) -> MarketCatalogEntry:
        code = (market or "").strip().upper()
        try:
            return self._by_code[code]
        except KeyError as exc:
            supported = ", ".join(self.supported_market_codes())
            raise MarketCatalogError(
                f"Unsupported market {market!r}. Supported: {supported}"
            ) from exc

    def as_runtime_payload(self) -> dict[str, object]:
        return {
            "version": CATALOG_VERSION,
            "markets": [entry.as_runtime_payload() for entry in self._entries],
        }


FULL_CAPABILITIES = MarketCapabilities(
    benchmark=True,
    breadth=True,
    fundamentals=True,
    group_rankings=True,
    feature_snapshot=True,
    official_universe=True,
    finviz_screening=False,
)


def _mic_facts(
    mic: str,
    *,
    timezone: str,
    default_currency: str,
    calendar_id: str | None = None,
    provider_calendar_id: str | None = None,
) -> MicFacts:
    return MicFacts(
        mic=mic,
        calendar_id=calendar_id or mic,
        timezone=timezone,
        default_currency=default_currency,
        provider_calendar_id=provider_calendar_id,
    )


def _market_entry(
    *,
    code: str,
    label: str,
    default_currency: str,
    timezone: str,
    primary_mic: str,
    mics: tuple[str, ...],
    exchanges: tuple[str, ...],
    indexes: tuple[str, ...],
    capabilities: MarketCapabilities,
    supported_currencies: tuple[str, ...] | None = None,
    provider_calendar_ids: dict[str, str] | None = None,
) -> MarketCatalogEntry:
    provider_calendar_ids = provider_calendar_ids or {}
    return MarketCatalogEntry(
        code=code,
        label=label,
        primary_mic=primary_mic,
        mics=mics,
        supported_currencies=supported_currencies or (default_currency,),
        default_currency=default_currency,
        mic_facts=tuple(
            _mic_facts(
                mic,
                timezone=timezone,
                default_currency=default_currency,
                provider_calendar_id=provider_calendar_ids.get(mic),
            )
            for mic in mics
        ),
        exchanges=exchanges,
        indexes=indexes,
        capabilities=capabilities,
    )


MARKET_CATALOG = MarketCatalog(
    [
        _market_entry(
            code="US",
            label="United States",
            default_currency="USD",
            timezone="America/New_York",
            primary_mic="XNYS",
            mics=("XNYS", "XNAS", "XASE"),
            exchanges=("NYSE", "NASDAQ", "AMEX"),
            indexes=("SP500",),
            capabilities=MarketCapabilities(
                benchmark=True,
                breadth=True,
                fundamentals=True,
                group_rankings=True,
                feature_snapshot=True,
                official_universe=False,
                finviz_screening=True,
            ),
        ),
        _market_entry(
            code="HK",
            label="Hong Kong",
            default_currency="HKD",
            timezone="Asia/Hong_Kong",
            primary_mic="XHKG",
            mics=("XHKG",),
            exchanges=("HKEX", "SEHK", "XHKG"),
            indexes=("HSI",),
            capabilities=FULL_CAPABILITIES,
        ),
        _market_entry(
            code="IN",
            label="India",
            default_currency="INR",
            timezone="Asia/Kolkata",
            primary_mic="XNSE",
            mics=("XNSE", "XBOM"),
            exchanges=("NSE", "XNSE", "BSE", "XBOM"),
            indexes=(),
            capabilities=FULL_CAPABILITIES,
            provider_calendar_ids={"XNSE": "NSE"},
        ),
        _market_entry(
            code="JP",
            label="Japan",
            default_currency="JPY",
            timezone="Asia/Tokyo",
            primary_mic="XTKS",
            mics=("XTKS",),
            exchanges=("TSE", "JPX", "XTKS"),
            indexes=("NIKKEI225",),
            capabilities=FULL_CAPABILITIES,
        ),
        _market_entry(
            code="KR",
            label="South Korea",
            default_currency="KRW",
            timezone="Asia/Seoul",
            primary_mic="XKRX",
            mics=("XKRX",),
            exchanges=("KOSPI", "KOSDAQ", "KRX", "XKRX"),
            indexes=(),
            capabilities=FULL_CAPABILITIES,
        ),
        _market_entry(
            code="TW",
            label="Taiwan",
            default_currency="TWD",
            timezone="Asia/Taipei",
            primary_mic="XTAI",
            mics=("XTAI",),
            exchanges=("TWSE", "TPEX", "XTAI"),
            indexes=("TAIEX",),
            capabilities=FULL_CAPABILITIES,
        ),
        _market_entry(
            code="CN",
            label="China A-shares",
            default_currency="CNY",
            timezone="Asia/Shanghai",
            primary_mic="XSHG",
            mics=("XSHG", "XSHE", "XBSE"),
            exchanges=("SSE", "SZSE", "BJSE", "XSHG", "XSHE", "XBSE"),
            indexes=(),
            capabilities=FULL_CAPABILITIES,
        ),
        _market_entry(
            code="CA",
            label="Canada",
            default_currency="CAD",
            timezone="America/Toronto",
            primary_mic="XTSE",
            mics=("XTSE", "XTNX"),
            exchanges=("TSX", "TSXV", "XTSE", "XTNX"),
            indexes=("TSX_COMPOSITE",),
            capabilities=FULL_CAPABILITIES,
        ),
        _market_entry(
            code="DE",
            label="Germany",
            default_currency="EUR",
            timezone="Europe/Berlin",
            primary_mic="XETR",
            mics=("XETR", "XFRA"),
            exchanges=("XETR", "XETRA", "XFRA", "FRA", "FWB"),
            indexes=("DAX", "MDAX", "SDAX"),
            capabilities=MarketCapabilities(
                benchmark=True,
                breadth=True,
                fundamentals=True,
                group_rankings=False,
                feature_snapshot=True,
                official_universe=True,
                finviz_screening=False,
            ),
        ),
        _market_entry(
            code="SG",
            label="Singapore",
            default_currency="SGD",
            timezone="Asia/Singapore",
            primary_mic="XSES",
            mics=("XSES",),
            exchanges=("SGX", "SES", "XSES"),
            indexes=("STI",),
            capabilities=MarketCapabilities(
                benchmark=True,
                breadth=False,
                fundamentals=True,
                group_rankings=False,
                feature_snapshot=True,
                official_universe=True,
                finviz_screening=False,
            ),
        ),
    ]
)


def get_market_catalog() -> MarketCatalog:
    return MARKET_CATALOG
