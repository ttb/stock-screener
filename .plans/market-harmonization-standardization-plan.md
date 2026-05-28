# Market Harmonization and Standardization Plan

## Goal

Address the five harmonization findings from the architecture review:

1. Make Market Catalog the single source for stable Market facts.
2. Deepen Universe ingestion so market-specific source parsing plugs into one lifecycle.
3. Turn provider routing into executable data plans for prices and fundamentals.
4. Fix the per-row currency and FX contract before multi-currency Markets land.
5. Standardize Universe, API, and frontend market contracts around backend-owned facts.

The outcome should be that adding a Market requires a small, predictable set of changes:

- Add stable facts and capabilities to the Market Catalog.
- Add one Universe source Adapter if the Market has an official source.
- Add or select provider Adapters for prices, fundamentals, and growth.
- Add data fixtures and capability tests.

Everything else should derive from those Modules rather than carrying local allowlists.

## Non-Goals

- Equalizing provider coverage across Markets. Missing fields remain valid when represented through capability metadata.
- Replacing yfinance, KRX, AKShare, BaoStock, or Finviz.
- Introducing row versioning for Universe history. ADR 0003 keeps the mutable row plus audit-log model.
- Re-litigating canonical MIC identity. ADR 0001 and ADR 0004 govern MIC naming, MIC Facts, and Market-scoped aliases.
- Breaking existing API payloads or scan request formats in one step.
- Building Euronext itself. This plan prepares for multi-currency and multi-MIC Markets but does not implement ENX.

## Architecture Principles

- **Market Catalog** owns stable supported-Market facts and capability flags.
- **Market Catalog** owns canonical MIC facts (`primary_mic`, `mics`), not informal exchange aliases.
- **MIC Facts** own per-MIC calendar ID, timezone, default currency, and provider calendar ID; Market-level calendar calls use primary MIC as fallback.
- **Market Catalog** may carry `default_currency`, but only as a coarse fallback identity seed; MIC default currency is preferred when MIC context exists, and FX uses row currency.
- **Market Catalog** owns app-visible Market Capabilities only; provider routes and screening-field support live in provider/field coverage modules.
- **MIC Aliases** live in compatibility lookup surfaces such as SecurityMaster or MarketRegistry and resolve to canonical MICs within a Market.
- **Provider Data Plans** own execution order, batching, and fallback rules at Market level, with optional MIC overrides; **Field Capabilities** own field-level support.
- **Runtime Preferences** owns mutable local choices: primary Market, enabled Markets, and Bootstrap state.
- **Market Workload** owns live progress, leases, queue state, and active holders.
- **SecurityMaster** owns security identity: symbol, Market, MIC/exchange field, local code, row currency, timezone.
- **Universe** owns sets of securities and their lifecycle.
- **All Universe** means all active rows globally, independent of Runtime Preferences.
- **Index Registry** owns canonical index definitions and membership-source facts; Market Catalog exposes derived index summaries only for runtime convenience.
- **Benchmark Registry** remains separate from IndexRegistry because benchmarks are comparison instruments, not necessarily index Universes.
- **Universe** rows remain keyed by canonical symbol for now; `(Market, MIC, local_code)` must be unique for active rows.
- A **Scan** has exactly one Universe; that Universe may span multiple Markets.
- **Scan Readiness** is a scan-admission decision using Universe data, freshness, field coverage, and Market Workload state; enabled Market state alone is insufficient.
- **Listing Tier** is optional first-class Universe row metadata, not source-only JSON metadata.
- **Listing Tier** definitions/options are Market-scoped and optionally MIC-scoped.
- **Listing Tier Registry** owns canonical tier keys, display labels, and Market/MIC scoping; Market Catalog exposes derived tier summaries only for runtime convenience.
- Provider routing is policy, but provider execution should be an Adapter plan instead of duplicated conditionals.
- FX uses row currency, not Market default currency, whenever row context exists.

