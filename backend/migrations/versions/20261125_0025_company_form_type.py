"""company_year.form_type: PDP or PPDG-1S

User's decision (2026-11-25): two company types. "pdp" files the PB-1 form of the workbook (every
company so far, so every existing company year is "pdp", as before); "ppdg" files PPDG-1S, whose
Poreski bilans is Obrazac PB2 (app/pb1_ppdg.py). Per company year, carried by the Migracija.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, Sequence[str], None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("company_year", sa.Column("form_type", sa.String(length=10), server_default="pdp", nullable=False))
    op.create_check_constraint("form_type", "company_year", "form_type IN ('pdp', 'ppdg')")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_year WHERE form_type <> 'pdp' LIMIT 1")).first():
        raise RuntimeError("Migration 0025 can't be undone while a company is of type PPDG-1S.")
    op.drop_constraint("form_type", "company_year", type_="check")
    op.drop_column("company_year", "form_type")
