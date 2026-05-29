"""Provider ticker suffix lookup for Market-scoped security identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .catalog import MarketCatalogError, get_market_catalog
from .mic_aliases import mic_alias_registry


@dataclass(frozen=True, slots=True)
class MarketSymbolSuffixDefinition:
    market: str
    suffix: str | None
    aliases: tuple[str, ...]
    is_default: bool = False


class MarketSymbolSuffixRegistry:
    """Resolve provider ticker suffixes separately from canonical MIC aliases."""

    def __init__(self, definitions: Iterable[MarketSymbolSuffixDefinition]) -> None:
        self._definitions = tuple(definitions)
        self._default_by_market: dict[str, str | None] = {}
        self._suffix_by_market_alias: dict[tuple[str, str], str | None] = {}
        self._market_by_suffix: dict[str, str] = {}
        self._mic_by_suffix: dict[str, str] = {}

        catalog = get_market_catalog()
        for definition in self._definitions:
            market = definition.market.strip().upper()
            try:
                catalog.get(market)
            except MarketCatalogError as exc:
                raise ValueError(f"Unsupported symbol suffix market: {market}") from exc

            if definition.is_default:
                if market in self._default_by_market:
                    raise ValueError(f"Duplicate default symbol suffix for {market}")
                self._default_by_market[market] = definition.suffix

            if definition.suffix:
                existing_market = self._market_by_suffix.get(definition.suffix)
                if existing_market is not None and existing_market != market:
                    raise ValueError(
                        f"Duplicate symbol suffix {definition.suffix!r} for "
                        f"{existing_market} and {market}"
                    )
                self._market_by_suffix[definition.suffix] = market
                for alias in definition.aliases:
                    resolved = mic_alias_registry.resolve(market, alias)
                    if resolved is not None:
                        self._mic_by_suffix[definition.suffix] = resolved.mic
                        break

            for alias in definition.aliases:
                normalized_alias = self._normalize_alias(alias)
                if not normalized_alias:
                    continue
                key = (market, normalized_alias)
                if (
                    key in self._suffix_by_market_alias
                    and self._suffix_by_market_alias[key] != definition.suffix
                ):
                    raise ValueError(
                        f"Duplicate symbol suffix alias for {market}: {alias!r}"
                    )
                self._suffix_by_market_alias[key] = definition.suffix

    def suffix_for(self, market: str | None, alias: str | None = None) -> str | None:
        market_code = str(market or "").strip().upper()
        if not market_code:
            return None
        normalized_alias = self._normalize_alias(alias)
        if normalized_alias:
            suffix = self._suffix_by_market_alias.get((market_code, normalized_alias))
            if suffix is not None:
                return suffix
        return self._default_by_market.get(market_code)

    def market_for_symbol(self, symbol: str | None) -> str | None:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            return None
        for suffix, market in self.suffix_market_pairs():
            if normalized_symbol.endswith(suffix):
                return market
        return None

    def mic_for_symbol(self, symbol: str | None) -> str | None:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            return None
        for suffix, _market in self.suffix_market_pairs():
            if normalized_symbol.endswith(suffix):
                return self._mic_by_suffix.get(suffix)
        return None

    def suffix_market_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                self._market_by_suffix.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            )
        )

    @staticmethod
    def _normalize_alias(value: str | None) -> str:
        return str(value or "").strip().upper()


market_symbol_suffix_registry = MarketSymbolSuffixRegistry(
    (
        MarketSymbolSuffixDefinition(
            "US",
            None,
            ("NYSE", "XNYS", "NASDAQ", "XNAS", "AMEX", "XASE"),
            is_default=True,
        ),
        MarketSymbolSuffixDefinition(
            "HK",
            ".HK",
            ("HKEX", "SEHK", "XHKG"),
            is_default=True,
        ),
        MarketSymbolSuffixDefinition("IN", ".NS", ("NSE", "XNSE"), is_default=True),
        MarketSymbolSuffixDefinition("IN", ".BO", ("BSE", "XBOM")),
        MarketSymbolSuffixDefinition("JP", ".T", ("TSE", "JPX", "XTKS"), is_default=True),
        MarketSymbolSuffixDefinition("KR", ".KS", ("KOSPI", "KRX", "XKRX"), is_default=True),
        MarketSymbolSuffixDefinition("KR", ".KQ", ("KOSDAQ",)),
        MarketSymbolSuffixDefinition("TW", ".TW", ("TWSE", "XTAI"), is_default=True),
        MarketSymbolSuffixDefinition("TW", ".TWO", ("TPEX",)),
        MarketSymbolSuffixDefinition(
            "CN",
            ".SS",
            ("SSE", "SHSE", "XSHG"),
            is_default=True,
        ),
        MarketSymbolSuffixDefinition("CN", ".SZ", ("SZSE", "XSHE")),
        MarketSymbolSuffixDefinition("CN", ".BJ", ("BSE", "BJSE", "XBSE", "XBEI")),
        MarketSymbolSuffixDefinition("SG", ".SI", ("SGX", "SES", "XSES"), is_default=True),
        MarketSymbolSuffixDefinition("CA", ".TO", ("TSX", "XTSE"), is_default=True),
        MarketSymbolSuffixDefinition("CA", ".V", ("TSXV", "XTNX")),
        MarketSymbolSuffixDefinition("DE", ".DE", ("XETR", "XETRA"), is_default=True),
        MarketSymbolSuffixDefinition("DE", ".F", ("XFRA", "FRA", "FWB")),
    )
)