## Delivery Sequence

### Phase 0: Drift Guards and Baseline Tests

Purpose: make current drift visible before refactoring; do not change consumer behavior in this phase.

Files:

- `backend/tests/unit/domain/markets/test_market_catalog.py`
- `backend/tests/unit/domain/markets/test_market_registry.py`
- `backend/tests/unit/test_provider_routing_policy.py`
- `backend/tests/unit/test_field_capability_registry.py`
- `frontend/src/contexts/RuntimeContext.test.jsx`

Tasks:

- Add a drift test that `Market.SUPPORTED_MARKET_CODES`, `market_registry.supported_market_codes()`, `MarketCatalog.supported_market_codes()`, provider routing markets, and field capability market order contain the same codes unless a test explicitly documents an exception.
- Add a test that every catalog exchange alias is either a MIC or a documented backward-compatible alias.
- Add tests for Market-scoped MIC alias resolution, including ambiguous aliases such as `BSE`.
- Add a test that frontend fallback catalog codes match backend catalog codes. Keep it as a safety net until frontend fallback data is generated or removed.
- Add a lightweight drift test documenting where endpoint capability allowlists differ from catalog capabilities. Consumer behavior changes land in Phase 1B.

Acceptance:

- A new Market added to one list but not the others fails tests immediately.
- Existing behavior is unchanged.
- Endpoint/frontend drift tests document mismatches without forcing behavior changes until Phase 1B.

### Phase 1A: Market Identity Facts

Purpose: make Market, MIC, MIC Alias, currency fallback, and Market Capability facts canonical before consumers migrate.

Files:

- `backend/app/domain/markets/catalog.py`
- `backend/app/domain/markets/mic.py`
- `backend/app/domain/markets/aliases.py`
- `backend/app/domain/markets/registry.py`
- `backend/app/domain/markets/market.py`

Tasks:

- Replace `MarketCatalogEntry.currency` with `supported_currencies: tuple[str, ...]` plus fallback-only `default_currency`.
- Replace `MarketCatalogEntry.exchanges` with canonical `primary_mic` and `mics`.
- Add MIC Facts for calendar ID, timezone, default currency, and provider calendar ID.
- Replace canonical Market `timezone` with `display_timezone` derived from primary MIC; keep old `timezone` response field only as a deprecated compatibility alias if needed.
- Keep `default_currency` documented as non-FX fallback only.
- Add a Market-scoped MIC alias resolver with ambiguity handling.
- Make `MarketRegistry` a compatibility facade built from Market Catalog, MIC Facts, MIC Alias Resolver, and benchmark-specific facts rather than duplicating constants.
- New code should prefer the narrower canonical modules over `market_registry.profile()`.
- Keep existing catalog index summaries as compatibility only; canonical IndexRegistry work lands in Phase 5.
- Move supported-Market validation to Market Catalog helpers; keep `Market` as a lightweight canonical code value object or compatibility wrapper.

Acceptance:

- Market Catalog exposes canonical `primary_mic`, `mics`, `supported_currencies`, `default_currency`, and Market Capabilities.
- MIC Facts are the canonical source for calendar, timezone, provider-calendar, and MIC default currency.
- MIC aliases resolve only with Market context unless explicitly globally unambiguous.
- ADR 0002 is reflected in code: catalog has `supported_currencies`, not a single FX currency.

Suggested tests:

- Backend catalog, MIC facts, and registry drift tests.
- Market-scoped MIC alias tests, including ambiguous `BSE`.
- Default-currency fallback tests for Market-only and MIC-specific contexts.

### Phase 1B: Market Facts Consumers

Purpose: migrate runtime/API consumers onto the canonical Market identity facts from Phase 1A.

Files:

- `backend/app/services/security_master_service.py`
- `backend/app/services/market_calendar_service.py`
- `backend/app/tasks/market_queues.py`
- `backend/app/api/v1/app_runtime.py`
- `backend/app/api/v1/groups.py`
- `backend/app/api/v1/breadth.py`
- `frontend/src/contexts/RuntimeContext.jsx`

