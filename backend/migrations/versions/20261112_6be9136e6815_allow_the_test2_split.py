"""Allow the test2 split: a second held-out set, added once the test split had been seen several times.

Revision ID: 6be9136e6815
Revises: 8dab1a05061f
Create Date: 2026-11-12 16:28:26.574379
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6be9136e6815"
down_revision: str | None = "8dab1a05061f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_evaluation_runs_split_valid"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "evaluation_runs", type_="check")
    op.execute(
        f"ALTER TABLE evaluation_runs ADD CONSTRAINT {CONSTRAINT} CHECK (split in ('train', 'dev', 'test', 'test2'))"
    )


def downgrade() -> None:
    # Fails while test2 runs exist; delete them first if you really want to go back.
    op.drop_constraint(op.f(CONSTRAINT), "evaluation_runs", type_="check")
    op.execute(f"ALTER TABLE evaluation_runs ADD CONSTRAINT {CONSTRAINT} CHECK (split in ('train', 'dev', 'test'))")
