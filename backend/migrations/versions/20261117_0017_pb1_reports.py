"""PB-1: two separate reports per company year, preliminary and final

User's decision (2026-11-17): every company's PB-1 has a preliminary and a final report, each
with its own values and calculations. The preliminary report is marked as done (then locked,
still viewable); the final report is created from it by a button.

- pb1_company_edit gets `report` ('preliminary' / 'final') as part of its key; existing values
  (none on 2026-11-17) belong to the preliminary report.
- pb1_report_state: per company year, when the preliminary report was marked as done and when
  the final report was created (and by whom).

Downgrade refuses while a final value or a report state is stored.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pb1_company_edit",
        sa.Column("report", sa.String(length=12), server_default="preliminary", nullable=False),
    )
    op.create_check_constraint(op.f("ck_pb1_company_edit_report"), "pb1_company_edit", "report IN ('preliminary', 'final')")
    op.drop_constraint("pk_pb1_company_edit", "pb1_company_edit", type_="primary")
    op.create_primary_key("pk_pb1_company_edit", "pb1_company_edit", ["company_year_id", "report", "tab", "row", "col"])

    op.create_table(
        "pb1_report_state",
        sa.Column("company_year_id", sa.BigInteger(), nullable=False),
        sa.Column("preliminary_done_by", sa.Text(), nullable=True),
        sa.Column("preliminary_done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_created_by", sa.Text(), nullable=True),
        sa.Column("final_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(preliminary_done_at IS NULL) = (preliminary_done_by IS NULL)", name=op.f("ck_pb1_report_state_done_pair")),
        sa.CheckConstraint("(final_created_at IS NULL) = (final_created_by IS NULL)", name=op.f("ck_pb1_report_state_final_pair")),
        sa.CheckConstraint("final_created_at IS NULL OR preliminary_done_at IS NOT NULL", name=op.f("ck_pb1_report_state_final_after_done")),
        sa.ForeignKeyConstraint(["company_year_id"], ["company_year.id"], name=op.f("fk_pb1_report_state_company_year_id_company_year"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("company_year_id", name=op.f("pk_pb1_report_state")),
    )


def downgrade() -> None:
    conn = op.get_bind()
    finals = conn.execute(sa.text("SELECT count(*) FROM pb1_company_edit WHERE report <> 'preliminary'")).scalar()
    states = conn.execute(sa.text("SELECT count(*) FROM pb1_report_state")).scalar()
    if finals or states:
        raise RuntimeError(f"Refusing to downgrade: {finals} final report values and {states} report states are stored.")
    op.drop_table("pb1_report_state")
    op.drop_constraint("pk_pb1_company_edit", "pb1_company_edit", type_="primary")
    op.create_primary_key("pk_pb1_company_edit", "pb1_company_edit", ["company_year_id", "tab", "row", "col"])
    op.drop_constraint("ck_pb1_company_edit_report", "pb1_company_edit", type_="check")
    op.drop_column("pb1_company_edit", "report")