Tasks:

- Update `MarketCalendarService` to use MIC Facts; existing Market-level calls resolve to primary MIC.
- Update `SecurityMaster` to use the Market-scoped MIC alias resolver.
- Update queue supported Markets to derive from Market Catalog.
- Move hardcoded endpoint support sets to Market Catalog capability queries:
  - `breadth=True`
  - `group_rankings=True`
  - `feature_snapshot=True`
  - `official_universe=True`
- Update runtime capabilities so frontend market options come from the backend catalog in normal operation.
- Runtime capabilities expose all supported Markets from Market Catalog; enabled state remains in Runtime Preferences and may be layered onto UI options separately.
- Reduce frontend fallback catalog to a minimal emergency fallback and protect it with a backend-generated fixture or drift test.

Acceptance:

- Adding a Market in Market Catalog updates runtime capabilities, queue supported Markets, endpoint capability filters, registry lookups, and frontend options without local list edits.
- API error messages list supported Markets from catalog capability queries.

Suggested tests:

- Runtime capabilities payload snapshot test.
- Frontend RuntimeContext normalization test using backend-like payload.
- Groups and breadth endpoint tests for capability-gated Markets.
- MarketCalendarService MIC and primary-MIC fallback tests.

### Phase 2: Per-Row Currency and FX Contract

Purpose: remove the latent single-currency Market assumption before multi-currency Markets.

Files:

- `backend/app/services/fx_service.py`
- `backend/app/services/fundamentals_cache_service.py`
- `backend/app/services/security_master_service.py`
- `backend/app/services/*_universe_ingestion_adapter.py`
- `backend/app/services/provider_snapshot_service.py`
- `backend/tests/unit/test_fx_service.py`
- `backend/tests/unit/test_fundamentals_completeness_integration.py`

Tasks:

- Change `_enrich_with_fx_normalization(data, market)` to `_enrich_with_fx_normalization(data, currency, *, market=None)` or equivalent.
- Resolve currency from `StockUniverse.currency` or provider snapshot row metadata before FX arithmetic.
- Keep `currency_for_market()` only for boot-time paths with no row context; rename it to default-currency language or document it as fallback-only.
- Add catalog drift test: every distinct `StockUniverse.currency` observed for a Market must be in `MarketCatalogEntry.supported_currencies`.
- Add MIC facts drift test: active rows' denormalized timezone must match MIC facts for their MIC, except documented exceptions.
- Ensure provider snapshot and fundamentals refresh paths pass row currency into FX enrichment.
- Ensure missing row currency fails closed to null USD columns plus metadata, unless the caller explicitly opts into default fallback.

Acceptance:

- FX normalization no longer calls `currency_for_market(market)` when a row currency is available.
- A multi-currency Market can store EUR, NOK, GBP, and USD rows without wrong USD normalization.
- Existing single-currency Markets keep current outputs.

Suggested tests:

- Unit test for HKD row in HK and USD row in US.
- Regression test for mixed-currency synthetic Market rows.
- Test that missing FX rate records unavailable metadata and null USD fields.
- Test that catalog supported currencies include all seeded Universe row currencies.

### Phase 3: Universe Ingestion Pipeline

Purpose: keep market-specific source parsing but centralize lifecycle, persistence, reconciliation, and telemetry.

Files:

- New: `backend/app/domain/universe/ingestion.py` or `backend/app/services/universe_ingestion_pipeline.py`
- New: `backend/app/domain/universe/listing_tiers.py`
- New: `backend/app/services/universe_sources/`
- Existing:
  - `backend/app/services/official_market_universe_source_service.py`
  - `backend/app/tasks/universe_tasks.py`
  - `backend/app/services/stock_universe_service.py`
  - `backend/app/services/*_universe_ingestion_adapter.py`

