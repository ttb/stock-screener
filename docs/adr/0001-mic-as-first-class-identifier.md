# MIC as first-class identifier

ISO 10383 Market Identifier Codes (XNYS, XPAR, XHKG, ...) are the canonical exchange identifiers in this codebase. SecurityMaster identity, calendar resolution, snapshot keys, and breadth grouping all key on MIC. The `exchange` field on existing models stores the MIC; informal venue names ("NYSE", "BSE") are backfilled to ISO MICs and kept only as backward-compatible lookup aliases.

## Context

The Euronext market expansion (`.plans/euronext-plan.md`) needed to aggregate six venues (XPAR, XAMS, XBRU, XLIS, XMIL, XOSL) under one Market. The pre-existing `MarketProfile.exchanges` tuple mixed MICs ("XNYS") with informal venue names ("NYSE"), and `StockUniverse.exchange` accepted either form. Calendar resolution and per-venue freshness checks could not tolerate that ambiguity — `last_completed_trading_day` for "NYSE" vs "XNYS" had to mean the same thing, but for "XPAR" vs "XAMS" had to mean different things.

## Considered Options

- **Sharpen "exchange"** — keep the existing field name; add a sentence to CONTEXT.md saying it stores the MIC. Rejected: preserves the historical ambiguity in old data; doesn't force new code paths to be precise.
- **Promote MIC** — chosen. Adds **MIC** to CONTEXT.md as a peer of **Market**; new APIs (calendar resolution, breadth grouping, snapshot keys) take `mic=` kwargs explicitly.

## Consequences

- New code uses `mic` as the canonical name; existing `exchange` columns are preserved but understood to hold MICs.
- Phase 0 backfill normalizes informal names ("NYSE" → "XNYS", "BSE" → "XBOM") in `StockUniverse.exchange`.
- `MarketProfile.exchanges` retains both MIC and informal aliases so `_MARKET_BY_EXCHANGE` lookups stay backward-compatible.
- A Market spans one or more MICs; one MIC is primary (the existing `MarketProfile.calendar_id`).
