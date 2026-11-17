"""Home status columns follow the PB-1 report steps only; GFI becomes a step

User's decision (2026-11-17): Preliminarni, GFI uradjen, PB-1, PB-2 and PB-1, PB-2 Predat are
never changed by hand (Home is view only); they follow the steps of the company's PB-1 reports:
preliminary done -> Preliminarni, GFI done -> GFI uradjen, final done -> PB-1, PB-2, submitted ->
Predat. GFI done is a new step between the preliminary report and the final one.

- pb1_report_state: gfi_done_by / gfi_done_at (CHECKs: pair; after the preliminary report; the
  final report only after GFI). A company year whose final report already exists gets its GFI
  step (at the time the final report was created, by the same user).
- pb1_report_event: the events gfi_done / gfi_reopened; the backfilled GFI steps are recorded.
- company_year: every status column set from the steps (1 where the step is taken, else 0); each
  change recorded in change_log (changed_by 'migration 0020'). The import snapshot keeps the
  workbook's values.

Irreversible: the downgrade refuses (the earlier hand-set values are only in change_log).

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENTS = (
    "preliminary_done", "gfi_done", "gfi_reopened", "final_created", "final_done", "final_unlocked", "submitted",
    "submission_withdrawn",
)
# Home status column -> the state column of its step
STEPS = {
    "preliminarni": "preliminary_done_at",
    "gfi_uradjen": "gfi_done_at",
    "pb": "final_done_at",
    "pb_predat": "submitted_at",
}


def upgrade() -> None:
    op.add_column("pb1_report_state", sa.Column("gfi_done_by", sa.Text(), nullable=True))
    op.add_column("pb1_report_state", sa.Column("gfi_done_at", sa.DateTime(timezone=True), nullable=True))
    # The GFI step of final reports that already exist.
    op.execute(
        "UPDATE pb1_report_state SET gfi_done_at = final_created_at, gfi_done_by = final_created_by "
        "WHERE final_created_at IS NOT NULL"
    )
    op.create_check_constraint(
        op.f("ck_pb1_report_state_gfi_done_pair"), "pb1_report_state", "(gfi_done_at IS NULL) = (gfi_done_by IS NULL)"
    )
    op.create_check_constraint(
        op.f("ck_pb1_report_state_gfi_after_preliminary"), "pb1_report_state",
        "gfi_done_at IS NULL OR preliminary_done_at IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_pb1_report_state_final_after_gfi"), "pb1_report_state", "final_created_at IS NULL OR gfi_done_at IS NOT NULL"
    )

    op.drop_constraint(op.f("ck_pb1_report_event_event"), "pb1_report_event", type_="check")
    op.create_check_constraint(
        op.f("ck_pb1_report_event_event"), "pb1_report_event", "event IN (" + ", ".join(f"'{e}'" for e in EVENTS) + ")"
    )
    op.execute(
        "INSERT INTO pb1_report_event (company_year_id, event, happened_at, happened_by) "
        "SELECT company_year_id, 'gfi_done', gfi_done_at, gfi_done_by FROM pb1_report_state WHERE gfi_done_at IS NOT NULL"
    )

    # Every status column from the steps, with its history.
    for field, step in STEPS.items():
        target = (
            f"(SELECT CASE WHEN s.{step} IS NOT NULL THEN 1 ELSE 0 END FROM pb1_report_state s "
            f"WHERE s.company_year_id = cy.id)"
        )
        value = f"COALESCE({target}, 0)"
        op.execute(f"""
            INSERT INTO change_log (company_year_id, year, source_row, col, field, old_value, new_value, changed_by, changed_at)
            SELECT cy.id, cy.year, cy.source_row, gc.col, '{field}', cy.{field}, {value}, 'migration 0020', now()
            FROM company_year cy
            JOIN gfi_column gc ON gc.source_file_id = cy.source_file_id AND gc.field = '{field}'
            WHERE cy.{field} <> {value}
        """)
        op.execute(f"UPDATE company_year cy SET {field} = {value} WHERE cy.{field} <> {value}")


def downgrade() -> None:
    raise RuntimeError("Migration 0020 can't be undone: the earlier hand-set status values are only in change_log.")
