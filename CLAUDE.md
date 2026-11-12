# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Start of every session

1. Read `DEVLOG.md` first to restore context: completed work, recent changes, open tasks.
2. Read `README.md` for setup and run commands if needed.

## Project rules

1. **Architecture:** client-server. The backend exposes an HTTP API under `/api`; the frontend consumes it. Keep business logic on the backend.
2. **Technologies:** backend in Python (FastAPI), frontend in React with TypeScript (Vite). Do not introduce other languages or frameworks without asking.
3. **Development log:** keep `DEVLOG.md` up to date. At the end of each piece of work, add a dated session entry with:
   - **Completed**: what was done and verified
   - **Changes**: notable modifications to existing code or structure
   - **Open / next tasks**: unfinished work and known issues
4. **Application logging:** use the project loggers with levels DEBUG, INFO, WARNING, ERROR, CRITICAL. Do not use bare `print` or `console.log`.
   - Backend: `from app.logging_config import get_logger; logger = get_logger(__name__)`. Level is set by `LOG_LEVEL`; output goes to the console and `backend/logs/app.log`.
   - Frontend: `import { getLogger } from "./logger"; const logger = getLogger("Name");`. Level is set by `VITE_LOG_LEVEL`; output goes to the browser console.

## Layout

```
backend/    FastAPI app (app/main.py, app/logging_config.py), venv in backend/.venv
            app/models.py          PostgreSQL tables (SQLAlchemy); app/db.py connection
            app/gfi_store.py       GFI data source: PostgreSQL or Excel + SQLite
            app/gfi_import.py      one-time import of a GFI workbook into PostgreSQL
            migrations/            Alembic schema migrations (alembic.ini)
            .env                   local settings, git-ignored (see .env.example)
frontend/   React + TS (src/), Vite dev server proxies /api -> http://localhost:8000
            src/components/ui      shadcn/ui components (vendored)
            src/components/layout  app shell: sidebar, header, main
            src/pages              route pages; src/config/navigation.ts sidebar items
.vscode/    tasks.json: "Start all" runs both dev servers with auto-reload
DEVLOG.md   development progress log
```

The application is named **Income Tax Reporting** (FastAPI title, sidebar, Login page, browser tab title; npm package `income-tax-reporting-frontend`).

## Commands

- Backend dev server (from `backend/`): `.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000`
- Frontend dev server (from `frontend/`): `npm run dev`
- Frontend type check (from `frontend/`): `npx tsc -p .`
- App: http://localhost:5173; API docs: http://localhost:8000/docs
- Database schema (from `backend/`, needs `DATABASE_URL`): `.venv\Scripts\alembic upgrade head`. After changing `app/models.py`, create a migration with `.venv\Scripts\alembic revision --autogenerate -m "..."`, review it, and check with `.venv\Scripts\alembic check`.
- GFI import (from `backend/`): `.venv\Scripts\python -m app.gfi_import <year> --dry-run`, then without `--dry-run`. Use `--replace` to import a year again.

## Data rules

