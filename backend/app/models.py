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
- pb1_link: which company_year a PB-1 file's amounts belong to.
- PB-1 (see the section below): the imported PB-1 workbook (pb1_sheet, pb1_sheet_column,
  pb1_source_cell), edits shared by every company (pb1_template_edit), each company's own
  values (pb1_company_edit) and the global comments (pb1_comment).
- app_user / user_session: logins.

Company identity is company.id / company_year.id. Editing a company's name or PIB
changes the row in place, so the identity and its links stay the same.

With DATABASE_URL set, everything the app shows or changes is in these tables; the Excel
files are read only by the one-time imports (app.gfi_import, app.pb1_import).
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
    ForeignKeyConstraint,
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

BigId = BigInteger()

# Numeric GFI status values entered by users, in table order.
NUMERIC_FIELDS = ("preliminarni", "gfi_uradjen", "pb", "pb_predat")
# kom (the workbook's "kom" column) is not stored: it is 1 for every company and every year
# (user's rule, 2026-11-14). It stays a constant in the formula and the statistics.
KOM = 1
# Columns that are always computed (read-only, not stored): field -> (minuend, subtrahend);
# an operand is a field or a constant. An empty value counts as 0.
FORMULA_FIELDS: dict[str, tuple[str | int, str]] = {
    "gfi_za_rad": (KOM, "gfi_uradjen"),  # GFI ZA RAD = kom (1) - GFI uradjen
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
        # Status columns are never empty and hold only 0 or 1 (user's rule, 2026-11-14).
        *(CheckConstraint(f"{field} IN (0, 1)", name=f"{field}_0_or_1") for field in NUMERIC_FIELDS),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="RESTRICT"), index=True)
    year: Mapped[int] = mapped_column(ForeignKey("reporting_year.year"))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id", ondelete="CASCADE"), index=True)
    source_row: Mapped[int] = mapped_column(Integer)  # Excel row; the API and edits address rows by it
    name: Mapped[str] = mapped_column(Text)  # NAZIV as written in this year's workbook
    referent_id: Mapped[int | None] = mapped_column(ForeignKey("referent.id"))
    office_id: Mapped[int | None] = mapped_column(ForeignKey("office.id"))
    # Status columns: 0 or 1, never empty (an empty cell of a workbook is imported as 0).
    preliminarni: Mapped[Decimal] = mapped_column(Numeric)
    gfi_uradjen: Mapped[Decimal] = mapped_column(Numeric)
    pb: Mapped[Decimal] = mapped_column(Numeric)
    pb_predat: Mapped[Decimal] = mapped_column(Numeric)
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


# --- PB-1 -----------------------------------------------------------------------------------
# The PB-1 workbook of a year ("<year> PB-1.xls") is imported once (app.pb1_import) as a
# read-only snapshot of its sheets: a source_file of kind 'pb1' (origin 'workbook') with
# pb1_sheet / pb1_sheet_column / pb1_source_cell. A constructed year's form is a 'pb1'
# source_file of origin 'constructed' (based_on_year) without cells: it uses the form of the
# year it was built from. Edits and settings are stored per year; amounts and comments of a
# company per company_year.

PB1_TAB_KEYS = ("poreski-bilans", "uporedo", "preliminarni")
_TAB_CHECK = "tab IN ('poreski-bilans', 'uporedo', 'preliminarni')"


class Pb1SheetRow(Base):
    """A sheet of an imported PB-1 workbook: one per tab of the form."""

    __tablename__ = "pb1_sheet"
    __table_args__ = (CheckConstraint(_TAB_CHECK, name="tab"),)

    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id", ondelete="CASCADE"), primary_key=True)
    tab: Mapped[str] = mapped_column(String(20), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger)  # sheet order in the workbook (0-based)
    name: Mapped[str] = mapped_column(Text)  # Excel sheet name, e.g. "Uporedo 2025 i 2024"
    nrows: Mapped[int] = mapped_column(Integer)  # used range of the sheet
    ncols: Mapped[int] = mapped_column(Integer)


class Pb1SheetColumn(Base):
    """Column width of a PB-1 sheet, as set in Excel (columns without a width are left out)."""

    __tablename__ = "pb1_sheet_column"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_file_id", "tab"], ["pb1_sheet.source_file_id", "pb1_sheet.tab"], ondelete="CASCADE"
        ),
    )

    source_file_id: Mapped[int] = mapped_column(BigId, primary_key=True)
    tab: Mapped[str] = mapped_column(String(20), primary_key=True)
    col: Mapped[str] = mapped_column(String(3), primary_key=True)  # Excel column letter
    width: Mapped[int] = mapped_column(Integer)  # 1/256 of a character, as in the file


