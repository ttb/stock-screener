"""Stable MIC-scoped market facts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MicFacts:
    """Calendar, timezone, and currency facts for one MIC."""

    mic: str
    calendar_id: str
    timezone: str
    default_currency: str
    provider_calendar_id: str | None = None
