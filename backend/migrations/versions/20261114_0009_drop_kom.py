"""kom is no longer stored: kom = 1 for every company

User's decision (2026-11-14): the "kom" column is removed from the app; kom is a global
constant 1 for every company and every year (app.models.KOM), so GFI ZA RAD = 1 - GFI uradjen
and the Home statistics are shares of the number of companies.

Removes the stored kom values (company_year.kom), the kom column of every GFI table
(gfi_column rows mapped to "kom") with its snapshot cells (source_cell), and any change_log rows
of kom. Irreversible: the downgrade refuses (the values are gone; before this migration the
real database had kom 1 for 153 and 0 for 12 companies in 2025, 0 for all in 2026).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM source_cell sc USING gfi_column gc"
        " WHERE gc.source_file_id = sc.source_file_id AND gc.col = sc.col AND gc.field = 'kom'"
    )
    op.execute("DELETE FROM gfi_column WHERE field = 'kom'")
    op.execute("DELETE FROM change_log WHERE field = 'kom'")
    op.drop_column("company_year", "kom")


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: the kom values were removed (kom = 1 for every company since 0009)")
