"""PB-1: submitting the report, and the history of the report steps

User's decision (2026-11-17): a final report marked as done can be submitted ("Mark as
submitted": Home "PB-1, PB-2 Predat" = 1, with the date and time), and the submission can be
withdrawn (the inverse). Every step is kept with its date, time and user in pb1_report_event.

- pb1_report_state: submitted_by / submitted_at (CHECKs: pair; only after the final is done).
- pb1_report_event: the steps; filled here from the states already stored (preliminary done,
  final created, final done).

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENTS = ("preliminary_done", "final_created", "final_done", "final_unlocked", "submitted", "submission_withdrawn")


def upgrade() -> None:
    op.add_column("pb1_report_state", sa.Column("submitted_by", sa.Text(), nullable=True))
    op.add_column("pb1_report_state", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_pb1_report_state_submitted_pair"), "pb1_report_state", "(submitted_at IS NULL) = (submitted_by IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_pb1_report_state_submitted_after_done"), "pb1_report_state",
        "submitted_at IS NULL OR final_done_at IS NOT NULL",
    )
    op.create_table(
        "pb1_report_event",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("company_year_id", sa.BigInteger(), nullable=False),
        sa.Column("event", sa.String(length=24), nullable=False),
        sa.Column("happened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("happened_by", sa.Text(), nullable=False),
        sa.CheckConstraint("event IN (" + ", ".join(f"'{e}'" for e in EVENTS) + ")", name=op.f("ck_pb1_report_event_event")),
        sa.ForeignKeyConstraint(
            ["company_year_id"], ["company_year.id"], name=op.f("fk_pb1_report_event_company_year_id_company_year"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pb1_report_event")),
    )
    op.create_index(op.f("ix_pb1_report_event_company_year_id"), "pb1_report_event", ["company_year_id"])
    # The steps already taken, from the stored states.
    for event, at, by in (
        ("preliminary_done", "preliminary_done_at", "preliminary_done_by"),
        ("final_created", "final_created_at", "final_created_by"),
        ("final_done", "final_done_at", "final_done_by"),
    ):
        op.execute(
            f"INSERT INTO pb1_report_event (company_year_id, event, happened_at, happened_by) "
            f"SELECT company_year_id, '{event}', {at}, {by} FROM pb1_report_state WHERE {at} IS NOT NULL"
        )


def downgrade() -> None:
    submitted = op.get_bind().execute(sa.text("SELECT count(*) FROM pb1_report_state WHERE submitted_at IS NOT NULL")).scalar()
    if submitted:
        raise RuntimeError(f"Refusing to downgrade: {submitted} reports are submitted.")
    op.drop_index(op.f("ix_pb1_report_event_company_year_id"), table_name="pb1_report_event")
    op.drop_table("pb1_report_event")
    op.drop_constraint(op.f("ck_pb1_report_state_submitted_after_done"), "pb1_report_state", type_="check")
    op.drop_constraint(op.f("ck_pb1_report_state_submitted_pair"), "pb1_report_state", type_="check")
    op.drop_column("pb1_report_state", "submitted_at")
    op.drop_column("pb1_report_state", "submitted_by")
