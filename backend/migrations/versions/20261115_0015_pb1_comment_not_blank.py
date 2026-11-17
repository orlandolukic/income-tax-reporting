"""PB-1 comments are never only spaces or "-"

User's rule (2026-11-15): a comment holding only spaces (one or more) or "-" is no comment; it
must not be stored (the app removes the comment instead). Adds that CHECK to pb1_comment; stops
if a stored comment breaks it (none on 2026-11-15).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK = r"value_text IS NULL OR value_text !~ '^\s*-?\s*$'"


def upgrade() -> None:
    blank = op.get_bind().execute(sa.text(f"SELECT tab, row FROM pb1_comment WHERE NOT ({CHECK})")).all()
    if blank:
        raise RuntimeError(f"PB-1 comments holding only spaces or '-': {blank}; remove them first")
    op.create_check_constraint(op.f("ck_pb1_comment_text_not_blank"), "pb1_comment", CHECK)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_pb1_comment_text_not_blank"), "pb1_comment", type_="check")
