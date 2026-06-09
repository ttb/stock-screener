from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base

import app.models.app_settings  # noqa: F401


def test_bootstrap_run_manifest_repository_round_trips_market_task_ids():
    from app.services.bootstrap_run_manifest import (
        BootstrapRunManifest,
        BootstrapRunManifestRepository,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        repository = BootstrapRunManifestRepository()
        manifest = BootstrapRunManifest(
            primary_market="US",
            enabled_markets=("US", "HK", "TW"),
            primary_task_id="primary-task-123",
            market_task_ids={
                "US": "primary-task-123",
                "HK": "background-task-2",
                "TW": "background-task-3",
            },
        )

        repository.save(db, manifest)
        loaded = repository.load(db)

        assert loaded == manifest
    finally:
        db.close()
        engine.dispose()
