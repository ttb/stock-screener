"""Presentation helpers for runtime activity status responses."""

from __future__ import annotations

from typing import Any

ACTIVE_STATUSES = {"queued", "running"}

STAGE_SEQUENCE = (
    "universe",
    "prices",
    "fundamentals",
    "breadth",
    "groups",
    "scan",
)


def _bootstrap_progress_percent(record: dict[str, Any] | None) -> float:
    if record is None:
        return 0.0
    stage_key = record.get("stage_key")
    if stage_key not in STAGE_SEQUENCE:
        return 0.0
    stage_index = STAGE_SEQUENCE.index(stage_key)
    raw_percent = record.get("percent")
    if raw_percent is not None:
        stage_fraction = max(0.0, min(float(raw_percent), 100.0)) / 100.0
    elif record.get("status") == "completed":
        stage_fraction = 1.0
    else:
        stage_fraction = 0.0
    return round(((stage_index + stage_fraction) / len(STAGE_SEQUENCE)) * 100.0, 2)


def _is_active_bootstrap_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("lifecycle") == "bootstrap"
        and payload.get("status") in ACTIVE_STATUSES
    )


def build_runtime_activity_status(
    *,
    bootstrap_status,
    bootstrap_run: dict[str, Any],
    market_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    enabled_markets = list(bootstrap_status.enabled_markets)
    primary_market = bootstrap_status.primary_market
    active_markets = [
        payload["market"]
        for payload in market_payloads
        if payload.get("status") in ACTIVE_STATUSES
    ]
    has_failed = any(payload.get("status") == "failed" for payload in market_payloads)
    summary_status = "warning" if has_failed else ("active" if active_markets else "idle")

    primary_payload = next(
        (payload for payload in market_payloads if payload["market"] == primary_market),
        None,
    )
    secondary_active = [
        payload["market"]
        for payload in market_payloads
        if payload["market"] != primary_market and _is_active_bootstrap_payload(payload)
    ]
    secondary_active_payload = next(
        (
            payload
            for payload in market_payloads
            if payload["market"] != primary_market and _is_active_bootstrap_payload(payload)
        ),
        None,
    )
    bootstrap_current = None
    bootstrap_total = None

    if bootstrap_status.bootstrap_state == "ready" and secondary_active_payload:
        bootstrap_progress_mode = secondary_active_payload.get("progress_mode") or "indeterminate"
        bootstrap_percent = secondary_active_payload.get("percent")
        bootstrap_stage = secondary_active_payload.get("stage_label")
        bootstrap_message = (
            secondary_active_payload.get("message")
            or "Additional market loading continues."
        )
        bootstrap_current = secondary_active_payload.get("current")
        bootstrap_total = secondary_active_payload.get("total")
    elif bootstrap_status.bootstrap_state == "ready":
        bootstrap_progress_mode = "determinate"
        bootstrap_percent = 100.0
        bootstrap_stage = primary_payload.get("stage_label") if primary_payload else None
        bootstrap_message = (
            "Primary market is ready."
            if not secondary_active
            else "Primary market is ready while additional market loading continues."
        )
    elif any(payload.get("progress_mode") == "determinate" for payload in market_payloads):
        focus_payload = next(
            (payload for payload in market_payloads if payload.get("status") in ACTIVE_STATUSES),
            primary_payload,
        )
        bootstrap_progress_mode = "determinate"
        bootstrap_percent = round(
            sum(_bootstrap_progress_percent(payload) for payload in market_payloads)
            / max(len(market_payloads), 1),
            2,
        )
        bootstrap_stage = focus_payload.get("stage_label") if focus_payload else None
        bootstrap_message = focus_payload.get("message") if focus_payload else "Bootstrap queued."
    else:
        bootstrap_progress_mode = "indeterminate"
        bootstrap_percent = None
        bootstrap_stage = primary_payload.get("stage_label") if primary_payload else None
        bootstrap_message = (
            primary_payload.get("message")
            if primary_payload is not None
            else "Bootstrap queued."
        )

    background_warning = None
    if len(enabled_markets) > 1 and (
        bootstrap_status.bootstrap_state == "running" or bool(secondary_active)
    ):
        background_warning = (
            "Additional enabled markets are still loading in the background."
        )

    return {
        "bootstrap": {
            "state": bootstrap_status.bootstrap_state,
            "app_ready": not bootstrap_status.bootstrap_required,
            "primary_market": primary_market,
            "enabled_markets": enabled_markets,
            "task_id": bootstrap_run.get("primary_task_id"),
            "market_task_ids": bootstrap_run.get("market_task_ids") or {},
            "current_stage": bootstrap_stage,
            "progress_mode": bootstrap_progress_mode,
            "percent": bootstrap_percent,
            "current": bootstrap_current,
            "total": bootstrap_total,
            "message": bootstrap_message,
            "background_warning": background_warning,
        },
        "summary": {
            "active_market_count": len(active_markets),
            "active_markets": active_markets,
            "status": summary_status,
        },
        "markets": market_payloads,
    }