Target Modules:

- `UniverseSourceAdapter`: fetches or loads a raw source snapshot for one Market.
- `UniverseCanonicalizer`: turns raw rows into canonical accepted/rejected rows.
- `UniversePersistence`: upserts `StockUniverse`, writes `StockUniverseStatusEvent`, records reconciliation, applies deactivation policy.
- `UniverseIngestionPipeline`: orchestrates the lifecycle and emits one common result shape.

Tasks:

- Define one canonical row model shared by all market canonicalizers. Keep market-specific optional metadata in `source_metadata`.
- Add minimal ListingTierRegistry for ingestion normalization: canonical key, label, Market, optional MIC, and source aliases.
- Include `listing_tier: str | None` in the canonical row model and persist it as queryable Universe row metadata when the migration lands.
- Add an invariant test that active Universe rows do not duplicate `(market, mic, local_code)`.
- Add `event_type` to Universe audit events so Listing Tier changes are recorded without overloading active/inactive lifecycle status.
- Move repeated accepted/rejected row result shape into one shared model.
- Replace `_ingest_official_snapshot()` market `if` chain with adapter lookup from Market Catalog capability or a registry.
- Move repeated upsert/reconciliation blocks out of `StockUniverseService.ingest_*_snapshot_rows()` into shared persistence code.
- Keep market-specific source rules in small Adapters:
  - HK code normalization
  - JP section filtering
  - CN board inference
  - CA/DE/SG instrument exclusions
- Preserve strict/rejected-row behavior and deactivation circuit breakers.
- Emit `listing_tier_changed` audit events with previous/new tier payload using ADR 0003's audit-log approach.

Acceptance:

- Adding a new official-source Market requires adding one source/canonicalizer Adapter and registering it.
- Reconciliation, status events, telemetry, deactivation safety, and result payloads are common across Markets.
- Existing HK, IN, JP, KR, TW, CN, CA, DE, and SG ingestion tests keep passing after migration.
- US Finviz ingestion can remain on the legacy path during this phase, but the shared canonical row and persistence model must be able to support US in a later migration.

Suggested tests:

- Golden canonicalization tests per Market remain market-specific.
- Shared pipeline tests cover accepted rows, rejected rows, upsert, update, deactivation, and reconciliation.
- Listing Tier tests cover insert, update, null-for-unsupported Markets, and audit event emission on tier changes.
- ListingTierRegistry tests cover source-label normalization into canonical tier keys.
- Task tests verify `refresh_official_market_universe(market=...)` dispatches through the pipeline and emits standard activity.

### Phase 4: Provider Data Plans

Purpose: turn provider routing from passive policy into executable plans.

Files:

- New: `backend/app/domain/providers/data_plan.py`
- New: `backend/app/services/provider_adapters/`
- Existing:
  - `backend/app/services/provider_routing_policy.py`
  - `backend/app/services/bulk_data_fetcher.py`
  - `backend/app/services/data_source_service.py`
  - `backend/app/services/hybrid_fundamentals_service.py`
  - `backend/app/services/price_cache_service.py`
  - `backend/app/services/fundamentals_cache_service.py`
  - `backend/app/services/field_capability_registry.py`

Target Modules:

- `ProviderDataPlanRegistry`: returns the ordered provider plan for `(market, dataset)` with optional `(market, mic, dataset)` overrides.
- `PriceProviderAdapter`: yfinance, KRX, CN native providers.
- `FundamentalsProviderAdapter`: Finviz, yfinance, KRX, OpenDART, AKShare/BaoStock.
- `ProviderExecutionResult`: common success, partial, missing, error, provider metadata shape.
- `PLAN_VERSION`: provider execution semantics version stored in fetch provenance.

Tasks:

- Keep provider policy versioning, but move execution decisions into dataset-specific plans:
  - prices
  - fundamentals
  - growth
  - ownership/sentiment if needed later
