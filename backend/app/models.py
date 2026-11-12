"""PostgreSQL tables for GFI data (SQLAlchemy 2 ORM). Schema changes go through Alembic
(`backend/migrations`).

- reporting_year: one row per GFI year.
- source_file / gfi_column / source_cell: the imported workbook, kept as an exact,
  read-only snapshot (headers, every cell's original value, number format and formula
  flag). It is the "Excel value" that edits are compared with.
- company / company_year: the companies and their GFI status per year. company_year
  holds the current values; the GFI table shows these. R.B. is not stored: it only
  defines, at import, which workbook rows form the company list.
- referent / office: lookup tables (exact text from the workbook, no merging).
- import_issue: problems found while importing (missing / shared / non-9-digit PIB, ...).
- change_log: every edit, with old and new value (number or text), user and time.
- pb1_link: which company_year a PB-1 file belongs to (PB-1 data itself is still read from Excel).

Company identity is company.id / company_year.id. Editing a company's name or PIB
changes the row in place, so the identity and its links stay the same.

PB-1, users and sessions are not stored here yet.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    true,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# BIGINT on PostgreSQL. INTEGER on SQLite (used only for local tests) so ids auto-increment.
BigId = BigInteger().with_variant(Integer(), "sqlite")

# Numeric GFI status values entered by users, in table order.
NUMERIC_FIELDS = ("kom", "preliminarni", "gfi_uradjen", "pb", "pb_predat")
# Columns that are always computed (read-only, not stored): field -> (minuend, subtrahend).
# An empty value counts as 0.
FORMULA_FIELDS = {
    "gfi_za_rad": ("kom", "gfi_uradjen"),  # GFI ZA RAD = kom - GFI uradjen
    "pb_za_rad": ("pb", "pb_predat"),  # PB-1,PB-2 za rad = PB-1, PB-2 - PB-1, PB-2 Predat
}


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class ReportingYear(Base):
    __tablename__ = "reporting_year"
    __table_args__ = (CheckConstraint("year BETWEEN 2000 AND 2100", name="year_range"),)

    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)


class SourceFile(Base):
    """Where a year's GFI table comes from: an imported workbook, or (origin "constructed") a
    year built in the app from the previous year (Migracija page); then file_name describes it
    and there is no file hash or time."""

    __tablename__ = "source_file"
    __table_args__ = (
        CheckConstraint("kind IN ('gfi', 'pb1')", name="kind"),
        CheckConstraint("origin IN ('workbook', 'constructed')", name="origin"),
        UniqueConstraint("kind", "year"),  # one active import per kind and year
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    year: Mapped[int] = mapped_column(ForeignKey("reporting_year.year"))
    origin: Mapped[str] = mapped_column(String(20), default="workbook", server_default="workbook")
    based_on_year: Mapped[int | None] = mapped_column(SmallInteger)  # constructed: the year it was built from
    file_name: Mapped[str] = mapped_column(Text)
    sheet_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary)  # workbook only
    file_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # workbook only
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    imported_by: Mapped[str] = mapped_column(Text)


class GfiColumn(Base):
    """Excel columns A..N of an imported workbook, with their header and mapped field."""

    __tablename__ = "gfi_column"

    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id", ondelete="CASCADE"), primary_key=True)
    col: Mapped[str] = mapped_column(String(3), primary_key=True)  # Excel column letter
    position: Mapped[int] = mapped_column(SmallInteger)  # 0-based order in the table
    header: Mapped[str | None] = mapped_column(Text)  # exact header text from row 1
    field: Mapped[str | None] = mapped_column(String(40))  # company_year field it maps to, if any


class SourceCell(Base):
    """Original cell from the workbook (read-only snapshot). At most one value_* is set."""

    __tablename__ = "source_cell"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN value_number IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN value_text IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN value_bool IS NULL THEN 0 ELSE 1 END) <= 1",
            name="one_value",
        ),
    )

    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id", ondelete="CASCADE"), primary_key=True)
    row: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # Excel row number
    col: Mapped[str] = mapped_column(String(3), primary_key=True)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    is_formula: Mapped[bool] = mapped_column(Boolean, default=False)
    number_format: Mapped[str] = mapped_column(Text, default="General")


class Company(Base):
    """A company. PIB is stored exactly as in the workbook; it is not required or unique."""

    __tablename__ = "company"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    pib: Mapped[str | None] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Referent(Base):
    __tablename__ = "referent"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)


class Office(Base):
    """The unnamed column right after REFERENT (SLAVIJA, FER, LJILJA, ADMIN, ...)."""

    __tablename__ = "office"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)


class CompanyYear(Base):
    """One company in one GFI year (one row of the GFI table), with its current values."""

    __tablename__ = "company_year"
    __table_args__ = (
        UniqueConstraint("year", "source_row"),
        UniqueConstraint("year", "company_id"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="RESTRICT"), index=True)
    year: Mapped[int] = mapped_column(ForeignKey("reporting_year.year"))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id", ondelete="CASCADE"), index=True)
    source_row: Mapped[int] = mapped_column(Integer)  # Excel row; the API and edits address rows by it
    name: Mapped[str] = mapped_column(Text)  # NAZIV as written in this year's workbook
    referent_id: Mapped[int | None] = mapped_column(ForeignKey("referent.id"))
    office_id: Mapped[int | None] = mapped_column(ForeignKey("office.id"))
    kom: Mapped[Decimal | None] = mapped_column(Numeric)
    preliminarni: Mapped[Decimal | None] = mapped_column(Numeric)
    gfi_uradjen: Mapped[Decimal | None] = mapped_column(Numeric)
    pb: Mapped[Decimal | None] = mapped_column(Numeric)
    pb_predat: Mapped[Decimal | None] = mapped_column(Numeric)
    # GFI ZA RAD and PB-1,PB-2 za rad are not stored: they are computed (FORMULA_FIELDS).
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(Text)
    # Shown in the year's table. A constructed year's company that is deselected (Migracija)
    # is hidden, not deleted, so its values are back when it is selected again.
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    company: Mapped[Company] = relationship()
    referent: Mapped[Referent | None] = relationship()
    office: Mapped[Office | None] = relationship()


class Pb1Link(Base):
    """Which company a PB-1 file belongs to. Set once (by the company name in the PB-1 file,
    matched on the original GFI names); afterwards PB-1 is found only through this link, so
    editing a company's name or PIB never changes it. Only companies of the list can be linked."""

    __tablename__ = "pb1_link"

    year: Mapped[int] = mapped_column(ForeignKey("reporting_year.year"), primary_key=True)
    pb1_file_name: Mapped[str] = mapped_column(Text, primary_key=True)
    pb1_company: Mapped[str] = mapped_column(Text)  # company name as written in the PB-1 file when linked
    company_year_id: Mapped[int] = mapped_column(ForeignKey("company_year.id", ondelete="CASCADE"), index=True)
    linked_by: Mapped[str] = mapped_column(Text)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportIssue(Base):
    __tablename__ = "import_issue"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id", ondelete="CASCADE"), index=True)
    row: Mapped[int | None] = mapped_column(Integer)
    col: Mapped[str | None] = mapped_column(String(3))
    message: Mapped[str] = mapped_column(Text)


class ChangeLog(Base):
    """Edit history. Kept when an import is replaced (company_year_id becomes NULL)."""

    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    company_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_year.id", ondelete="SET NULL"), index=True
    )
    year: Mapped[int] = mapped_column(SmallInteger)
    source_row: Mapped[int] = mapped_column(Integer)
    col: Mapped[str] = mapped_column(String(3))
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[Decimal | None] = mapped_column(Numeric)  # numeric fields
    new_value: Mapped[Decimal | None] = mapped_column(Numeric)
    old_text: Mapped[str | None] = mapped_column(Text)  # company details (name, PIB, referent, office)
    new_text: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
