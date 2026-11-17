"""company details in upper case; "-" as a stored detail means empty

User's decision (2026-11-14): NAZIV, REFERENT and office are upper case everywhere, so the
data is consistent ("prebaci sve u velika slova"). This converts the existing values, in the
current values and in the import snapshot (so they are not shown as edited):
- company_year.name and company.name -> upper case;
- referent / office lookups -> upper case; a lookup whose upper-case name already exists is
  merged into it (2026-11-14: "Kristina" into "KRISTINA", "Slavija" into "SLAVIJA");
- a referent / office stored as "-" (or blank) is empty: "-" is how an empty detail is shown
  (2026-11-14: referent "-" and office "-", 4 companies each per year);
- source_cell texts of the NAZIV / REFERENT / office columns accordingly.
pb1_link.pb1_company is not changed (it is the name as written in the PB-1 file) and
change_log keeps its history as it was.

Python str.upper() is used (č ć đ š ž handled independently of the database locale).
Downgrade does nothing (the original spelling is in the workbooks).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMPTY_MARK = "-"


def _clean(name: str | None) -> str | None:
    value = (name or "").strip()
    return None if value in ("", EMPTY_MARK) else value.upper()


def _lookups(conn, table: str, fk: str) -> None:
    rows = conn.execute(sa.text(f"SELECT id, name FROM {table} ORDER BY id")).all()
    by_name = {name: id_ for id_, name in rows}
    for id_, name in rows:
        target = _clean(name)
        if target == name:
            continue
        if target is None:
            conn.execute(sa.text(f"UPDATE company_year SET {fk} = NULL WHERE {fk} = :id"), {"id": id_})
            conn.execute(sa.text(f"DELETE FROM {table} WHERE id = :id"), {"id": id_})
            del by_name[name]
        elif target in by_name and by_name[target] != id_:
            conn.execute(sa.text(f"UPDATE company_year SET {fk} = :to WHERE {fk} = :id"), {"to": by_name[target], "id": id_})
            conn.execute(sa.text(f"DELETE FROM {table} WHERE id = :id"), {"id": id_})
            del by_name[name]
        else:
            conn.execute(sa.text(f"UPDATE {table} SET name = :name WHERE id = :id"), {"name": target, "id": id_})
            del by_name[name]
            by_name[target] = id_


def upgrade() -> None:
    conn = op.get_bind()
    _lookups(conn, "referent", "referent_id")
    _lookups(conn, "office", "office_id")
    for table in ("company_year", "company"):
        for id_, name in conn.execute(sa.text(f"SELECT id, name FROM {table}")).all():
            if name != name.upper():
                conn.execute(sa.text(f"UPDATE {table} SET name = :name WHERE id = :id"), {"name": name.upper(), "id": id_})
    cells = conn.execute(sa.text(
        "SELECT c.source_file_id, c.row, c.col, c.value_text, g.field FROM source_cell c"
        " JOIN gfi_column g ON g.source_file_id = c.source_file_id AND g.col = c.col"
        " WHERE g.field IN ('name', 'referent', 'office') AND c.value_text IS NOT NULL"
    )).all()
    for source_file_id, row, col, value, field in cells:
        new = value.upper() if field == "name" else (value.upper() if value.strip() != EMPTY_MARK else None)
        if new != value:
            conn.execute(
                sa.text("UPDATE source_cell SET value_text = :v WHERE source_file_id = :f AND row = :r AND col = :c"),
                {"v": new, "f": source_file_id, "r": row, "c": col},
            )


def downgrade() -> None:
    pass  # the original spelling is in the workbooks; nothing to restore