- Keep field-level support in `FieldCapabilityRegistryService`; provider plans should expose provider names and execution behavior, not a field matrix.
- Store `provider_plan_version` in price/fundamentals provenance separately from field capability registry version.
- Treat provider plan version as provenance-only by default; add explicit per-dataset refresh policy for changes that materially affect stored values.
- Replace CN/KR special branches in `BulkDataFetcher` with plan execution.
- Replace CN/KR special branches in `DataSourceService` and `HybridFundamentalsService` with fundamentals plan execution.
- Let `FieldCapabilityRegistryService` derive market/provider support from the provider plan registry where possible.
- Do not put provider order or field-level support into the Market Catalog.
- Preserve per-market rate budget and circuit breaker keys.
- Ensure fallback rules are explicit, e.g. CN BJSE does not fallback to Yahoo.
- Add MIC override tests before adding any aggregated multi-MIC Market whose provider behavior differs by venue.

Acceptance:

- Provider order for every Market and dataset is tested in one place.
- Callers execute a provider plan instead of knowing CN/KR/yfinance/Finviz details.
- Telemetry can report provider plan version, primary provider, fallback provider, and failure reason consistently.
- Rows fetched under older provider execution semantics are explainable through `provider_plan_version`.
- Cache refresh due to provider-plan changes is opt-in per dataset/change, not automatic for every version bump.

Suggested tests:

- Plan registry tests for US, HK, KR, CN, CA, DE, SG.
- Price refresh tests that KRX/CN/yfinance fallback behavior is unchanged.
- Fundamentals refresh tests that Finviz is skipped for non-US and CN/KR native providers are attempted first.
- Field capability tests derive expected market support from plan facts.

### Phase 5: Universe, API, and Frontend Contract Standardization

Purpose: remove local market/exchange/index contract drift at the API and UI edges.

Files:

- `backend/app/schemas/universe.py`
- `backend/app/services/universe_resolver.py`
- `backend/app/services/universe_compat_adapter.py`
- `backend/app/api/v1/scans.py`
- `backend/app/api/v1/groups.py`
- `backend/app/api/v1/breadth.py`
- `frontend/src/contexts/RuntimeContext.jsx`
- `frontend/src/features/scan/universeSelection.js`
- `frontend/src/features/scan/filterOptions.js`

Tasks:

- Keep `UniverseDefinition` wire payload backward-compatible, but validate market, MIC, Market-scoped legacy exchange alias, and index against backend catalog/registry facts instead of hardcoded enums.
- Add Listing Tier as an optional selector on Market/MIC Universe definitions, not a standalone Universe type.
- Add or reuse an IndexRegistry for canonical index definitions; runtime capabilities may expose derived index summaries.
- Add a lightweight ListingTierRegistry for canonical tier definitions; runtime capabilities may expose derived tier summaries.
- Keep benchmark selection in BenchmarkRegistryService or a dedicated Benchmark Registry, not IndexRegistry.
- Preserve `UniverseDefinition.ALL` as all active rows globally; Bootstrap and daily jobs must use explicit Market-scoped Universes.
- Preserve the one-Scan-one-Universe model. Multi-Market Universes use row-level Market/MIC/currency and mixed-market scan policy rather than being split into implicit per-Market scans.
- Introduce `mic` as the canonical new request field while preserving `exchange` as a deprecated legacy alias.
- Deprecate `UniverseDefinition.EXCHANGE` as a public concept; normalize legacy exchange payloads into Market/MIC semantics internally.
- Prefer `UniverseDefinition.MARKET` with optional `mic` and `listing_tier` for new payloads rather than adding a standalone MIC Universe type immediately.
- Reject requests that provide both `mic` and `exchange` when the Market-scoped alias does not resolve to the same MIC.
- Require Market context for legacy `exchange` alias resolution unless the alias is explicitly marked globally unambiguous.
- Expose catalog-backed Universe options through runtime capabilities:
  - Markets
  - canonical MICs
  - MIC aliases under explicit alias fields
  - indexes
  - Listing Tier filters where supported
  - feature capabilities per Market
