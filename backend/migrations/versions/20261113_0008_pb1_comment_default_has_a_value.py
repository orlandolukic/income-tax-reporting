"""pb1_comment_default always has a value

A default comment is a number (a rate) or a text, never empty and never both. Guards against a
default being stored without its value (a construction bug found on 2026-11-13: copied rates
became empty; the stored data was not affected).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_pb1_comment_default_one_value"), "pb1_comment_default",
        "(value_number IS NULL) <> (value_text IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_pb1_comment_default_one_value"), "pb1_comment_default", type_="check")
