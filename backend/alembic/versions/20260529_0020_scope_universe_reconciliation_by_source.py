"""Scope universe reconciliation snapshots by source."""

from __future__ import annotations

from alembic import op


revision = "20260529_0020"
down_revision = "20260529_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stock_universe_reconciliation_runs") as batch_op:
        batch_op.drop_constraint(
            "uq_universe_reconciliation_market_snapshot",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_universe_reconciliation_market_source_snapshot",
            ["market", "source_name", "snapshot_id"],
        )
        batch_op.create_index(
            "idx_universe_reconciliation_market_source_created",
            ["market", "source_name", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("stock_universe_reconciliation_runs") as batch_op:
        batch_op.drop_index("idx_universe_reconciliation_market_source_created")
        batch_op.drop_constraint(
            "uq_universe_reconciliation_market_source_snapshot",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_universe_reconciliation_market_snapshot",
            ["market", "snapshot_id"],
        )
