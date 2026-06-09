"""Price refresh planning for GitHub-seeded and live market refreshes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from .price_history_coverage import PriceHistoryCoverage, classify_price_history


STALE_PRICE_TOP_UP_PERIOD = "7d"
NO_HISTORY_PRICE_BOOTSTRAP_PERIOD = "2y"


class PriceRefreshMode(str, Enum):
    AUTO = "auto"
    FULL = "full"
    BOOTSTRAP = "bootstrap"
    DELTA = "delta"

    @classmethod
    def parse(cls, value: "PriceRefreshMode | str") -> "PriceRefreshMode":
        if isinstance(value, cls):
            return value
        return cls(str(value))


class PriceRefreshJobKind(str, Enum):
    AUTO = "auto"
    FULL = "full"
    STALE = "stale"
    NO_HISTORY = "no_history"


class PriceRefreshSource(str, Enum):
    LIVE = "live"
    GITHUB = "github"
    GITHUB_AND_LIVE = "github+live"


class GitHubSeedStatus(str, Enum):
    SUCCESS = "success"
    UP_TO_DATE = "up_to_date"
    MISSING = "missing"
    ERROR = "error"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: Any) -> "GitHubSeedStatus":
        try:
            return cls(str(value))
        except ValueError:
            return cls.UNKNOWN


LIVE_TOP_UP_MODES = frozenset({PriceRefreshMode.BOOTSTRAP, PriceRefreshMode.DELTA})
GITHUB_SYNC_SUCCESS_STATUSES = frozenset({
    GitHubSeedStatus.SUCCESS,
    GitHubSeedStatus.UP_TO_DATE,
})


@dataclass(frozen=True)
class GitHubSeedOutcome:
    status: GitHubSeedStatus
    raw_status: str | None = None
    as_of_date: date | None = None
    source_revision: str | None = None
    reason: str | None = None
    error: str | None = None
    stale_reason: str | None = None

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any] | None
    ) -> "GitHubSeedOutcome | None":
        if not payload:
            return None
        raw_status = str(payload.get("status")) if payload.get("status") is not None else None
        return cls(
            status=GitHubSeedStatus.parse(raw_status),
            raw_status=raw_status,
            as_of_date=_parse_bundle_date(payload.get("as_of_date")),
            source_revision=(
                str(payload["source_revision"])
                if payload.get("source_revision") is not None
                else None
            ),
            reason=str(payload["reason"]) if payload.get("reason") is not None else None,
            error=str(payload["error"]) if payload.get("error") is not None else None,
            stale_reason=(
                str(payload["stale_reason"])
                if payload.get("stale_reason") is not None
                else None
            ),
        )

    @property
    def status_value(self) -> str:
        return self.raw_status or self.status.value

    @property
    def is_success(self) -> bool:
        return self.status in GITHUB_SYNC_SUCCESS_STATUSES

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status_value}
        if self.as_of_date is not None:
            payload["as_of_date"] = self.as_of_date.isoformat()
        if self.source_revision is not None:
            payload["source_revision"] = self.source_revision
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.error is not None:
            payload["error"] = self.error
        if self.stale_reason is not None:
            payload["stale_reason"] = self.stale_reason
        return payload


@dataclass(frozen=True)
class PriceRefreshJob:
    kind: PriceRefreshJobKind
    symbols: tuple[str, ...]
    period: str


@dataclass(frozen=True)
class PriceRefreshPlan:
    symbols: tuple[str, ...]
    jobs: tuple[PriceRefreshJob, ...] = ()
    all_symbols: tuple[str, ...] = ()
    symbol_markets: Mapping[str, str] = field(default_factory=dict)
    github_seed: GitHubSeedOutcome | None = None
    github_seed_used: bool = False
    completion_message: str | None = None

    @property
    def source(self) -> PriceRefreshSource:
        if self.github_seed_used:
            return PriceRefreshSource.GITHUB_AND_LIVE if self.jobs else PriceRefreshSource.GITHUB
        return PriceRefreshSource.LIVE

    @property
    def used_github_seed(self) -> bool:
        return self.github_seed_used

    @property
    def live_refresh_jobs(self) -> tuple[PriceRefreshJob, ...]:
        return self.jobs


def _normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(symbol).upper() for symbol in symbols)


def _parse_bundle_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def build_top_up_jobs(coverage: PriceHistoryCoverage) -> tuple[PriceRefreshJob, ...]:
    jobs: list[PriceRefreshJob] = []
    if coverage.stale:
        jobs.append(
            PriceRefreshJob(
                kind=PriceRefreshJobKind.STALE,
                symbols=coverage.stale,
                period=STALE_PRICE_TOP_UP_PERIOD,
            )
        )
    if coverage.no_history:
        jobs.append(
            PriceRefreshJob(
                kind=PriceRefreshJobKind.NO_HISTORY,
                symbols=coverage.no_history,
                period=NO_HISTORY_PRICE_BOOTSTRAP_PERIOD,
            )
        )
    return tuple(jobs)


def _symbols_from_jobs(jobs: Sequence[PriceRefreshJob]) -> tuple[str, ...]:
    return tuple(symbol for job in jobs for symbol in job.symbols)


def _plan_live_full(symbols: tuple[str, ...]) -> PriceRefreshPlan:
    jobs = (
        PriceRefreshJob(
            kind=PriceRefreshJobKind.FULL,
            symbols=symbols,
            period=NO_HISTORY_PRICE_BOOTSTRAP_PERIOD,
        ),
    ) if symbols else ()
    return PriceRefreshPlan(symbols=symbols, jobs=jobs)


def _plan_live_auto(
    symbols: tuple[str, ...],
    *,
    recently_refreshed_filter: Callable[[Sequence[str]], Sequence[str]] | None,
) -> PriceRefreshPlan:
    refresh_symbols = (
        _normalize_symbols(recently_refreshed_filter(symbols))
        if recently_refreshed_filter is not None
        else symbols
    )
    jobs = (
        PriceRefreshJob(
            kind=PriceRefreshJobKind.AUTO,
            symbols=refresh_symbols,
            period=NO_HISTORY_PRICE_BOOTSTRAP_PERIOD,
        ),
    ) if refresh_symbols else ()
    return PriceRefreshPlan(symbols=refresh_symbols, jobs=jobs)


def _plan_live_top_up(
    db: Session,
    *,
    symbols: tuple[str, ...],
    effective_market: str,
    market_calendar_service,
    github_seed: GitHubSeedOutcome | None = None,
) -> PriceRefreshPlan:
    target_as_of = market_calendar_service.last_completed_trading_day(effective_market)
    coverage = classify_price_history(db, symbols=symbols, as_of_date=target_as_of)
    jobs = build_top_up_jobs(coverage)
    return PriceRefreshPlan(
        symbols=_symbols_from_jobs(jobs),
        jobs=jobs,
        github_seed=github_seed,
    )


def _plan_github_top_up(
    db: Session,
    *,
    symbols: tuple[str, ...],
    effective_market: str,
    github_seed: GitHubSeedOutcome,
    market_calendar_service,
) -> PriceRefreshPlan:
    target_as_of = market_calendar_service.last_completed_trading_day(effective_market)
    github_as_of = github_seed.as_of_date
    coverage = classify_price_history(db, symbols=symbols, as_of_date=target_as_of)
    jobs = build_top_up_jobs(coverage)
    live_symbols = _symbols_from_jobs(jobs)
    completion_message = None
    if not live_symbols:
        completion_message = (
            "GitHub daily price bundle is current - no live fetch needed"
            if github_as_of == target_as_of
            else "All symbols already fresh - no live fetch needed"
        )
    return PriceRefreshPlan(
        symbols=live_symbols,
        jobs=jobs,
        github_seed=github_seed,
        github_seed_used=True,
        completion_message=completion_message,
    )


def plan_price_refresh(
    db: Session,
    *,
    all_symbols: Sequence[str],
    mode: PriceRefreshMode | str,
    effective_market: str,
    market_calendar_service,
    github_seed: GitHubSeedOutcome | None = None,
    recently_refreshed_filter: Callable[[Sequence[str]], Sequence[str]] | None = None,
) -> PriceRefreshPlan:
    """Plan live price-fetch work without performing any fetches."""
    parsed_mode = PriceRefreshMode.parse(mode)
    normalized_symbols = _normalize_symbols(all_symbols)
    if not normalized_symbols:
        return PriceRefreshPlan(
            symbols=(),
            jobs=(),
            completion_message="No active symbols found in universe",
        )

    if parsed_mode is PriceRefreshMode.AUTO:
        plan = _plan_live_auto(
            normalized_symbols,
            recently_refreshed_filter=recently_refreshed_filter,
        )
    elif parsed_mode is PriceRefreshMode.FULL:
        plan = _plan_live_full(normalized_symbols)
    elif github_seed and github_seed.is_success:
        plan = _plan_github_top_up(
            db,
            symbols=normalized_symbols,
            effective_market=effective_market,
            github_seed=github_seed,
            market_calendar_service=market_calendar_service,
        )
    else:
        plan = _plan_live_top_up(
            db,
            symbols=normalized_symbols,
            effective_market=effective_market,
            market_calendar_service=market_calendar_service,
            github_seed=github_seed,
        )

    return replace(plan, all_symbols=normalized_symbols)


def load_active_price_refresh_universe(
    db: Session,
    *,
    market: str | None,
    effective_market: str,
    normalize_market: Callable[[str], str],
) -> tuple[tuple[str, ...], dict[str, str]]:
    from ..models.stock_universe import StockUniverse

    query = db.query(StockUniverse.symbol, StockUniverse.market).filter(
        StockUniverse.is_active == True
    )
    if market is not None:
        query = query.filter(StockUniverse.market == normalize_market(market))
    query = query.order_by(StockUniverse.market_cap.desc().nullslast())
    universe_rows = query.all()
    all_symbols = tuple(row.symbol for row in universe_rows)
    symbol_markets = {
        str(row.symbol).upper(): normalize_market(
            getattr(row, "market", None) or effective_market
        )
        for row in universe_rows
    }
    return all_symbols, symbol_markets


def build_market_price_refresh_plan(
    db: Session,
    *,
    mode: PriceRefreshMode | str,
    market: str | None,
    effective_market: str,
    normalize_market: Callable[[str], str],
    market_calendar_service,
    sync_github_seed: Callable[..., Mapping[str, Any]],
    recently_refreshed_filter: Callable[[Sequence[str]], Sequence[str]] | None = None,
) -> PriceRefreshPlan:
    parsed_mode = PriceRefreshMode.parse(mode)
    all_symbols, symbol_markets = load_active_price_refresh_universe(
        db,
        market=market,
        effective_market=effective_market,
        normalize_market=normalize_market,
    )
    github_seed = None
    if parsed_mode in LIVE_TOP_UP_MODES and all_symbols and market is not None:
        github_seed = GitHubSeedOutcome.from_mapping(
            sync_github_seed(db, market=effective_market, allow_stale=True)
        )
    plan = plan_price_refresh(
        db,
        all_symbols=all_symbols,
        mode=parsed_mode,
        effective_market=effective_market,
        market_calendar_service=market_calendar_service,
        github_seed=github_seed,
        recently_refreshed_filter=recently_refreshed_filter,
    )
    return replace(
        plan,
        all_symbols=all_symbols,
        symbol_markets=symbol_markets,
    )
