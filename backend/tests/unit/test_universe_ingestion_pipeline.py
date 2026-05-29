from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domain.universe.ingestion import (
    CanonicalUniverseIngestionResult,
    CanonicalUniverseRow,
    RejectedUniverseRow,
    UniverseSourceProvenance,
)
from app.models.stock_universe import (
    StockUniverse,
    StockUniverseStatusEvent,
    UNIVERSE_EVENT_LISTING_TIER_CHANGED,
    UNIVERSE_EVENT_STATUS_CHANGED,
    UNIVERSE_STATUS_ACTIVE,
)
from app.services.stock_universe_service import StockUniverseService
from app.services.universe_ingestion_pipeline import (
    UniverseIngestionPipeline,
    UniversePersistence,
)


class _FakeCanonicalizer:
    def __init__(self, result: CanonicalUniverseIngestionResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def canonicalize_rows(self, rows, **kwargs):
        self.calls.append({"rows": list(rows), **kwargs})
        return self.result


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _row(
    symbol: str,
    *,
    local_code: str,
    listing_tier: str | None = None,
    source_row_number: int = 1,
) -> CanonicalUniverseRow:
    return CanonicalUniverseRow(
        symbol=symbol,
        name=f"{symbol} name",
        market="SG",
        mic="XSES",
        local_code=local_code,
        currency="SGD",
        timezone="Asia/Singapore",
        listing_tier=listing_tier,
        sector="Banks",
        industry="Banking",
        market_cap=100.0,
        provenance=UniverseSourceProvenance(
            source_name="sgx_official",
            snapshot_id="sgx-2026-05-29",
            snapshot_as_of="2026-05-29",
            source_symbol=local_code,
            source_row_number=source_row_number,
            source_metadata={"row_counts": {"xses": 2}},
            lineage_hash=f"lineage-{local_code}",
            row_hash=f"row-{local_code}",
        ),
    )


def test_pipeline_persists_rows_reconciliation_and_listing_tier_audit() -> None:
    TestingSessionLocal = _make_session()
    db = TestingSessionLocal()
    db.add(
        StockUniverse(
            symbol="D05.SI",
            name="DBS old",
            market="SG",
            exchange="XSES",
            currency="SGD",
            timezone="Asia/Singapore",
            local_code="D05",
            listing_tier="mainboard",
            is_active=True,
            status=UNIVERSE_STATUS_ACTIVE,
            source="sg_ingest",
        )
    )
    db.commit()

    canonicalizer = _FakeCanonicalizer(
        CanonicalUniverseIngestionResult(
            canonical_rows=(
                _row("D05.SI", local_code="D05", listing_tier="catalist"),
                _row("O39.SI", local_code="O39", source_row_number=2),
            )
        )
    )
    service = StockUniverseService()
    pipeline = UniverseIngestionPipeline(
        canonicalizers={"SG": canonicalizer},
        persistence=UniversePersistence.for_stock_universe_service(service),
    )

    stats = pipeline.ingest_snapshot_rows(
        db,
        market="SG",
        rows=[{"symbol": "D05"}, {"symbol": "O39"}],
        source_name="sgx_official",
        snapshot_id="sgx-2026-05-29",
        snapshot_as_of="2026-05-29",
        source_metadata={"row_counts": {"xses": 2}},
        strict=True,
    )

    assert canonicalizer.calls[0]["source_name"] == "sgx_official"
    assert stats["added"] == 1
    assert stats["updated"] == 1
    assert stats["total"] == 2
    assert stats["rejected"] == 0
    assert stats["canonical_rows"][0]["exchange"] == "XSES"
    assert stats["canonical_rows"][0]["source_symbol"] == "D05"
    assert stats["reconciliation"]["counts"]["added"] == 2

    existing = db.query(StockUniverse).filter_by(symbol="D05.SI").one()
    added = db.query(StockUniverse).filter_by(symbol="O39.SI").one()
    assert existing.listing_tier == "catalist"
    assert added.exchange == "XSES"
    assert added.listing_tier is None

    events = db.query(StockUniverseStatusEvent).order_by(
        StockUniverseStatusEvent.id.asc()
    ).all()
    assert [event.event_type for event in events] == [
        UNIVERSE_EVENT_LISTING_TIER_CHANGED,
        UNIVERSE_EVENT_STATUS_CHANGED,
    ]
    tier_payload = json.loads(events[0].payload_json)
    assert tier_payload["previous"] == "mainboard"
    assert tier_payload["current"] == "catalist"
    assert tier_payload["snapshot_id"] == "sgx-2026-05-29"
    db.close()


def test_pipeline_strict_mode_raises_for_rejected_rows() -> None:
    TestingSessionLocal = _make_session()
    db = TestingSessionLocal()
    canonicalizer = _FakeCanonicalizer(
        CanonicalUniverseIngestionResult(
            rejected_rows=(
                RejectedUniverseRow(
                    source_row_number=1,
                    source_symbol="BAD",
                    reason="Invalid SG symbol",
                ),
            )
        )
    )
    pipeline = UniverseIngestionPipeline(
        canonicalizers={"SG": canonicalizer},
        persistence=UniversePersistence.for_stock_universe_service(
            StockUniverseService()
        ),
    )

    with pytest.raises(ValueError, match="SG ingestion rejected 1 row"):
        pipeline.ingest_snapshot_rows(
            db,
            market="SG",
            rows=[{"symbol": "BAD"}],
            source_name="sgx_official",
            snapshot_id="sgx-2026-05-29",
            strict=True,
        )
    db.close()
