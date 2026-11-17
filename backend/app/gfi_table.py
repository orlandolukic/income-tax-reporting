"""The GFI table as the app works with it: original cells (from the database snapshot) and the
column mapping. No Excel library here; reading a workbook is app.gfi_workbook (imports only)."""

from dataclasses import dataclass, field

CellValue = str | int | float | bool | None


@dataclass(frozen=True)
class SourceCell:
    value: CellValue  # stored value (cached result for formulas)
    number_format: str  # Excel number format, e.g. "#,##0_);[Red](#,##0)"
    is_formula: bool
    locked: bool = False  # not editable as a number regardless of content (e.g. company details in the database)

    @property
    def is_editable(self) -> bool:
        """Only plain numeric cells can be edited; formulas, text and empty cells cannot."""
        return (
            not self.locked
            and not self.is_formula
            and isinstance(self.value, (int, float))
            and not isinstance(self.value, bool)
        )


@dataclass(frozen=True)
class SourceTable:
    workbook: str
    sheet: str
    headers: dict[str, str | None]  # column letter -> original header
    rows: dict[int, dict[str, SourceCell]]  # Excel row number -> column letter -> cell
    # Column letter -> GFI field (name, pib, kom, ...), found by header; set by app.gfi_store.
    fields: dict[str, str] = field(default_factory=dict)
