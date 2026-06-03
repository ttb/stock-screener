"""Unit tests for the one-time universe sector/industry backfill script core."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.stock_universe import StockUniverse
from app.scripts.backfill_universe_sector_industry import backfill_universe


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add(session, symbol, market, sector, industry, is_active=True):
    session.add(StockUniverse(
        symbol=symbol, market=market, sector=sector, industry=industry, is_active=is_active
    ))
    session.commit()


_FETCH = {
    "0700.HK": {"sector": "Communication Services", "industry": "Internet Content & Information"},
    "600519.SS": {"sector": "Consumer Defensive", "industry": "Beverages - Wineries & Distilleries"},
    "9988.HK": {"sector": "Consumer Cyclical", "industry": "Internet Retail"},
}


def _fetch(symbol):
    return _FETCH.get(symbol)


def test_backfill_fills_missing_and_skips_populated():
    session = _session()
    _add(session, "0700.HK", "HK", "", "")                 # missing → backfill
    _add(session, "600519.SS", "CN", "Other", None)        # placeholder → backfill
    _add(session, "AAPL", "US", "Technology", "Software")   # real → skipped (not a candidate)

    stats = backfill_universe(session, fetch_fundamentals=_fetch)

    assert stats["candidates"] == 2          # AAPL is not a candidate
    assert stats["filled"] == 2
    rows = {r.symbol: r for r in session.query(StockUniverse).all()}
    assert rows["0700.HK"].sector == "Communication Services"
    assert rows["600519.SS"].industry == "Beverages - Wineries & Distilleries"
    assert rows["AAPL"].sector == "Technology"  # untouched


def test_market_filter_and_limit():
    session = _session()
    _add(session, "0700.HK", "HK", "", "")
    _add(session, "9988.HK", "HK", "", "")
    _add(session, "600519.SS", "CN", "Other", None)

    stats = backfill_universe(session, fetch_fundamentals=_fetch, market="hk", limit=1)
    assert stats["candidates"] == 1   # HK only, capped at 1 of the 2 HK candidates
    assert stats["filled"] == 1
    # Exactly one HK row was filled; the other was dropped by the limit (still empty),
    # and CN was excluded by the market filter.
    hk_filled = [
        r for r in session.query(StockUniverse).filter_by(market="HK").all()
        if (r.sector or "")
    ]
    assert len(hk_filled) == 1
    assert (session.query(StockUniverse).filter_by(symbol="600519.SS").first().sector) == "Other"


def test_dry_run_reports_without_persisting():
    session = _session()
    _add(session, "0700.HK", "HK", "", "")

    stats = backfill_universe(session, fetch_fundamentals=_fetch, dry_run=True)
    assert stats["filled"] == 1 and stats["dry_run"] is True
    # rolled back → not persisted
    assert (session.query(StockUniverse).filter_by(symbol="0700.HK").first().sector or "") == ""


def test_counts_errors_for_raises_and_none_returns():
    # get_fundamentals returns None on failure (doesn't re-raise); both a raised
    # exception AND a None return must count as errors, not silent "not filled".
    session = _session()
    _add(session, "0700.HK", "HK", "", "")
    _add(session, "RAISE.HK", "HK", "", "")
    _add(session, "NONE.HK", "HK", "", "")

    def flaky(symbol):
        if symbol == "RAISE.HK":
            raise RuntimeError("provider down")
        if symbol == "NONE.HK":
            return None  # the common failure mode
        return _fetch(symbol)

    stats = backfill_universe(session, fetch_fundamentals=flaky)
    assert stats["candidates"] == 3
    assert stats["filled"] == 1
    assert stats["errors"] == 2  # both RAISE.HK and NONE.HK