- Do not expose provider execution order in normal frontend runtime capabilities; expose field/market availability summaries instead.
- Keep provider plan details for operations, diagnostics, provenance, and explainability endpoints.
- Keep enabled/disabled runtime state separate from catalog facts in the payload shape.
- Make frontend universe selectors consume runtime capabilities instead of local option lists.
- Show all supported Markets in scan selection surfaces, but disable non-enabled or non-scan-ready Markets and provide an action path to enable, Bootstrap, or refresh them.
- Expose Listing Tier options grouped by Market and by MIC when a Market has MIC-specific tier systems.
- Store canonical `listing_tier` keys on Universe rows, not raw source tier labels.
- Keep backend scan admission authoritative for readiness/freshness rejection.
- Expose scan readiness summaries through a separate live endpoint, not through runtime capabilities.
- Start with catalog-backed option readiness, e.g. `GET /scan/readiness/options`; arbitrary `UniverseDefinition` readiness via `POST /scan/readiness` can follow if scan creation rejection reasons are not enough.
- Keep Phase 5 readiness work thin: expose enabled state, active Universe availability, freshness summary where available, and blocking workload state. Deeper scan-admission refactoring is a follow-up.
- Make API docs and query descriptions derive from capability facts.
- Add compatibility tests for legacy payloads:
  - `"all"`
  - `"market:HK"`
  - `"exchange:NYSE"`
  - typed `UniverseDefinition`

Acceptance:

- New Market options appear in scan UI from backend runtime payload.
- API validation errors and OpenAPI descriptions use catalog-derived supported values.
- Legacy scan payloads continue to resolve.
- New code uses MIC terminology where the data model is canonical, while old `exchange` payloads remain accepted.

Suggested tests:

- Schema tests for catalog-backed validation.
- Universe resolver tests for Market, MIC/exchange, Index, Custom, and Test.
- Frontend tests for scan universe selector rendering catalog-provided Markets and indexes.
- API contract tests for legacy and new payloads.

## Work Breakdown Into Issues

Created beads epic:

- `StockScreenClaude-mh`: `P1 epic` - Market harmonization and standardization program.

Created beads issues:

1. `StockScreenClaude-mh.1` - `P1 task`: Add Market Catalog drift guards.
2. `StockScreenClaude-mh.2` - `P1 task`: Add Market Catalog canonical MIC, supported currencies, and MIC Facts.
3. `StockScreenClaude-mh.3` - `P1 task`: Implement Market-scoped MIC alias resolver and ambiguity tests.
4. `StockScreenClaude-mh.4` - `P1 task`: Derive registry, queues, and runtime Market facts from Market Catalog.
5. `StockScreenClaude-mh.5` - `P1 task`: Move MarketCalendarService to MIC Facts with primary-MIC fallback.
6. `StockScreenClaude-mh.6` - `P1 task`: Move endpoint allowlists to Market Capability queries.
7. `StockScreenClaude-mh.7` - `P1 task`: Move FX enrichment to row currency.
8. `StockScreenClaude-mh.8` - `P1 task`: Add nullable `listing_tier` Universe row field and audit `event_type` support.
9. `StockScreenClaude-mh.9` - `P1 task`: Add shared Universe canonical row/result models.
10. `StockScreenClaude-mh.10` - `P1 task`: Add UniverseIngestionPipeline and migrate SG as tracer bullet.
11. `StockScreenClaude-mh.11` - `P1 task`: Migrate remaining official-source Markets onto UniverseIngestionPipeline.
12. `StockScreenClaude-mh.12` - `P2 task`: Migrate US Finviz Universe ingestion onto shared UniversePersistence.
13. `StockScreenClaude-mh.13` - `P1 task`: Add ProviderDataPlanRegistry for price data.
14. `StockScreenClaude-mh.14` - `P1 task`: Add ProviderDataPlanRegistry for fundamentals data.
15. `StockScreenClaude-mh.15` - `P2 task`: Derive field capability registry from provider plans.
16. `StockScreenClaude-mh.16` - `P1 task`: Catalog-backed UniverseDefinition validation.
17. `StockScreenClaude-mh.17` - `P1 task`: Runtime capabilities expose catalog-backed Universe options.
18. `StockScreenClaude-mh.18` - `P1 task`: Frontend scan controls consume runtime capability options.

