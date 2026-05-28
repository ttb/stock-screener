# Per-row currency; market-default deprecated for FX

FX normalization reads each row's `StockUniverse.currency` rather than the market's default currency. `currency_for_market` is kept only as a boot-time fallback for paths that have no row context. `MarketCatalogEntry.currency` is replaced by `supported_currencies: tuple[str, ...]`, which the FX rate-primer and the frontend market panel both consume.

## Context

Pre-existing markets (US, HK, IN, JP, KR, TW, CN) are single-currency, so `currency_for_market(market)` happened to be correct for every row. The Euronext market spans four currencies (EUR, NOK, GBP, USD) under one Market — translating an Oslo NOK market cap with an EUR rate would silently produce wrong `market_cap_usd` numbers and propagate the error into every downstream breadth and scan computation.

Audit found exactly one production caller of `currency_for_market` outside the FX service itself: `fundamentals_cache_service._enrich_with_fx_normalization(data, market)` at line 568. Per-row currency was already plumbed through ingestion and stored on `StockUniverse.currency` for every row in every market.

## Considered Options

- **Single primary currency on the catalog entry** — keep `MarketCatalogEntry.currency = "EUR"` and document it as "primary, with row overrides". Rejected: leaves the wrong-currency translation bug latent in `_enrich_with_fx_normalization`.
- **Two fields: primary + supported** — add `supported_currencies` alongside `currency`. Rejected: keeps the misleading `currency` field as the obvious-but-wrong default.
- **Drop market-default entirely for FX** — chosen. The FX-relevant code path takes a currency argument directly, sourced from the row.

## Consequences

- `_enrich_with_fx_normalization(data, market)` becomes `_enrich_with_fx_normalization(data, currency)`; callers resolve currency from the security's row.
- `MarketCatalogEntry.currency` is renamed to `supported_currencies: tuple[str, ...]`. ENX = `("EUR", "NOK", "GBP", "USD")`, US = `("USD",)`.
- `currency_for_market` stays for boot-time / pre-universe paths and is documented as a fallback only; new FX-path code does not call it.
- Drift-prevention test: every distinct `StockUniverse.currency` value for a market must be in that market's `supported_currencies`.
- `MarketProfile.currency` is repurposed as a boot-time default seed (used in `_MARKET_DEFAULTS` only); its value never appears in FX arithmetic.
