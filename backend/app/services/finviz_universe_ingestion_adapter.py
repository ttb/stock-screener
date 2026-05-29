"""US Finviz universe ingestion adapter for the shared pipeline."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from ..domain.universe.ingestion import (
    CanonicalUniverseIngestionResult,
    CanonicalUniverseRow,
    RejectedUniverseRow,
    UniverseLifecycleMetadata,
    UniverseSourceProvenance,
)
from .security_master_service import security_master_resolver

_APPROVED_FINVIZ_SOURCES: frozenset[str] = frozenset(
    {
        "finviz",
        "finviz_universe",
        "finviz_screener",
        "finviz_nasdaq",
        "finviz_nyse",
        "finviz_amex",
        "finviz_reference_bundle",
    }
)


class FinvizUniverseIngestionAdapter:
    """Normalize Finviz screener rows into canonical US universe rows."""

    @staticmethod
    def normalize_source_name(source_name: str) -> str:
        normalized = (source_name or "").strip().lower().replace("-", "_")
        if not normalized:
            raise ValueError("source_name must be provided")
        return normalized

    @classmethod
    def is_approved_source(cls, source_name: str) -> bool:
        normalized = cls.normalize_source_name(source_name)
        return normalized in _APPROVED_FINVIZ_SOURCES or normalized.startswith("finviz_")

    @staticmethod
    def _normalize_source_symbol(raw_symbol: Any) -> str:
        symbol = str(raw_symbol or "").strip().upper().replace(" ", "")
        if symbol.startswith("$"):
            symbol = symbol[1:]
        return symbol

    @staticmethod
    def _normalize_exchange(raw_exchange: Any) -> str:
        return str(raw_exchange or "").strip().upper() or "NASDAQ"

    @staticmethod
    def _parse_market_cap(raw_value: Any) -> float | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, (int, float)):
            return float(raw_value)

        raw = str(raw_value).strip().upper().replace(",", "")
        if not raw or raw == "-":
            return None

        multiplier = 1.0
        if raw.endswith("B"):
            multiplier = 1e9
            raw = raw[:-1]
        elif raw.endswith("M"):
            multiplier = 1e6
            raw = raw[:-1]
        elif raw.endswith("K"):
            multiplier = 1e3
            raw = raw[:-1]

        try:
            return float(raw) * multiplier
        except ValueError:
            return None

    @staticmethod
    def _hash_payload(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def canonicalize_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        source_name: str,
        snapshot_id: str,
        snapshot_as_of: str | None = None,
        source_metadata: Mapping[str, Any] | None = None,
    ) -> CanonicalUniverseIngestionResult:
        normalized_source_name = self.normalize_source_name(source_name)
        if not self.is_approved_source(normalized_source_name):
            raise ValueError(
                f"Unapproved Finviz source '{source_name}'. "
                "Use a finviz-prefixed source identifier."
            )

        normalized_snapshot_id = (snapshot_id or "").strip()
        if not normalized_snapshot_id:
            raise ValueError("snapshot_id must be provided")

        metadata = dict(source_metadata or {})
        canonical_by_symbol: dict[str, CanonicalUniverseRow] = {}
        rejected_rows: list[RejectedUniverseRow] = []

        for index, raw_row in enumerate(rows, start=1):
            source_symbol = self._normalize_source_symbol(
                raw_row.get("symbol")
                or raw_row.get("ticker")
                or raw_row.get("Ticker")
            )
            if not source_symbol:
                rejected_rows.append(
                    RejectedUniverseRow(
                        source_row_number=index,
                        source_symbol="",
                        reason="Missing symbol/ticker",
                        source_name=normalized_source_name,
                        snapshot_id=normalized_snapshot_id,
                        snapshot_as_of=snapshot_as_of,
                        strict=False,
                    )
                )
                continue

            try:
                exchange = self._normalize_exchange(
                    raw_row.get("exchange") or raw_row.get("Exchange")
                )
                identity = security_master_resolver.resolve_identity(
                    symbol=source_symbol,
                    market="US",
                    exchange=exchange,
                )
                if not identity.mic:
                    raise ValueError(f"Unsupported US exchange '{exchange}'")

                row_name = str(raw_row.get("name") or raw_row.get("Name") or "").strip()
                row_sector = str(raw_row.get("sector") or raw_row.get("Sector") or "").strip()
                row_industry = str(raw_row.get("industry") or raw_row.get("Industry") or "").strip()
                row_market_cap = self._parse_market_cap(
                    raw_row.get("market_cap")
                    or raw_row.get("Market Cap")
                    or raw_row.get("MarketCap")
                )
                row_metadata = {
                    **metadata,
                    "source_exchange": exchange,
                    "canonical_mic": identity.mic,
                }

                lineage_payload = {
                    "source_name": normalized_source_name,
                    "snapshot_id": normalized_snapshot_id,
                    "source_row_number": index,
                    "source_symbol": source_symbol,
                    "canonical_symbol": identity.canonical_symbol,
                }
                canonical_payload = {
                    "symbol": identity.canonical_symbol,
                    "market": identity.market,
                    "exchange": identity.mic,
                    "local_code": identity.local_code,
                    "name": row_name,
                    "sector": row_sector,
                    "industry": row_industry,
                    "market_cap": row_market_cap,
                    "source_name": normalized_source_name,
                    "snapshot_id": normalized_snapshot_id,
                }
                canonical_by_symbol.setdefault(
                    identity.canonical_symbol,
                    CanonicalUniverseRow(
                        symbol=identity.canonical_symbol,
                        name=row_name,
                        market=identity.market,
                        mic=identity.mic,
                        currency=identity.currency,
                        timezone=identity.timezone,
                        local_code=identity.local_code,
                        sector=row_sector,
                        industry=row_industry,
                        market_cap=row_market_cap,
                        lifecycle=UniverseLifecycleMetadata(
                            status_reason="Present in Finviz universe sync",
                        ),
                        provenance=UniverseSourceProvenance(
                            source_name=normalized_source_name,
                            source_symbol=source_symbol,
                            source_row_number=index,
                            snapshot_id=normalized_snapshot_id,
                            snapshot_as_of=snapshot_as_of,
                            source_metadata=row_metadata,
                            lineage_hash=self._hash_payload(lineage_payload),
                            row_hash=self._hash_payload(canonical_payload),
                        ),
                    ),
                )
            except ValueError as exc:
                rejected_rows.append(
                    RejectedUniverseRow(
                        source_row_number=index,
                        source_symbol=source_symbol,
                        reason=str(exc),
                        source_name=normalized_source_name,
                        snapshot_id=normalized_snapshot_id,
                        snapshot_as_of=snapshot_as_of,
                        strict=False,
                    )
                )

        return CanonicalUniverseIngestionResult(
            canonical_rows=tuple(
                sorted(canonical_by_symbol.values(), key=lambda row: row.symbol)
            ),
            rejected_rows=tuple(
                sorted(rejected_rows, key=lambda row: row.source_row_number or 0)
            ),
        )


finviz_universe_ingestion_adapter = FinvizUniverseIngestionAdapter()