Dependencies:

- `StockScreenClaude-mh.1` blocks all other child tasks.
- `StockScreenClaude-mh.2` blocks `StockScreenClaude-mh.3`, `StockScreenClaude-mh.4`, `StockScreenClaude-mh.5`, `StockScreenClaude-mh.7`, `StockScreenClaude-mh.16`, and `StockScreenClaude-mh.17`.
- `StockScreenClaude-mh.3` blocks `StockScreenClaude-mh.4` and `StockScreenClaude-mh.16`.
- `StockScreenClaude-mh.4` blocks `StockScreenClaude-mh.5`, `StockScreenClaude-mh.6`, and `StockScreenClaude-mh.17`.
- `StockScreenClaude-mh.5` blocks MIC-aware freshness/calendar work and any aggregated multi-MIC Market.
- `StockScreenClaude-mh.7` should land before any multi-currency Market work.
- `StockScreenClaude-mh.8` blocks `StockScreenClaude-mh.9`.
- `StockScreenClaude-mh.9` blocks `StockScreenClaude-mh.10` and `StockScreenClaude-mh.11`; `StockScreenClaude-mh.10` also blocks `StockScreenClaude-mh.11`.
- `StockScreenClaude-mh.12` follows `StockScreenClaude-mh.11` and is not required before provider-plan work.
- `StockScreenClaude-mh.13` can run in parallel with `StockScreenClaude-mh.14` after `StockScreenClaude-mh.1`.
- `StockScreenClaude-mh.15` follows both provider-plan tasks.
- `StockScreenClaude-mh.17` blocks `StockScreenClaude-mh.18`.

## Verification Gates

Backend:

```bash
cd backend
source venv/bin/activate
pytest tests/unit/domain/markets tests/unit/test_fx_service.py tests/unit/test_provider_routing_policy.py tests/unit/test_field_capability_registry.py
pytest tests/unit/test_universe_resolver.py tests/unit/test_universe_tasks.py tests/unit/test_stock_universe_service.py
pytest tests/unit/test_fundamentals_cache_service_metadata_backfill.py tests/unit/test_scan_create_endpoint.py
```

Frontend:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
cd frontend
npm run test:run -- RuntimeContext scan universeSelection
npm run lint
```

End-to-end smoke:

- Bootstrap enabled Markets `US,HK,IN,JP,TW,CN,KR,CA,DE,SG`.
- Confirm each enabled Market has a populated active Universe.
- Confirm price refresh uses the expected provider plan per Market.
- Confirm fundamentals refresh writes field provenance, completeness, row currency, `market_cap_usd`, `adv_usd`, and `fx_metadata`.
- Confirm scan UI options match backend runtime capabilities.

## Rollout Notes

- Land Phase 0 first so later changes fail fast on drift.
- Land Phase 1 and Phase 2 before adding any multi-currency Market.
- Use a tracer-bullet migration for Universe ingestion: migrate one low-risk Market first, then port the rest.
- Use SG as the UniverseIngestionPipeline tracer-bullet Market, then migrate DE/CA, HK/JP/TW, and KR/CN last.
- Keep compatibility aliases for `exchange` while introducing MIC terminology in new internal Modules.
- Update ADR 0002 status once the code uses `supported_currencies` and row-currency FX end to end.
