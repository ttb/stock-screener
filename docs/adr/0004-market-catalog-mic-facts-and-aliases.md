# Market Catalog owns canonical MICs; aliases are Market-scoped

The Market Catalog owns canonical Market facts: `primary_mic`, supported `mics`, supported currencies, fallback default currency, and app-visible Market Capabilities. Per-MIC calendar, timezone, provider-calendar, and MIC default-currency facts live in MIC Facts, while legacy exchange labels are Market-scoped MIC Aliases resolved by compatibility layers such as SecurityMaster or MarketRegistry.

## Context

The previous `exchanges` shape mixed canonical MICs (`XNYS`, `XHKG`) with informal labels (`NYSE`, `BSE`). That fails for aggregated multi-MIC Markets and for ambiguous aliases: `BSE` can mean India/Bombay in one Market context and China/Beijing in another. ADR 0001 made MICs canonical; this ADR records the follow-on split needed to keep Market facts, MIC facts, and alias compatibility from drifting together.

## Considered Options

- **Keep one `exchanges` tuple** — rejected because it preserves ambiguity between canonical MICs and aliases.
- **Make aliases globally unique** — rejected because real aliases such as `BSE` are Market-scoped.
- **Split canonical MICs, MIC Facts, and Market-scoped aliases** — chosen because it adds a small amount of structure while making multi-MIC Markets, calendar resolution, and legacy API compatibility explicit.

## Consequences

- New APIs and internal modules use `mic`; legacy `exchange` inputs resolve through a Market-scoped alias lookup.
- Market-level calendar calls are compatibility defaults that resolve to the Market's primary MIC; MIC-level calendar facts are canonical.
- Market Catalog may expose derived display/compat fields, but canonical timezone/calendar facts are MIC-level.