- GFI workbooks (`<year> GFI *.xlsx` in `GFI_DATA_DIR`, default the project root) are **read-only**. Never write to them.
- **Migracija** (`app/migration.py`, page `/migration`, sidebar "Administracija"; PostgreSQL only): the next year (latest + 1) is constructed from the latest year with the companies chosen in a dialog (registry of all companies). Carried over: NAZIV, PIB, REFERENT, office (current values); status columns start at 0. Constructed years: `source_file.origin = 'constructed'`; a deselected company is hidden (`company_year.active = false`), never deleted. The year then appears in the Reporting year selector; the selector itself never offers to add a year. Construction also creates the year's PB-1 form (`ensure_pb1_form`: a constructed 'pb1' source_file): the same three tabs as the source year's form as shown in the app (its form-level settings copied: shared template edits, default comments), all amounts 0, no file values for anyone, years in read-only texts moved on (`pb1_template`, `shift_years`).
- **PostgreSQL is the main database for GFI data** (PostgreSQL 18, SQLAlchemy 2.1, psycopg 3, Alembic). It is used when `DATABASE_URL` is set (`backend/.env`); **active since 2026-11-12** (database `income_tax_reporting`, 2025 imported). PB-1 (edits, comments, settings in SQLite `edits.db`), users and sessions are not in the database yet.
  - The user installs PostgreSQL themselves when it is needed. Do not install it.
  - Without `DATABASE_URL`, the app falls back to the Excel workbook with edits in SQLite (`backend/data/edits.db`, `DATABASE_PATH`, git-ignored; `app/edits_store.py`). Both modes return the same API responses (`app/gfi_store.py`).
  - Data gets into PostgreSQL only through `app/gfi_import.py`. It keeps only the company list (rows while R.B. continues 1, 2, 3, …; 2025: 165 companies up to DAGOTTA), carries over every SQLite edit on the first import, and verifies every cell against the Excel + SQLite output before committing. It never writes the Excel file or SQLite.
  - Referents and offices are lookups: a name no company uses any more is removed when a company's referent / office changes (`_drop_if_unused` in `app/gfi_store.py`).
  - Before deleting or replacing database records, check that no user edits are lost. `--replace` refuses while any value differs from the import snapshot; `change_log` history is always kept.
  - Schema: `reporting_year`, `source_file` + `gfi_column` + `source_cell` (read-only snapshot of the original cells: values, formats, formula flags), `company`, `company_year` (current values, addressed by Excel row `source_row`), `referent`, `office`, `import_issue`, `change_log`. Change it only through Alembic migrations.
  - Company identity: each company-list row is its own company. PIB is stored exactly as in Excel; it is not required or unique. Problems (missing / shared / non-9-digit PIB) are recorded in `import_issue`, never merged or guessed.
- Editing rules (`edit_kind` in `app/gfi_store.py`, the same in both storage modes, enforced by the backend). Columns are identified by header, never by letter.
  - **Formula columns, in every row, on Home and Registry:** GFI ZA RAD = kom − GFI uradjen, PB-1,PB-2 za rad = PB-1, PB-2 − PB-1, PB-2 Predat (`FORMULA_FIELDS` in `app/models.py`; an empty value counts as 0). Computed by the API (`apply_formulas` in `app/companies.py`) from the current values, never editable, not stored in the database. A cell update returns the row's recomputed formulas (`formulas`), and the page shows them at once. Formula cells don't react to the mouse on any page (no highlight, preview or tooltip).
  - Other numeric GFI status columns (kom, Preliminarni, GFI uradjen, PB-1, PB-2, Predat): numbers, and empty (or blank-text) cells that can be filled in; formula and other text cells are read-only. **Home edits only cells that hold a number in Excel**; the Company Registry also fills empty ones. Clearing a filled cell back to empty counts as not edited.
  - Company details: NAZIV, PIB, REFERENT and the unnamed office column after it, edited as text (cell flag `text`). NAZIV can't be empty; PIB is digits only. The API marks them editable, but **only the Company Registry page edits them**; Home shows them read-only.
  - Other columns are read-only.
