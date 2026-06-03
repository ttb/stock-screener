"""Canonical helpers for ``StockUniverse`` sector/industry classification.

Foreign-market ingest lands universe rows without real classification (CN
``sector="Other"``, HK empty), which starves the IBD crosswalk + embedding tiers.
This module is the single home for *what counts as a meaningful sector/industry*
and the two write policies over it, so every universe write path shares one
definition instead of re-deriving "is this missing?" inline.
"""
from __future__ import annotations

import logging
from typing import TypeVar

from sqlalchemy.orm import Session

from ..models.stock_universe import StockUniverse

logger = logging.getLogger(__name__)

# Values that mean "no real classification" — placeholders left by foreign ingest.
_PLACEHOLDER_CLASSIFICATION = frozenset({"", "other", "unknown", "n/a", "none"})

_T = TypeVar("_T")


def is_meaningful_classification(value: object) -> bool:
    """True when ``value`` is a real sector/industry label.

    Blank/``None`` and the placeholder labels (``Other``/``Unknown``/``N/A``/``None``)
    all read as not-meaningful; the membership test is case-insensitive. (``None``
    is caught both by the falsy guard and by ``"none"`` being in the set.)
    """
    return bool(value) and str(value).strip().lower() not in _PLACEHOLDER_CLASSIFICATION


def prefer_meaningful(new: _T, current: _T) -> _T:
    """Return ``new`` when it's a meaningful label, else keep ``current``.

    For ingest/update paths where the incoming source is authoritative for the
    market: a fresh real value wins, but a placeholder ("", "Other", …) must not
    clobber an existing real value — the bug in the older ``new or current`` form,
    which treated the truthy ``"Other"`` as a real value.
    """
    return new if is_meaningful_classification(new) else current


def backfill_universe_classification(
    db: Session, symbol: str, *, sector: object, industry: object
) -> bool:
    """Fill a universe row's sector/industry only where it's currently missing.

    Conservative no-clobber backfill for *enrichment* paths (e.g. yfinance
    fundamentals) that must not override an already-authoritative classification
    (US finviz). Returns True if anything changed.
    """
    if not (is_meaningful_classification(sector) or is_meaningful_classification(industry)):
        return False

    row = db.query(StockUniverse).filter(StockUniverse.symbol == symbol).first()
    if row is None:
        return False

    changed = False
    if is_meaningful_classification(sector) and not is_meaningful_classification(row.sector):
        row.sector = str(sector).strip()
        changed = True
    if is_meaningful_classification(industry) and not is_meaningful_classification(row.industry):
        row.industry = str(industry).strip()
        changed = True
    if changed:
        logger.info("Backfilled StockUniverse sector/industry for %s", symbol)
    return changed