class Pb1SourceCell(Base):
    """A cell of a PB-1 sheet as stored in the file (read-only): its value (formula cells: Excel's
    last result), number format, bold font and fill color. Empty, unformatted cells are left out."""

    __tablename__ = "pb1_source_cell"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_file_id", "tab"], ["pb1_sheet.source_file_id", "pb1_sheet.tab"], ondelete="CASCADE"
        ),
        CheckConstraint("kind IN ('empty', 'text', 'number', 'bool', 'error')", name="kind"),
        CheckConstraint(
            "(kind = 'empty' AND value_number IS NULL AND value_text IS NULL AND value_bool IS NULL)"
            " OR (kind = 'number' AND value_number IS NOT NULL AND value_text IS NULL AND value_bool IS NULL)"
            " OR (kind IN ('text', 'error') AND value_text IS NOT NULL AND value_number IS NULL AND value_bool IS NULL)"
            " OR (kind = 'bool' AND value_bool IS NOT NULL AND value_number IS NULL AND value_text IS NULL)",
            name="value_of_kind",
        ),
    )

    source_file_id: Mapped[int] = mapped_column(BigId, primary_key=True)
    tab: Mapped[str] = mapped_column(String(20), primary_key=True)
    row: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # Excel row number
    col: Mapped[str] = mapped_column(String(3), primary_key=True)  # Excel column letter
    kind: Mapped[str] = mapped_column(String(6))
    value_number: Mapped[Decimal | None] = mapped_column(Numeric)
    value_text: Mapped[str | None] = mapped_column(Text)  # text, or an error such as "#DIV/0!"
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    number_format: Mapped[str] = mapped_column(Text, default="General")
    bold: Mapped[bool] = mapped_column(Boolean, default=False)
    fill: Mapped[str | None] = mapped_column(String(7))  # "#rrggbb"


class _Pb1Value:
    """Value columns of a PB-1 edit: the value and the value shown before the first edit
    (a number or a text; both NULL = empty)."""

    value_number: Mapped[Decimal | None] = mapped_column(Numeric)
    value_text: Mapped[str | None] = mapped_column(Text)
    original_number: Mapped[Decimal | None] = mapped_column(Numeric)
    original_text: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Pb1TemplateEdit(_Pb1Value, Base):
    """A change of the year's PB-1 form shared by every company (a template text, konto, ...)."""

    __tablename__ = "pb1_template_edit"
    __table_args__ = (CheckConstraint(_TAB_CHECK, name="tab"),)

    year: Mapped[int] = mapped_column(ForeignKey("reporting_year.year"), primary_key=True)
    tab: Mapped[str] = mapped_column(String(20), primary_key=True)
    row: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # Excel row of the form
    col: Mapped[str] = mapped_column(String(3), primary_key=True)


# Every company's PB-1 has two separate reports (user, 2026-11-17): the preliminary one and the
# final one, each with its own values and calculations.
PB1_REPORTS = ("preliminary", "final")
_REPORT_CHECK = "report IN ('preliminary', 'final')"


class Pb1CompanyEdit(_Pb1Value, Base):
    """A company's own PB-1 value in one of its reports: an amount or its months in business.
    A final report's value is stored only where it differs from the (locked) preliminary one."""

    __tablename__ = "pb1_company_edit"
    __table_args__ = (CheckConstraint(_TAB_CHECK, name="tab"), CheckConstraint(_REPORT_CHECK, name="report"))

    # RESTRICT: a company year with PB-1 values can't be deleted (e.g. by a GFI re-import).
    company_year_id: Mapped[int] = mapped_column(
        ForeignKey("company_year.id", ondelete="RESTRICT"), primary_key=True
    )
    report: Mapped[str] = mapped_column(String(12), primary_key=True, server_default="preliminary")
    tab: Mapped[str] = mapped_column(String(20), primary_key=True)
    row: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    col: Mapped[str] = mapped_column(String(3), primary_key=True)


