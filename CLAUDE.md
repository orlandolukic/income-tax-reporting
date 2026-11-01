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
frontend/   React + TS (src/), Vite dev server proxies /api -> http://localhost:8000
            src/components/ui      shadcn/ui components (vendored)
            src/components/layout  app shell: sidebar, header, main
            src/pages              route pages; src/config/navigation.ts sidebar items
.vscode/    tasks.json: "Start all" runs both dev servers with auto-reload
DEVLOG.md   development progress log
```

## Commands

- Backend dev server (from `backend/`): `.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000`
- Frontend dev server (from `frontend/`): `npm run dev`
- Frontend type check (from `frontend/`): `npx tsc -p .`
- App: http://localhost:5173; API docs: http://localhost:8000/docs

## Data rules

- GFI workbooks (`<year> GFI *.xlsx` in `GFI_DATA_DIR`, default the project root) are **read-only**. Never write to them.
- User edits are stored in SQLite (`backend/data/edits.db`, `DATABASE_PATH`, git-ignored; `app/edits_store.py`) and applied on top of the Excel values by the API.
- Only plain numeric cells are editable; formula, text and empty cells are read-only (enforced by the backend).
- Numbers are displayed with the cell's Excel number format via `src/lib/excel-format.ts` (Serbian separators `1.234,56`).
- PB-1: `<year> PB-1.xls` (same folder, read with `xlrd`, never written), sheet "Poreski bilans", columns A–F from the header row down.
  - Columns A, B and F are the template shared by all companies; C, D and E are amounts.
  - The amounts are shown only for the company the file belongs to, matched by identity: the normalized name (`normalize_company_name`) must match exactly one GFI company, and its PIB must match too. Never match by table position.

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
