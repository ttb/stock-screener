# Point-in-time correctness via audit log, not row versioning

Universe lifecycle (delistings, IPOs, listing-tier changes) is captured *temporally* through the `StockUniverseStatusEvent` audit log, not *spatially* through versioned rows. `StockUniverse` stays mutable with one row per symbol, enforced by `UNIQUE (symbol)`. Backtests that need historical universe membership replay the audit log; the hot path (active-universe queries from the freshness gate, breadth, scans) reads a single mutable row.

## Context

The existing 7-market codebase already follows this pattern: `StockUniverse.is_active`, `status`, `deactivated_at`, and `consecutive_fetch_failures` track current lifecycle state on the row itself, while transitions are recorded in `StockUniverseStatusEvent`. The Euronext plan initially proposed spatial versioning ("board promotions create new rows with `effective_from`") — but that violates the existing `UNIQUE (symbol)` constraint and would force every active-universe query to add a temporal predicate.

## Considered Options

- **Spatial versioning** (one row per (symbol, validity-window)) — rejected: invasive refactor, contradicts existing pattern across 7 markets, slows the hot path.
- **Hybrid: mutable row + separate `*_history` table** — rejected for v1: adds drift surface for a backtest feature no one has asked for.
- **Temporal-via-audit-log** — chosen: matches existing pattern, preserves hot-path performance.

## Consequences

- Listing-tier transitions extend `StockUniverseStatusEvent` with new event types (`tier_promoted`, `tier_demoted`) rather than inserting new universe rows.
- Delistings continue to use the existing pattern: `is_active=False` + `status=inactive_*` + `deactivated_at`. The plan's proposed `delisted_on` column is not added.
- `stock_identifiers` follows the same philosophy: one current row per `(symbol, market, scheme)`, no `effective_from/to` columns. If historical identifier reconstruction becomes load-bearing, it is added as a separate change-event table.
- Backtest tooling that needs historical membership reads the audit log; this is documented as a known cost of the pattern.