class Pb1ReportState(Base):
    """Where a company year's PB-1 reports stand: the preliminary report marked as done (then
    locked, still viewable) and the final report created from it (user, 2026-11-17). No row:
    the preliminary report is being worked on."""

    __tablename__ = "pb1_report_state"
    __table_args__ = (
        CheckConstraint("(preliminary_done_at IS NULL) = (preliminary_done_by IS NULL)", name="done_pair"),
        CheckConstraint("(final_created_at IS NULL) = (final_created_by IS NULL)", name="final_pair"),
        # The final report is made only from a preliminary report marked as done.
        CheckConstraint("final_created_at IS NULL OR preliminary_done_at IS NOT NULL", name="final_after_done"),
        CheckConstraint("(gfi_done_at IS NULL) = (gfi_done_by IS NULL)", name="gfi_done_pair"),
        # GFI is marked as done after the preliminary report, and before the final one is made.
        CheckConstraint("gfi_done_at IS NULL OR preliminary_done_at IS NOT NULL", name="gfi_after_preliminary"),
        CheckConstraint("final_created_at IS NULL OR gfi_done_at IS NOT NULL", name="final_after_gfi"),
        CheckConstraint("(final_done_at IS NULL) = (final_done_by IS NULL)", name="final_done_pair"),
        # Only a created final report can be marked as done.
        CheckConstraint("final_done_at IS NULL OR final_created_at IS NOT NULL", name="final_done_after_created"),
        CheckConstraint("(submitted_at IS NULL) = (submitted_by IS NULL)", name="submitted_pair"),
        # Only a final report marked as done can be submitted.
        CheckConstraint("submitted_at IS NULL OR final_done_at IS NOT NULL", name="submitted_after_done"),
    )

    company_year_id: Mapped[int] = mapped_column(
        ForeignKey("company_year.id", ondelete="RESTRICT"), primary_key=True
    )
    preliminary_done_by: Mapped[str | None] = mapped_column(Text)
    preliminary_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # GFI (the annual financial statements) done: Home "GFI uradjen" = 1; the final report is
    # made on it. Reopening clears it (only before the final report is created).
    gfi_done_by: Mapped[str | None] = mapped_column(Text)
    gfi_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_created_by: Mapped[str | None] = mapped_column(Text)
    final_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The final report marked as done (locked); unlocking clears it (user, 2026-11-17).
    final_done_by: Mapped[str | None] = mapped_column(Text)
    final_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The report submitted (Home "PB-1, PB-2 Predat" = 1); withdrawing clears it. Every step is
    # also kept in pb1_report_event.
    submitted_by: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# The steps of a company year's PB-1 reports, in pb1_report_event (user, 2026-11-17).
PB1_REPORT_EVENTS = (
    "preliminary_done", "gfi_done", "gfi_reopened", "final_created", "final_done", "final_unlocked", "submitted",
    "submission_withdrawn",
)


class Pb1ReportEvent(Base):
    """One step of a company year's PB-1 reports, with its date, time and user: the history of
    the consecutive steps (marked as done, created, unlocked, submitted, withdrawn)."""

    __tablename__ = "pb1_report_event"
    __table_args__ = (
        CheckConstraint("event IN (" + ", ".join(f"'{e}'" for e in PB1_REPORT_EVENTS) + ")", name="event"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    company_year_id: Mapped[int] = mapped_column(ForeignKey("company_year.id", ondelete="RESTRICT"), index=True)
    event: Mapped[str] = mapped_column(String(24))
    happened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    happened_by: Mapped[str] = mapped_column(Text)


COMMENT_TEXT_CHECK = r"value_text IS NULL OR value_text !~ '^\s*-?\s*$'"


class Pb1Comment(Base):
    """Global settings: the comment of a PB-1 form row ("Komentar, stopa, konto"), one for every
    year and every company (user's rule, 2026-11-15: the comments are rules for the form's
    sections; no year or company comments). Edited only on the Global Settings page."""

    __tablename__ = "pb1_comment"
    __table_args__ = (
        CheckConstraint(_TAB_CHECK, name="tab"),
        # A comment always has a value: a number (a rate) or a text, not both.
        CheckConstraint("(value_number IS NULL) <> (value_text IS NULL)", name="one_value"),
        # A text comment is never only spaces or "-" (that is no comment).
        CheckConstraint(COMMENT_TEXT_CHECK, name="text_not_blank"),
    )

    tab: Mapped[str] = mapped_column(String(20), primary_key=True)
    row: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # Excel row of the form
    value_number: Mapped[Decimal | None] = mapped_column(Numeric)  # a rate, e.g. 0.05
    value_text: Mapped[str | None] = mapped_column(Text)  # a comment or konto numbers
    # "workbook" (filled by the PB-1 import) or "app" (added on Global Settings)
    source: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Users and sessions -------------------------------------------------------------------


class AppUser(Base):
    """A user who can log in. Only the password hash is stored (app.security)."""

    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(Text, primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """A login session. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "user_session"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    username: Mapped[str] = mapped_column(ForeignKey("app_user.username", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
