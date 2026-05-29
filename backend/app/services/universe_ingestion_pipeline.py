"""Shared official-source Universe ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Protocol

from sqlalchemy.orm import Session

from ..domain.universe.ingestion import (
    CanonicalUniverseIngestionResult,
    CanonicalUniverseRow,
    RejectedUniverseRow,
)
from ..models.stock_universe import (
    StockUniverse,
    StockUniverseStatusEvent,
    UNIVERSE_EVENT_LISTING_TIER_CHANGED,
    UNIVERSE_STATUS_ACTIVE,
)


class UniverseCanonicalizer(Protocol):
    def canonicalize_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        source_name: str,
        snapshot_id: str,
        snapshot_as_of: str | None = None,
        source_metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalUniverseIngestionResult:
        """Return accepted/rejected canonical rows for one source snapshot."""


@dataclass(frozen=True)
class UniversePersistenceHooks:
    apply_status_transition: Callable[..., bool]
    apply_market_reconciliation_policy: Callable[..., dict[str, Any]]
    build_metadata_event_record: Callable[..., StockUniverseStatusEvent]
    build_status_event_record: Callable[..., StockUniverseStatusEvent]
    bulk_insert_records: Callable[[Session, list[Any]], None]
    record_market_reconciliation_run: Callable[..., dict[str, Any]]


class UniversePersistence:
    """Persist canonical Universe rows and shared reconciliation side effects."""

    def __init__(self, hooks: UniversePersistenceHooks) -> None:
        self._hooks = hooks

    @classmethod
    def for_stock_universe_service(cls, service: Any) -> "UniversePersistence":
        return cls(
            UniversePersistenceHooks(
                apply_status_transition=service._apply_status_transition,
                apply_market_reconciliation_policy=(
                    service._apply_market_reconciliation_policy
                ),
                build_metadata_event_record=service._build_metadata_event_record,
                build_status_event_record=service._build_status_event_record,
                bulk_insert_records=service._bulk_insert_records,
                record_market_reconciliation_run=(
                    service._record_market_reconciliation_run
                ),
            )
        )

    def persist(
        self,
        db: Session,
        *,
        market: str,
        source_name: str,
        snapshot_id: str,
        result: CanonicalUniverseIngestionResult,
        trigger_source: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.utcnow()
        canonical_rows = result.canonical_rows
        canonical_symbols = [row.symbol for row in canonical_rows]
        existing_rows = (
            {
                row.symbol: row
                for row in db.query(StockUniverse)
                .filter(StockUniverse.symbol.in_(canonical_symbols))
                .all()
            }
            if canonical_symbols
            else {}
        )

        added_count = 0
        updated_count = 0
        new_rows: list[StockUniverse] = []
        new_events: list[StockUniverseStatusEvent] = []

        for row in canonical_rows:
            event_payload = self._event_payload(row)
            reason = f"Present in {market} source snapshot {row.provenance.snapshot_id}"
            existing = existing_rows.get(row.symbol)

            if existing is not None:
                self._update_existing_row(
                    db,
                    existing,
                    row=row,
                    now=now,
                    trigger_source=trigger_source,
                    reason=reason,
                    event_payload=event_payload,
                    new_events=new_events,
                )
                updated_count += 1
                continue

            new_rows.append(
                self._new_universe_row(
                    row,
                    now=now,
                    source=trigger_source,
                    reason=reason,
                )
            )
            new_events.append(
                self._hooks.build_status_event_record(
                    symbol=row.symbol,
                    old_status=None,
                    new_status=UNIVERSE_STATUS_ACTIVE,
                    trigger_source=trigger_source,
                    reason=reason,
                    payload=event_payload,
                )
            )
            added_count += 1

        self._hooks.bulk_insert_records(db, new_rows)
        self._hooks.bulk_insert_records(db, new_events)

        reconciliation = self._hooks.record_market_reconciliation_run(
            db,
            market=market,
            source_name=source_name,
            snapshot_id=snapshot_id,
            canonical_rows=canonical_rows,
        )
        reconciliation = self._hooks.apply_market_reconciliation_policy(
            db,
            market=market,
            snapshot_id=snapshot_id,
            trigger_source=trigger_source,
            reconciliation=reconciliation,
            now=now,
        )
        db.commit()

        return {
            "added": added_count,
            "updated": updated_count,
            "reconciliation": reconciliation,
        }

    def _update_existing_row(
        self,
        db: Session,
        existing: StockUniverse,
        *,
        row: CanonicalUniverseRow,
        now: datetime,
        trigger_source: str,
        reason: str,
        event_payload: dict[str, Any],
        new_events: list[StockUniverseStatusEvent],
    ) -> None:
        previous_listing_tier = existing.listing_tier
        existing.name = row.name or existing.name
        existing.market = row.market
        existing.exchange = row.mic
        existing.currency = row.currency
        existing.timezone = row.timezone
        existing.local_code = row.local_code or existing.local_code
        existing.sector = row.sector or existing.sector
        existing.industry = row.industry or existing.industry
        existing.listing_tier = row.listing_tier
        if row.market_cap is not None:
            existing.market_cap = row.market_cap

        if previous_listing_tier != row.listing_tier:
            new_events.append(
                self._hooks.build_metadata_event_record(
                    symbol=row.symbol,
                    event_type=UNIVERSE_EVENT_LISTING_TIER_CHANGED,
                    trigger_source=trigger_source,
                    reason="listing tier changed",
                    payload={
                        **event_payload,
                        "previous": previous_listing_tier,
                        "current": row.listing_tier,
                    },
                )
            )

        self._hooks.apply_status_transition(
            db,
            existing,
            new_status=UNIVERSE_STATUS_ACTIVE,
            trigger_source=trigger_source,
            reason=reason,
            now=now,
            payload=event_payload,
            source=trigger_source,
            clear_failures=True,
            seen_in_source=True,
        )

    @staticmethod
    def _new_universe_row(
        row: CanonicalUniverseRow,
        *,
        now: datetime,
        source: str,
        reason: str,
    ) -> StockUniverse:
        return StockUniverse(
            symbol=row.symbol,
            name=row.name,
            market=row.market,
            exchange=row.mic,
            listing_tier=row.listing_tier,
            currency=row.currency,
            timezone=row.timezone,
            local_code=row.local_code,
            sector=row.sector,
            industry=row.industry,
            market_cap=row.market_cap,
            is_active=True,
            status=UNIVERSE_STATUS_ACTIVE,
            status_reason=reason,
            source=source,
            consecutive_fetch_failures=0,
            added_at=now,
            first_seen_at=now,
            last_seen_in_source_at=now,
            updated_at=now,
        )

    @staticmethod
    def _event_payload(row: CanonicalUniverseRow) -> dict[str, Any]:
        provenance = row.provenance
        return {
            "source_name": provenance.source_name,
            "source_symbol": provenance.source_symbol,
            "source_row_number": provenance.source_row_number,
            "snapshot_id": provenance.snapshot_id,
            "snapshot_as_of": provenance.snapshot_as_of,
            "source_metadata": provenance.source_metadata,
            "lineage_hash": provenance.lineage_hash,
            "row_hash": provenance.row_hash,
            "listing_tier": row.listing_tier,
        }


class UniverseIngestionPipeline:
    """Canonicalize, persist, reconcile, and summarize one market snapshot."""

    def __init__(
        self,
        *,
        canonicalizers: Mapping[str, UniverseCanonicalizer],
        persistence: UniversePersistence,
    ) -> None:
        self._canonicalizers = {
            str(market).strip().upper(): canonicalizer
            for market, canonicalizer in canonicalizers.items()
        }
        self._persistence = persistence

    def ingest_snapshot_rows(
        self,
        db: Session,
        *,
        market: str,
        rows: Iterable[Mapping[str, Any]],
        source_name: str,
        snapshot_id: str,
        snapshot_as_of: str | None = None,
        source_metadata: Mapping[str, Any] | None = None,
        strict: bool = True,
    ) -> dict[str, Any]:
        market_code = str(market or "").strip().upper()
        canonicalizer = self._canonicalizers.get(market_code)
        if canonicalizer is None:
            raise ValueError(f"Universe ingestion is unsupported for market {market!r}")

        result = canonicalizer.canonicalize_rows(
            rows,
            source_name=source_name,
            snapshot_id=snapshot_id,
            snapshot_as_of=snapshot_as_of,
            source_metadata=source_metadata,
        )
        if strict and result.rejected_rows:
            sample = self._rejected_sample(result.rejected_rows)
            raise ValueError(
                f"{market_code} ingestion rejected {len(result.rejected_rows)} "
                f"row(s). {sample}"
            )

        trigger_source = f"{market_code.lower()}_ingest"
        persisted = self._persistence.persist(
            db,
            market=market_code,
            source_name=source_name,
            snapshot_id=snapshot_id,
            result=result,
            trigger_source=trigger_source,
        )
        return self._summary(
            market=market_code,
            source_name=source_name,
            snapshot_id=snapshot_id,
            result=result,
            persisted=persisted,
        )

    @staticmethod
    def _rejected_sample(rejected_rows: tuple[RejectedUniverseRow, ...]) -> str:
        return "; ".join(
            f"row {row.source_row_number}: {row.reason}" for row in rejected_rows[:3]
        )

    @staticmethod
    def _summary(
        *,
        market: str,
        source_name: str,
        snapshot_id: str,
        result: CanonicalUniverseIngestionResult,
        persisted: Mapping[str, Any],
    ) -> dict[str, Any]:
        details_limit = 25
        canonical_preview = result.canonical_rows[:details_limit]
        rejected_preview = result.rejected_rows[:details_limit]
        return {
            "added": persisted["added"],
            "updated": persisted["updated"],
            "total": len(result.canonical_rows),
            "rejected": len(result.rejected_rows),
            "source_name": source_name,
            "snapshot_id": snapshot_id,
            "canonical_rows": [
                {
                    "symbol": row.symbol,
                    "local_code": row.local_code,
                    "exchange": row.mic,
                    "source_symbol": row.provenance.source_symbol,
                    "lineage_hash": row.provenance.lineage_hash,
                    "row_hash": row.provenance.row_hash,
                }
                for row in canonical_preview
            ],
            "rejected_rows": [
                {
                    "source_row_number": row.source_row_number,
                    "source_symbol": row.source_symbol,
                    "reason": row.reason,
                }
                for row in rejected_preview
            ],
            "canonical_rows_truncated": len(result.canonical_rows) > details_limit,
            "rejected_rows_truncated": len(result.rejected_rows) > details_limit,
            "reconciliation": persisted["reconciliation"],
            "pipeline": {
                "market": market,
                "version": "universe-ingestion-pipeline-v1",
            },
        }
