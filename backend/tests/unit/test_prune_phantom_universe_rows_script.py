"""Unit tests for the phantom universe-row pruning script core."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.stock_universe import StockUniverse, UNIVERSE_STATUS_ACTIVE
from app.scripts.prune_phantom_universe_rows import prune_phantom_universe_rows


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add(session, symbol, exchange, market="TW"):
    session.add(StockUniverse(
        symbol=symbol, exchange=exchange, market=market,
        is_active=True, status=UNIVERSE_STATUS_ACTIVE, status_reason="active",
    ))
    session.commit()


def test_prunes_phantom_two_row_keeping_real_tw():
    # 1240.TWO + XTAI canonicalizes to 1240.TW (exchange wins), which also exists:
    # the .TWO row is a phantom and must be deleted, the genuine .TW kept.
    session = _session()
    _add(session, "1240.TW", "XTAI")
    _add(session, "1240.TWO", "XTAI")

    stats = prune_phantom_universe_rows(session)

    symbols = {r.symbol for r in session.query(StockUniverse).all()}
    assert symbols == {"1240.TW"}
    assert stats["phantoms"] == 1
    assert stats["deleted"] == 1


def test_keeps_genuine_standalone_two_row():
    # A real TPEx security (exchange TPEX) canonicalizes to .TWO == its own symbol
    # and has no .TW sibling: it is NOT a phantom and must be kept.
    session = _session()
    _add(session, "6488.TWO", "TPEX")

    stats = prune_phantom_universe_rows(session)

    assert {r.symbol for r in session.query(StockUniverse).all()} == {"6488.TWO"}
    assert stats["phantoms"] == 0


def test_dry_run_reports_without_deleting():
    session = _session()
    _add(session, "1240.TW", "XTAI")
    _add(session, "1240.TWO", "XTAI")

    stats = prune_phantom_universe_rows(session, dry_run=True)

    assert stats["phantoms"] == 1 and stats["deleted"] == 0
    assert session.query(StockUniverse).count() == 2  # nothing removed


def test_market_filter_scopes_the_sweep():
    session = _session()
    _add(session, "1240.TW", "XTAI")
    _add(session, "1240.TWO", "XTAI")
    _add(session, "0700.HK", "XHKG", market="HK")

    stats = prune_phantom_universe_rows(session, market="hk")

    # HK has no phantom; TW phantom untouched because market-scoped to HK.
    assert stats["phantoms"] == 0
    assert session.query(StockUniverse).count() == 3
