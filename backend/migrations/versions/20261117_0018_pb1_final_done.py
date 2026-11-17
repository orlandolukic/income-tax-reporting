"""PB-1: the final report can be marked as done (locked) and unlocked again

User's decision (2026-11-17): the final report gets "Mark as done" (locked, Home "PB-1, PB-2" = 1)
and "Unlock" (editable again, Home "PB-1, PB-2" = 0). pb1_report_state keeps when and by whom it
was marked as done; unlocking clears it (the Home column's change_log keeps the history).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pb1_report_state", sa.Column("final_done_by", sa.Text(), nullable=True))
    op.add_column("pb1_report_state", sa.Column("final_done_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_pb1_report_state_final_done_pair"), "pb1_report_state",
        "(final_done_at IS NULL) = (final_done_by IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_pb1_report_state_final_done_after_created"), "pb1_report_state",
        "final_done_at IS NULL OR final_created_at IS NOT NULL",
    )


def downgrade() -> None:
    done = op.get_bind().execute(sa.text("SELECT count(*) FROM pb1_report_state WHERE final_done_at IS NOT NULL")).scalar()
    if done:
        raise RuntimeError(f"Refusing to downgrade: {done} final reports are marked as done.")
    op.drop_constraint(op.f("ck_pb1_report_state_final_done_after_created"), "pb1_report_state", type_="check")
    op.drop_constraint(op.f("ck_pb1_report_state_final_done_pair"), "pb1_report_state", type_="check")
    op.drop_column("pb1_report_state", "final_done_at")
    op.drop_column("pb1_report_state", "final_done_by")