- **R.B. is not kept anywhere.** It is read only from the Excel workbook to find the company list (`company_list` / `main_list_rows` in `app/gfi_workbook.py`, used by the API in Excel mode and by the import). The API, the database and the pages never contain the R.B. columns. The `#` column is the company's position in the list (1, 2, 3, …).
- Company identity is the Excel row (database: `company` / `company_year` ids); editing a name or PIB changes the record in place.
- Home has an **Actions** column (last) with three buttons in three colors (`--chart-1..3`), one per tab of the company's PB-1 form: PB (Poreski bilans, what clicking the name used to open), Uporedo, Prelim. Company names are not links.
- Under the Home table (Home only): statistics cards for Preliminarni, GFI uradjen and GFI ZA RAD, each with its total over all companies and its share of the kom total. Computed by the API (`stats` in `app/companies.py`, from current values with formulas applied, empty = 0) and returned again with every cell update; `GfiStats` only displays them.
- Pages: Home (`variant="home"`: compact, display substitutions) and Company Registry (`/company-registry`, `variant="registry"`) show the same data through `GfiTableView` / `useGfiEditor`. All edits go through one autosave queue (`CellAutosaveProvider` in `AuthenticatedLayout`), stored in `localStorage` until saved.
- Company Registry layout (user's rules): its purpose is editing what Home can't, so it is never condensed like Home (NAZIV and PIB are separate columns).
  - Columns: `#`, NAZIV, PIB, REFERENT, office, kom … ending with "PB-1,PB-2 za rad" (nothing after it).
  - It always fits the screen width: `table-fixed` with column widths in percent, no horizontal scroll. Nothing is truncated (no "…"): long values wrap and the row grows.
  - Empty cells show `0` from kom (included) to the right and `-` in the columns left of kom (display only, same rules as Home). They stay editable; opening an empty cell shows an empty editor, so just clicking never stores a value.
  - Read-only cells (including `#`) don't react to the mouse: no highlight, no enlarged preview, no tooltip. No tooltips naming Excel rows or columns anywhere in the Registry. Editable cells keep the highlight, preview and edit tooltips.
- Numbers are displayed with the cell's Excel number format via `src/lib/excel-format.ts` (Serbian separators `1.234,56`).
- PB-1: `<year> PB-1.xls` (same folder, read with `xlrd`, never written). **Every company has one PB-1 form with three tabs**, the three sheets of the workbook (`PB1_TABS` in `app/pb1_workbook.py`; page `/companies/:year/:row/pb1/:tab`):
  - `poreski-bilans`: "Poreski bilans", columns A–F from the header row down, plus G shown as "Konto" (konto numbers as written, no number format); amounts C, D, E.
  - `uporedo`: "Uporedo <year> i <year-1>", columns A–E from the header row (R.b. | Opis | year | year-1 | Index); amounts C, D, E.
  - `preliminarni`: "Preliminarni rezultat", columns A–G, rows 2–42 (two tables side by side and the sections below), no header row; amounts C and G.
  - The other columns are the template shared by all companies. Helper columns (H–Q, H–J), title rows and company names written on the sheets are not part of the form.
  - Line-number columns (`narrow_columns`) are headed `#` and as narrow as their numbers; a longer text in them overflows into the empty cells to its right. Nothing in the PB-1 tables is truncated: text wraps.
  - Typos in the form's descriptive texts are corrected for display only (`app/pb1_texts.py`: general cleanup + `CORRECTIONS`, keyed by the cleaned original text); the spelling without diacritics is kept. Numbers and konto lists are right-aligned, comments in words left-aligned.
  - Headers are on one line and left-aligned. Poreski bilans: its last four rows (from "V. Poreska osnovica") are a separate summary table below the form (`summary_label` / API `summary`), with column widths taken from the form table. Its first three sheet rows (title, company name with "Klasa 5 | Klasa 6", class totals) are a separate table above the form (`head_rows` / API `head`; only its used columns B–F are drawn, each above its own column): every number in them is the company's amount; D1 is the number of months in business (`months_cell`, labelled "Meseci poslovanja" in C1; monthly advance = tax / months). For now fixed at 12 and read-only (`MONTHS_EDITABLE = False`); per company (1–12) is prepared for a later automatic calculation, texts are read-only, and the company name written in the file is replaced by the form's company name. The head rows keep their Excel fill colors (API `fill`; the only place where colors come from data: CSS variable `--cell-fill`, as in Excel in light mode, mixed 25% into the background in dark mode).
  - PB-1 tables don't react to the mouse (no hover highlight or preview); rows with a bold description are shaded (`bg-muted/60`, API `shaded`).
  - PB-1 fields editable by click: amounts (per company: GFI workbook + row) and every other field, also empty ones (template, shared by every company; empty fields in amount columns as numbers). Read-only only what the user listed: `#`, headers, Opis in every tab (`readonly_columns`), and in Preliminarni rezultat the right table's texts (E, F) and everything above Opis incl. the "R.b. | Opis | RSD" row (`readonly_top`). An amount field holding " " or an Excel error counts as empty. Saved through the app-wide autosave queue to `PUT .../companies/{row}/pb1/{tab}/cells/{column}/{cell_row}`, stored in SQLite `pb1_edits` (both modes, until the PB-1 migration). All writes go through `save_pb1_cell()` in `app/pb1.py`, which automation must use too.
  - Only the company the file belongs to (2025: FRIGOLAKTA) gets the amounts, in all three tabs; every other company sees the empty frame.
  - Amount fields (`amount`: amount-column cells holding a number, an Excel error or blank text in the file; the same for every company) show their value with exactly two decimals (`withDecimals`, keeping the cell's negative/percent style) and `0,00` when they have no number. Amount columns are right-aligned; every column has a vertical border. Template text in amount columns (e.g. "RSD") is shown to every company.
  - The Excel forms are hand-made: amount fields follow the form's logic, not only the cell types. Corrections (form lines without an amount cell, spacer rows with stray ones) are listed in `PB1_TABS[].amount_fixes`, checked against the row's description.
  - User reviews PB-1 changes on FRIGOLAKTA; every change applies to the shared form of all companies.
  - **Company actions** above the tabs (`Pb1CompanyActions`): "Sačuvaj izmene" (flush the autosave queue), "Preuzmi PDF", "Štampaj PDF" (both save first). Switching tabs and Back also save first (`flush`). The PDF is built by the backend (`app/pb1_pdf.py`, ReportLab, `GET .../pb1-pdf`) from `build_pb1_table`, so it always matches the page; it needs a TrueType font with č/ć/đ (`PDF_FONT`).
  - **Tax loss** (`LOSS_RULES` in `app/pb1.py`): a negative tax base (Poreska osnovica) makes its tax 0 and read-only (PB C87, Uporedo C13/D13, Preliminarni C14); the monthly advances follow through their formulas. The PB-1 page shows a red "Gubitak!" banner from the Poreski bilans base (API `loss`).
  - **Comments** (Poreski bilans, column F "Komentar, stopa, konto"): not a table column; shown beside the table (`Pb1Comments`) as "# · Opis → komentar", one per row. Defaults = settings (`pb1_comment_defaults`, filled once from the workbook: what the table held). A comment written in the app applies only to that company (`pb1_edits`, column F, company identity). Rates (percent numbers) stay numbers and feed the formulas per company; konto numbers are text.
  - **Formulas:** cells that hold a formula in the PB-1 workbook are computed in the app with that formula (`FORMULAS` + evaluator in `app/pb1_formulas.py`, extracted from the 2025 workbook), from the current values of the whole form across tabs, edits included; read-only (`formula`). References are Excel addresses = the app's internal row keys (Excel rows), never the "#" line numbers. Helper cells outside the form come from the file for the file's company, else empty. Every workbook load checks all formulas against Excel's stored results; on any difference the computed cells are switched off for that workbook (ERROR in the log). A new year's template needs its formulas re-extracted (Excel on a read-only copy) if they differ.
  - PB-1 data is not in the database yet: the pages are finalized first, then it is migrated in one step (including the SQLite `pb1_edits`).
  - The amounts are shown only for the company the file belongs to. **PB-1 is linked to the company's identity, never looked up by its current name or PIB:** the link is stored (`pb1_links` in SQLite, `pb1_link` → `company_year` in PostgreSQL; `pb1_owner_row` in `app/pb1.py`).
  - The link is made once from the company name written in the PB-1 file (the file has no PIB), compared with the **original** GFI names (`normalize_company_name`); exactly one company of the list must match. It is made again only if the PB-1 file names a different company, or the linked company is no longer in the list / the GFI workbook was replaced. Only companies of the list (165) can be linked. Never match by table position.
  - The PostgreSQL import carries the SQLite PB-1 links over by company identity.

## Design guidelines

The permanent visual style is modeled on **Shadcn Admin** (https://github.com/satnaing/shadcn-admin). Every new page and component must follow it.

**Stack**
- Tailwind CSS v4 (via `@tailwindcss/vite`) and **shadcn/ui**, style `new-york`, base color `neutral` (see `frontend/components.json`). Radix primitives come from the `radix-ui` package.
- Icons: `lucide-react` only. Font: Inter (`@fontsource-variable/inter`).
- React 19 (needed so shadcn components forward refs correctly).
- Import paths use the `@/` alias for `src/` (for example `@/components/ui/button`).

**Components**
- Build UI from shadcn components in `src/components/ui/`. If one is missing, add it with `npx shadcn@latest add <name>` (from `frontend/`). Do not hand-roll an equivalent.
- After adding a component, check its imports. The CLI has written `from "cn"` instead of `from "@/lib/utils"` and installed an unrelated `cn` npm package. Fix the imports and uninstall that package if it appears.
- Treat `src/components/ui/` as vendored: avoid editing these files. Customize through `className` at the call site.
- Merge classes with `cn()` from `@/lib/utils`.

**Colors and theming**
- Use only the semantic theme tokens (`bg-background`, `text-foreground`, `bg-card`, `text-muted-foreground`, `bg-primary`, `text-destructive`, `border`, `bg-sidebar`, ...). They are defined in `src/index.css` for light and dark.
- Never hard-code colors (no hex values, no `text-gray-500`, no inline `style` colors). Every UI must work in both light and dark.
- Accent colors: `chart-1`, `chart-2`, `chart-3` (shadcn chart palette, defined for light and dark in `src/index.css`), e.g. tinted buttons `border-chart-1/40 bg-chart-1/10 text-chart-1`.
- Status colors: `text-success` (green, token `--success`, light and dark in `src/index.css`) and `text-destructive` (red). Home colors the 0 / 1 values of Preliminarni … PB-1,PB-2 za rad: 1 green, 0 red (`statusColors` in `CompanyTable`).
- Theme: `ThemeProvider` (`src/context/ThemeProvider.tsx`) supports light, dark and system, saved in `localStorage` (`ui-theme`). It toggles the `.dark` class on `<html>`. Users switch it with `ThemeSwitch` in the header.

**Layout**
- Logged-in pages render inside `AuthenticatedLayout` (`src/components/layout/`). It contains a collapsible floating `AppSidebar` (logo, nav groups, user menu with Log out), a sticky `Header` (sidebar toggle, theme switch, profile menu) and the routed page.
- A new page is a route nested under the `AuthenticatedLayout` route in `App.tsx`. Wrap its content in `<Main>`, and add a sidebar entry in `src/config/navigation.ts` (title, url, lucide icon).
- Page header pattern: `<h1 className="text-2xl font-bold tracking-tight">Title</h1>`, with an optional `<p className="text-muted-foreground">` description below.
- Public/auth pages (such as Login): a centered `max-w-sm` column on `bg-muted/40`, with the logo above a `Card`.

**Patterns**
- Forms: `Label` + `Input` pairs in `grid gap-2`; fields in `grid gap-4`; a full-width primary `Button` with a `Loader2 animate-spin` icon while submitting.
- Errors: `Alert variant="destructive"` for form or page errors, and `aria-invalid` on invalid inputs.
- Spacing and shape: Tailwind spacing scale (`gap-2/4/6`, `p-4`, `px-4 py-6`), radius tokens (`rounded-md`, `rounded-lg`), and subtle borders. Keep it minimal and clean, without decorative gradients or heavy shadows.
- Responsive: layouts must work at mobile width (the sidebar becomes a sheet below `md`).
- Data tables: follow `src/components/CompanyTable.tsx`.
  - Use one `overflow-auto rounded-md border` scroll container with a max height, and a raw `<table>` with shadcn `TableHeader/TableRow/TableHead/TableCell`. Don't use the `Table` wrapper, because its own scroll box breaks sticky headers.
  - Header row: sticky `bg-muted`. Row numbers: a sticky left column.
  - Numbers: `text-end tabular-nums`.
  - Cells: `hover:bg-accent` with an enlarged hover preview of the full value.
  - `SidebarInset` has `min-w-0`, so wide content scrolls inside the page instead of widening it.

## Working conventions

- Implement only what is requested; do not add business functionality ahead of instructions.
- Commit only when asked.
