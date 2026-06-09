"""Persistence boundary for local runtime bootstrap task manifests."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..models.app_settings import AppSetting

BOOTSTRAP_RUN_KEY = "runtime.activity.bootstrap_run"
RUNTIME_ACTIVITY_CATEGORY = "runtime_activity"
BOOTSTRAP_RUN_DESCRIPTION = "Latest local runtime bootstrap run task manifest."


@dataclass(frozen=True)
class BootstrapRunManifest:
    primary_market: str
    enabled_markets: tuple[str, ...]
    primary_task_id: str
    market_task_ids: Mapping[str, str]
    queued_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "primary_market", str(self.primary_market).upper())
        object.__setattr__(
            self,
            "enabled_markets",
            tuple(str(market).upper() for market in self.enabled_markets),
        )
        object.__setattr__(
            self,
            "market_task_ids",
            {
                str(market).upper(): task_id
                for market, task_id in self.market_task_ids.items()
            },
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "BootstrapRunManifest":
        return cls(
            primary_market=str(payload["primary_market"]),
            enabled_markets=tuple(payload.get("enabled_markets") or ()),
            primary_task_id=str(payload["primary_task_id"]),
            market_task_ids=dict(payload.get("market_task_ids") or {}),
            queued_at=(
                str(payload["queued_at"])
                if payload.get("queued_at") is not None
                else None
            ),
        )

    @classmethod
    def create(
        cls,
        *,
        primary_market: str,
        enabled_markets: Iterable[str],
        primary_task_id: str,
        market_task_ids: Mapping[str, str],
        queued_at: str | None = None,
    ) -> "BootstrapRunManifest":
        return cls(
            primary_market=primary_market,
            enabled_markets=tuple(enabled_markets),
            primary_task_id=primary_task_id,
            market_task_ids=dict(market_task_ids),
            queued_at=queued_at,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "primary_market": self.primary_market,
            "enabled_markets": list(self.enabled_markets),
            "primary_task_id": self.primary_task_id,
            "market_task_ids": dict(self.market_task_ids),
        }
        if self.queued_at is not None:
            payload["queued_at"] = self.queued_at
        return payload


class BootstrapRunManifestRepository:
    def load(self, db: Session) -> BootstrapRunManifest | None:
        setting = db.query(AppSetting).filter(AppSetting.key == BOOTSTRAP_RUN_KEY).first()
        if setting is None:
            return None
        try:
            payload = json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        return BootstrapRunManifest.from_payload(payload)

    def save(
        self,
        db: Session,
        manifest: BootstrapRunManifest,
    ) -> dict[str, Any]:
        encoded = json.dumps(manifest.to_payload())
        setting = db.query(AppSetting).filter(AppSetting.key == BOOTSTRAP_RUN_KEY).first()
        if setting is None:
            setting = AppSetting(
                key=BOOTSTRAP_RUN_KEY,
                value=encoded,
                category=RUNTIME_ACTIVITY_CATEGORY,
                description=BOOTSTRAP_RUN_DESCRIPTION,
            )
            db.add(setting)
        else:
            setting.value = encoded
            setting.category = RUNTIME_ACTIVITY_CATEGORY
            setting.description = BOOTSTRAP_RUN_DESCRIPTION
        db.commit()
        return manifest.to_payload()
