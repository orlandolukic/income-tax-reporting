"""status columns are never empty: 0 or 1

User's decision (2026-11-14): the status columns (Preliminarni, GFI uradjen, PB-1, PB-2,
PB-1, PB-2 Predat) can't be empty; a cell without a value is 0. Every empty status cell becomes
0, both the current value (company_year) and the original in the snapshot (source_cell), so the
cell behaves as a 0 everywhere (on Home it is editable like every status cell holding a number).
Then the database refuses empty values and anything but 0 / 1 (NOT NULL + CHECK).

Before this migration the real database had, in 2025 and in 2026 each, 8 empty Preliminarni,
8 GFI uradjen, 14 PB-1, PB-2 and 14 Predat cells (shown as 0 already).

Downgrade removes the constraints only (the 0 values stay).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUS_FIELDS = ("preliminarni", "gfi_uradjen", "pb", "pb_predat")


def upgrade() -> None:
    fields = ", ".join(f"'{f}'" for f in STATUS_FIELDS)
    op.execute(
        "UPDATE source_cell c SET value_number = 0, value_text = NULL, value_bool = NULL"
        " FROM gfi_column g WHERE g.source_file_id = c.source_file_id AND g.col = c.col"
        f" AND g.field IN ({fields}) AND c.value_number IS NULL"
    )
    for field in STATUS_FIELDS:
        op.execute(f"UPDATE company_year SET {field} = 0 WHERE {field} IS NULL")
        op.alter_column("company_year", field, nullable=False)
        op.create_check_constraint(op.f(f"ck_company_year_{field}_0_or_1"), "company_year", f"{field} IN (0, 1)")


def downgrade() -> None:
    for field in STATUS_FIELDS:
        op.drop_constraint(op.f(f"ck_company_year_{field}_0_or_1"), "company_year", type_="check")
        op.alter_column("company_year", field, nullable=True)
