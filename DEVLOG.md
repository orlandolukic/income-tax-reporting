# Development Log

Read this file at the start of each new Claude Code session to restore project context.

## Project rules

1. **Architecture:** client-server.
2. **Technologies:** Python backend (FastAPI), React frontend (TypeScript, Vite).
3. **Development log:** this file records completed work, changes, and open tasks.
4. **Application logging:** DEBUG, INFO, WARNING, ERROR, CRITICAL levels on both backend and frontend.

---

## 2026-11-01: Session 1: Project skeleton

### Completed
- Backend: FastAPI app in `backend/app/main.py` with `GET /api/health`, CORS for `localhost:5173`.
- Backend logging: `backend/app/logging_config.py`. Console + rotating file `backend/logs/app.log`, level from `LOG_LEVEL`.
- Frontend: Vite + React 18 + TypeScript in `frontend/`. Page shows "Application is running" plus backend health status.
- Frontend logging: `frontend/src/logger.ts`. Level from `VITE_LOG_LEVEL`, outputs to the browser console.
- Vite dev proxy: `/api` → `http://localhost:8000`.
- VS Code tasks in `.vscode/tasks.json` ("Start all" runs both dev servers with auto-reload).
- README with setup and run instructions.
- Verified: both servers start, `/api/health` responds through the proxy, `tsc` passes, logs are written to the file.

### Environment notes
- Python 3.14.4, Node 22.21.0, npm 10.9.4 on Windows.
- Backend venv: `backend/.venv` (git-ignored).

### Open / next tasks
- No business functionality yet. Waiting for requirements.
- Possible later: shipping frontend logs to the backend, tests (pytest / vitest), linting, and env-based config.

---

## 2026-11-01: Session 2: Basic authentication

### Completed
- Backend:
  - `app/security.py`: password hashing with PBKDF2-HMAC-SHA256 (stdlib, 600k iterations, random salt) and a constant-time verify.
  - `app/users.py`: single test user `nikola`, stored as a hash only (no plaintext anywhere in source).
  - `app/auth.py`: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`. Server-side sessions with a random token in an `HttpOnly`, `SameSite=Lax` cookie `session_id`. The same error is returned for unknown user and wrong password, and a dummy hash check is run for unknown users so timing doesn't reveal which usernames exist.
  - Logging: WARNING on failed login, INFO on login/logout, DEBUG on unauthenticated session checks. Passwords and session tokens are never logged.
- Frontend:
  - Added `react-router-dom@6.28.0`. Routes: `/login`, `/` (protected), `*` redirects to `/`.
  - `src/auth/AuthContext.tsx` (session restore via `/api/auth/me`, login, logout), `src/auth/ProtectedRoute.tsx`.
  - `src/pages/LoginPage.tsx`: username/password form with an error message on invalid credentials.
  - `src/pages/HomePage.tsx`: "Home" heading plus a Logout button.
- Verified in the browser (Chrome): `/` redirects to `/login` when logged out; a wrong password shows "Invalid username or password."; correct credentials redirect to Home; the session survives a page reload; Logout returns to `/login`; `/` is blocked after logout. Also verified with curl. Checked `app.log`: no passwords or tokens.

### Changes
- `app/main.py`: includes the auth router; CORS now sets `allow_credentials=True`.
- `src/App.tsx`: replaced the "Application is running" + health status page with the router. `/api/health` still exists on the backend.

### Notes
- Sessions are kept in memory, so a backend restart or auto-reload logs everyone out.
- To create a hash for a new password: `cd backend; .venv\Scripts\python -c "from app.security import hash_password; print(hash_password(input()))"`
- `npm audit` reports 3 high-severity vulnerabilities in the dev dependency tree. Not addressed yet.

### Open / next tasks
- Persistent user storage and sessions (database) when needed.
- Possibly later: session expiry, login rate limiting, and the `Secure` cookie flag when served over HTTPS.

---

## 2026-11-01: Session 3: Environment cleanup and verification

No application code or dependencies were changed in this session.

### Completed
- **Stopped stray dev servers.** Found three sets running at the same time: the 00:29 backend (uvicorn reloader + worker, port 8000), the 00:29 Vite instance (port 5173), and a Vite test instance from session 2 (port 5174). All were stopped, and ports 8000, 5173 and 5174 were confirmed free.
  - Root cause of the session 2 problem: the old Vite on 5173 was not proxying `/api` (requests fell through to `index.html`), and two uvicorn processes were bound to port 8000 at once. A fresh start fixed both.
- **"Start all" task commands verified.** Ran the exact commands from `.vscode/tasks.json` (same working folders, through PowerShell). Backend listened on `127.0.0.1:8000`, Vite on `localhost:5173`.
- **API verified through the 5173 proxy and directly on 8000:** health 200; `/me` while logged out 401; bad login 401; good login 200 with cookie; `/me` while logged in 200; logout 204; `/me` after logout 401.
- **Browser verified (Chrome, port 5173):** `/` redirects to `/login`; wrong password shows the error; correct login goes to Home; reload keeps the session; Logout returns to `/login`; `/` is blocked after logout. No console errors.
- Afterwards, all test servers were stopped so that "Start all" in VS Code starts cleanly.
- The untracked `2025 GFI TOKK 1.xlsx` was not touched and not added to Git.

### npm audit: 3 high-severity findings (not fixed yet)
All three come from a single direct dependency, `react-router-dom@6.28.0`, which was added in session 2:

| Package | Type | Installed |
|---|---|---|
| `react-router-dom` | direct | 6.28.0 |
| `react-router` | transitive | 6.28.0 |
| `@remix-run/router` | transitive | 1.21.0 |

Underlying advisories:

| Advisory | Summary | Severity | Fixed in |
|---|---|---|---|
| GHSA-2w69-qvjg-hvjx | XSS via open redirects | high | `@remix-run/router` 1.23.2 (react-router 7.12.0) |
| GHSA-2j2x-hqr9-3h42 | Open redirect via `//` path | medium | 6.30.4 / 7.14.1 |
| GHSA-9jcx-v3wj-wh4m | External redirect via untrusted paths | medium | 6.30.2 / 7.9.6 |
| GHSA-wrjc-x8rr-h8h6 | Open redirect via backslash in `<Link>`/`useNavigate` | medium | 7.18.0 only (no v6 fix) |
| GHSA-337j-9hxr-rhxg | Constructor injection in SSR hydration | medium | 7.18.0 only (no v6 fix) |

**Real exposure today is low.** The app uses `BrowserRouter` (no data router, loaders or `redirect()`), has no SSR, and only navigates to fixed paths (`/`, `/login`). It never navigates to user-supplied URLs.

**Options:**
1. **Recommended: upgrade to React Router v7** (latest 7.18.5). This clears all 5 advisories. For our simple usage the migration is small: install `react-router`, change the imports from `react-router-dom` to `react-router`, and re-test login and logout.
2. Interim: upgrade to `react-router-dom@6.30.6`. Semver-compatible with no code changes. Clears the high-severity finding and 2 of the medium ones, but GHSA-wrjc and GHSA-337j stay open because they have no v6 fix.

### Open / next tasks
- Decide on and apply the react-router upgrade (option 1 recommended).
- Before running "Start all", make sure no older dev servers are still running (otherwise ports collide, as happened in session 2).

---

## 2026-11-01: Session 4: React Router v7 upgrade

### Changes
- Dependencies (`frontend/package.json`, `package-lock.json`): removed `react-router-dom@6.28.0` and added `react-router@^7.18.5` (latest stable). In v7 everything is in the single `react-router` package, so `react-router-dom` is no longer needed. Requirements are met: Node >= 20 (we have 22) and React >= 18.
- Code: only the import source changed, from `"react-router-dom"` to `"react-router"`, in `src/App.tsx`, `src/auth/ProtectedRoute.tsx`, `src/pages/HomePage.tsx` and `src/pages/LoginPage.tsx`. No logic changes. The APIs we use (`BrowserRouter`, `Routes`, `Route`, `Navigate`, `useNavigate`) work the same in v7.

### Test results
- `tsc` type check passes; `npm run build` passes.
- Servers started with the "Start all" task commands: backend on 8000, Vite on 5173.
- API through the 5173 proxy and directly on 8000: health 200; `/me` while logged out 401; bad login 401; good login 200; `/me` while logged in 200; logout 204; `/me` after logout 401.
- Browser (Chrome, port 5173): `/` redirects to `/login`; wrong password shows the error; correct login goes to Home; reload keeps the session (it stayed logged in for 15+ seconds with no activity); Logout returns to `/login`; `/` is blocked after logout. No console errors or React Router warnings.
- `backend/logs/app.log` contains no passwords or tokens.
- **`npm audit`: 0 vulnerabilities** (also 0 with `--omit=dev`). All 5 react-router advisories from session 3 are resolved.

### Notes
- Testing note: the Chrome automation tool's `find` action clicked the Logout button by accident during testing, which looked like a spontaneous logout. Confirmed it is not an app bug (the session stays active when the page is left alone). Use `read_page` to locate elements in future browser tests.
- All test servers were stopped afterwards. `2025 GFI TOKK 1.xlsx` was left untouched and untracked.

### Open / next tasks
- None from this upgrade.

---

## 2026-11-01: Session 5: Shadcn Admin design

### Completed
- Adopted a visual style modeled on Shadcn Admin (https://github.com/satnaing/shadcn-admin) as the permanent app design. Design guidelines are documented in `CLAUDE.md` > "Design guidelines".
- **Stack:** Tailwind CSS v4 (`@tailwindcss/vite`), shadcn/ui (`new-york` style, `neutral` base color, Radix via the `radix-ui` package), `lucide-react` icons, Inter font (`@fontsource-variable/inter`), and `tw-animate-css`.
- **Theme:** light, dark and system via `src/context/ThemeProvider.tsx`, saved in `localStorage` (`ui-theme`). An inline script in `index.html` applies it before first paint (no flash). `ThemeSwitch` dropdown in the header.
- **App shell** (`src/components/layout/`): `AuthenticatedLayout` = collapsible floating `AppSidebar` (logo, "General > Home" nav, `NavUser` menu with Log out) + sticky `Header` (sidebar toggle, theme switch, `ProfileDropdown` with Log out) + routed content in `Main`.
- **Pages:** Login is now a centered card (logo, Username/Password, spinner on submit, destructive `Alert` for errors). Home shows a "Home" heading inside the shell.
- shadcn components added in `src/components/ui/`: alert, avatar, button, card, dropdown-menu, input, label, separator, sheet, sidebar, skeleton, tooltip (+ `src/hooks/use-mobile.ts`, `src/lib/utils.ts`).

### Changes
- **React 18 to 19** (`react`, `react-dom`, `@types/*` 19.3). Needed because current shadcn components rely on React 19 ref-as-prop; on 18, dropdown and tooltip positioning breaks. react-router 7.18.5 supports React 19.
- `vite.config.ts`: Tailwind plugin and `@` → `src` alias. `tsconfig.json`: `baseUrl` and `paths` for `@/*`. Added `components.json` (shadcn config) and `@types/node` (dev).
- `App.tsx`: wrapped in `ThemeProvider` and `TooltipProvider`. `/` is now a child route of a protected layout route (same URLs and same protection).
- Logout moved from a page button into the header profile menu and the sidebar user menu (both use the new `src/auth/useLogout.ts`; the same `AuthContext.logout()` as before). Auth logic, backend and API are unchanged.
- shadcn CLI note: `shadcn init` (v4.23) only offers interactive presets, so `components.json` was written by hand. `shadcn add` generated `import { cn } from "cn"` and installed an unrelated npm package `cn`. Fixed the imports to `@/lib/utils` and uninstalled `cn`. This is recorded in CLAUDE.md as a check after every `shadcn add`.

### Test results
- `tsc` passes; `npm run build` passes; **`npm audit`: 0 vulnerabilities**.
- Browser (Chrome, against the user's running "Start all" servers on 5173/8000):
  - Light and dark rendering of the Home shell and Login page. Theme switch works and persists across reload. "System" restored afterwards.
  - Sidebar collapses to icons and expands. Dropdowns (theme, profile, sidebar user menu) are positioned correctly.
  - `/` redirects to `/login` when logged out. A wrong password shows the destructive alert with a red input outline. Correct login goes to Home.
  - Log out from the header profile menu and from the sidebar user menu both return to `/login`. `/` is blocked after logout.
  - No console errors. `app.log` contains no passwords or tokens.
- Found and fixed during testing: the header's vertical divider was full height. It is now `data-[orientation=vertical]:h-6`.

### Open / next tasks
- Mobile layout (sidebar as a sheet below `md`) not yet tested in the browser.
- The untracked `2025 GFI TOKK 1.xlsx` was left untouched.

---

## 2026-11-01: Session 6: Financial reporting year selector

### Completed
- **Year source (decided with the user):** the reporting year comes from the workbook **file name**, `<year> GFI <anything>.xlsx`. `2025 GFI TOKK 1.xlsx` gives **2025**. The sheet itself has no year column; the `F 01/2026`..`F 04/2026` headers are monthly columns, not reporting years. Adding another file such as `2026 GFI ....xlsx` will add 2026 automatically.
- **Backend:** `app/reporting_years.py` with `GET /api/reporting-years` → `{"years": [2025]}` (newest first, distinct, login required).
  - Scans `GFI_DATA_DIR` (env var; default is the project root).
  - Ignores Excel lock files (`~$...`).
  - Logs WARNING when no workbooks are found and ERROR when the folder is missing.
- `app/auth.py`: extracted the session check into a reusable `require_user` dependency. `/me` uses it, with the same behavior.
- **Frontend:**
  - `ReportingYearProvider` (`src/context/`) wraps the authenticated layout. It loads the years and holds the selected year.
  - `ReportingYearSelect` (shadcn `Select`) sits next to the "Home" heading.
  - The selection is saved in `sessionStorage` (`reporting-year`), so it survives reloads in the tab. It is cleared on logout (`useLogout`).
  - If the saved year is no longer available, the selection falls back to the newest year.
  - Loading shows a skeleton; errors show a destructive alert; an empty list shows a muted message.
- Added shadcn `select` (the `cn` import issue happened again and was fixed again; see CLAUDE.md).

### Test results
- `tsc`, `npm run build`: pass. `npm audit`: 0 vulnerabilities.
- `find_reporting_years` checked against test files: duplicates, `.XLSX` casing, `~$` lock file, non-GFI files, missing folder → `[2025, 2024]` / `[]` as expected. On the real folder → `[2025]`.
- API: 401 when logged out; `{"years":[2025]}` when logged in; `/me` still OK.
- Browser (5173): the Login page is unchanged; after login, Home shows "Reporting year: 2025".
  - With a temporary empty `2024 GFI _TEST.xlsx` (deleted after the test): both years are listed, and selecting 2024 is saved and survives reload.
  - Logout clears the selection, and the next login defaults to 2025.
  - When the saved 2024 file was removed, the selection fell back to 2025. No console errors.
- Fixed during testing: the dropdown list overlapped the trigger at the screen edge. It now uses `position="popper" align="end"`.
- Testing note: the Chrome tool's clicks do not open the Radix `Select` (it requires `pointerType: "mouse"`). The selector was exercised with JS-dispatched mouse pointer events. Please confirm once with a real mouse.

### Notes
- `openpyxl` was installed briefly to inspect the workbook, then uninstalled (not needed yet). Add it to `requirements.txt` when the Excel table is implemented.
- `2025 GFI TOKK 1.xlsx` is now tracked in Git (it was included in the user's commit `ee2abed`). It contains company names and tax IDs (PIB).

### Open / next tasks
- Company list / Excel table for the selected year (not started, as instructed).
- Decide whether the GFI workbooks should stay in Git or move to a data folder that is not tracked (`GFI_DATA_DIR`).

---

## 2026-11-01: Session 7: Company table (read-only)

### Completed
- **Backend:**
  - `app/gfi_workbook.py`: `read_company_table(path)` reads the first sheet, columns **A–N** only, with openpyxl (`read_only`, `data_only`).
    - Row 1 gives the headers, returned exactly as stored, including the duplicate "R.B.", the blank F and N headers, and spacing such as `"GFI uradjen "` and `"PB-1,  PB-2"`.
    - Values are returned exactly as stored (text / number / null). Formula cells return their cached result, as Excel displays it (e.g. `J = G - I`, `SUM`, `#REF!`). Dates would be sent as ISO strings.
    - Rows that are completely empty in A–N are skipped (2025: 432 → 319 rows). Each row keeps its **Excel row number** for the editing step.
    - Response: `{workbook, sheet, columns:[{key:"A", header}], rows:[{row, cells:{A..N}}]}`.
  - `app/reporting_years.py`:
    - New `GET /api/reporting-years/{year}/companies` (login required). 404 if there is no workbook for the year, 500 (logged with traceback) if it can't be read. INFO log with the row count.
    - Refactored `find_workbooks()` (year → files) and `get_workbook_path()`. If several workbooks match one year, the first by name is used and a WARNING is logged.
  - `requirements.txt`: added `openpyxl>=3.1`.
- **Frontend:**
  - `src/hooks/use-company-table.ts`: loads the table for the selected year and reloads automatically when it changes. The previous request is aborted so a slow response can't show the wrong year.
  - `src/components/CompanyTable.tsx`, a scrollable table:
    - Single scroll container with a max height and a sticky header.
    - Sticky left column with the Excel row number.
    - Numbers right-aligned with tabular figures; long text truncated.
    - **Cell hover:** highlight (`bg-accent`) plus an enlarged popover (`text-base`, full wrapped value). The last 3 columns open it to the left.
  - `HomePage`: subtitle "N rows · workbook name"; skeleton while loading, destructive alert on error. While a different year loads, the old table is dimmed.
  - Added shadcn `table` (the `cn` import issue happened again and was fixed again).
- **Layout/theme fixes found while testing:**
  - `SidebarInset` gets `min-w-0`; before, the wide table widened the whole page and pushed the header controls off screen.
  - `.dark { color-scheme: dark; }` so native scrollbars match the dark theme.
- CLAUDE.md design guidelines: added a "Data tables" pattern.

### Test results
- `tsc`, `npm run build`: pass. `npm audit`: 0 vulnerabilities. No passwords or tokens in `app.log`.
- Reader on the real file: 14 columns, 319 rows, first and last rows match the sheet.
- API: 401 when logged out; 2025 → 200, 319 rows, ~0.17 s; 1999 → 404; `abc` → 422.
- Browser (5173):
  - Table renders with the exact A–N headers; no page-level horizontal scroll.
  - Vertical and horizontal scrolling keep the header and row numbers in place.
  - Cell hover highlight and enlarged preview work, including the right-anchored preview on the last columns.
  - Dark mode OK.
  - With a temporary generated `2024 GFI _TEST.xlsx` (3 rows plus an extra column O; deleted after the test): switching to 2024 reloaded 3 rows without column O, and switching back reloaded the 319 rows of 2025.
  - No console errors.
- `2025 GFI TOKK 1.xlsx` is unchanged (read-only access; Git shows no modification).

### Notes for the editing step
- Values shown are the stored raw values, not Excel's display formatting (e.g. `#,##0` thousand separators are not applied; E302 shows `0.00001639803263197952`, which Excel displays as `0.00`).
- Many cells are formulas. If openpyxl saves the workbook, Excel's cached formula results are dropped until the file is reopened and recalculated in Excel, so `data_only` reads would return empty values for formula cells. This needs a strategy before autosave: e.g. don't write formula cells, recalculate the affected values on the server, or keep the cached values another way.
- Writes must target the Excel row number (`row`) and column letter.

### Open / next tasks
- Editing and autosave of table cells (next step).
- Decide whether to apply Excel number formatting in the display.

---

## 2026-11-01: Session 8: Editing, autosave, Excel number formatting

### Completed
- **Excel-like number formatting** (`frontend/src/lib/excel-format.ts`):
  - Uses each cell's Excel number format. Supports General, numeric patterns (`#,##0`, `#,##0.00`, `0.##` ...), positive/negative/zero sections, `[Red]` negatives (shown in `text-destructive`), parentheses, `\x` / `"..."` literals, `_x` padding, `%` and `@`.
  - Serbian separators (`1.234,56`), set by `THOUSANDS_SEPARATOR` / `DECIMAL_SEPARATOR`.
  - Date/time formats on numbers fall back to General (none in the current data).
- **Editing:** a click (or Enter / F2 on a focused cell) opens an inline editor.
  - Enter or leaving the field saves; Escape cancels.
  - Input accepts `1234,56`, `1.234,56`, `1234.56` and `1.500` (= 1500). Empty clears the cell. Invalid input shows a red outline and isn't saved.
  - Edited cells show a corner marker; the tooltip shows the Excel value. Formula cells have the tooltip "Formula (read-only)".
  - Only plain numeric cells are editable: 1,373 cells in 2025. The 409 formula cells, text and empty cells are read-only, and the backend enforces it (409).
- **Storage:** SQLite `backend/data/edits.db` (`DATABASE_PATH`; git-ignored), table `cell_edits(workbook, sheet, row, col, value, original_value, updated_by, updated_at)`.
  - Created at startup (`init_db`). The Excel file is never written.
  - Saving the Excel value again deletes the override.
  - If the Excel value changes after an edit, the edit is kept and a WARNING is logged.
- **API:**
  - `GET /api/reporting-years/{year}/companies` now returns per cell `value, format, formula, editable, edited, original`, with default fields omitted, and with the edits applied. GZip enabled (180 KB → 9 KB).
  - `PUT /api/reporting-years/{year}/cells/{column}/{row}` with `{"value": number|null}` returns 200, 401, 404 (no such cell), 409 (read-only) or 422 (not a number).
  - Backend refactor: `gfi_workbook.py` reads values and formulas (two openpyxl passes) and caches the result by file mtime. New `companies.py` (table + edit endpoints) and `edits_store.py`. `reporting_years.py` now only handles year discovery.
- **Autosave** (`use-cell-autosave.ts`):
  - The change appears in the table immediately and is queued. Queued changes for the same cell are merged, and the queue is sent one request at a time.
  - Unsaved changes are kept in `localStorage` (`pending-cell-edits`), so they survive reload, logout and session expiry. They are applied over the loaded table and sent when the user is back.
  - Network or server errors: automatic retry every 10 s plus a Retry button. Rejected changes (404/409/422) are dropped and the table reloads.
  - 401: `AuthContext.markSessionExpired()` returns to Login, which shows "Your session has expired… unsaved table changes are kept and will be saved". After login, the queue is sent.
- **Save indicator** (`SaveStatus.tsx`, next to the year selector): "Saving…" (spinner), "All changes saved" (check, time in tooltip), or a red error with the count of unsaved changes and Retry.

### Test results
- Formatter and parser: 25/25 cases pass (scratch script with `tsx`), including `(1.234)` red, `0,00`, `1,6398E-05`, `25,6%`, `1.234,56`.
- API: edit 200; formula, text and empty cells 409; missing cell 404; non-number 422; logged out 401; clear and revert OK; the DB returns to 0 rows after a revert.
- Browser (5173), all checks passed:
  - G2 `1.234,5` → shown as `1.235` (`#,##0`) with the corner marker, "All changes saved", and the value kept after reload.
  - J2 (formula) and C2 (text) don't open an editor. `abc` is rejected (red); Escape restores the value.
  - **Network failure** (simulated): red "Can't reach the server. 1 unsaved change kept, retrying…" with Retry; after the network was restored the change saved.
  - **Session expiry** (server session ended behind the UI's back): editing I2 went to Login with the notice and the change stayed in localStorage. After login it saved automatically.
  - **Logout → login:** all edits restored. Dark mode OK.
  - Real-data formatting: E302 `0,00`, D296 `3.650.596.059`, I362 `141.110`.
- Test edits were reverted afterwards (DB = 0 rows). `2025 GFI TOKK 1.xlsx` is unchanged (Git: no modification). `tsc`/build pass, `npm audit` 0 vulnerabilities, no secrets in `app.log`.
- Found and fixed during testing: the corner marker was invisible (`border-transparent` overrode the coloured sides).

### Known limitations / open questions
- **Formula cells are not recalculated.** They show Excel's cached results. E.g. editing G2 does not update `J2 = G2 - I2`. Options: evaluate simple formulas on the server, or mark dependent cells as possibly stale.
- **Empty cells are not editable** (only cells that contain a number in Excel). Status columns such as H–M have empty cells that users may want to fill.
- Edits are keyed by workbook file name + row + column. If the Excel file is replaced with a version whose rows are reordered, edits would land on the wrong rows.
- Edits are shared by all users (`updated_by` records who). Changes queued on a device are sent under whichever user logs in next on that browser.
- Sessions are in memory, so a backend restart counts as session expiry (handled as above).

### Open / next tasks
- Decide on formula recalculation and editing of empty numeric cells.

---

## 2026-11-01: Session 9: PB-1 detail page per company

### Completed
- **Template source:** `2025 PB-1.xls` (old binary .xls, read with **xlrd**; added `xlrd>=2.0` to `requirements.txt`).
  - The PB-1 table is the sheet **"Poreski bilans"**, columns **A–F**, from the header row (`red.br.PB 1 | Opis | Priznati troskovi | Ostvareni troskovi | Prekoracenje | Komentar stopa konto`) to the last form row (Excel rows 5–88, "Mesecna akontacija"): 84 rows.
  - Not part of the PB-1 table: rows 1–3 (title, company name, class 5/6 totals), helper columns G–Q, and the sheets "Uporedo 2025 i 2024" and "Preliminarni rezultat".
  - Kept from Excel: header texts, row order, line numbers (including the duplicate "31"), column widths, bold cells (section rows), and number formats (`#,##0`, `#,##0.00`, `0.00%`, red negatives).
- **Template vs. values:** columns A (line no.), B (description) and F (rate / konto / comment) are the template shared by all companies. Columns C, D and E (amounts) are the company's values, empty by default.
- **Identity match:** the PB-1 file names its company "FRIGOLAKTA  DOO, BEOGRAD" (no PIB).
  - `normalize_company_name` removes the legal form and everything after it (city), plus punctuation, case and diacritics, giving "FRIGOLAKTA".
  - This must match exactly one GFI company (name + PIB). Here that is GFI Excel row 119, R.B. 118, `FRIGOLAKTA`, PIB `101202434`.
  - Values are shown only when both the normalized name and the PIB match. Table position is never used. "FILTER FRIGO" does not match. If the name matched several companies with different PIBs, no one would get the values (WARNING logged).
- **Backend:**
  - `app/pb1_workbook.py`: reader + mtime cache.
  - `app/pb1.py`: `GET /api/reporting-years/{year}/companies/{row}/pb1` → `{company:{row,name,pib}, workbook, sheet, has_values, columns:[{key,header,width}], rows:[{row, cells:{A..F:{value,format,bold}}}]}`. Returns 404 for rows without a company name or a year without `<year> PB-1.xls`.
- **Frontend:**
  - GFI table: each company name (NAZIV column, found by header) is a link to `/companies/:year/:row/pb1`. Editing is unchanged; name cells were never editable.
  - `Pb1Page`: Back button (to `/`), title = company name, subtitle "PB-1 · Poreski bilans · year · PIB", badge "Values from 2025 PB-1.xls" / "No PB-1 values yet".
  - `Pb1Table`: read-only, same data-table style (sticky header, hover highlight and enlarged preview, tabular numbers). Excel column widths; column B wraps.
  - Added shadcn `badge` (the `cn` import issue happened again and was fixed again).

### Test results
- Reader: 84 rows, original headers and widths; formats and bold flags read correctly.
- Name normalization: "FRIGOLAKTA  DOO, BEOGRAD", "FRIGOLAKTA" and "Frigolakta d.o.o." → "FRIGOLAKTA"; "FILTER FRIGO" stays distinct; "TIL TIM d.o.o. Beograd-Zemun" → "TIL TIM". Owner = ("FRIGOLAKTA", "101202434").
- API: 401 when logged out. Row 119 (Frigolakta): `has_values`, 70 amount values. Rows 137 (Filter Frigo) and 2 (1. Oktobar): same 84 rows, 0 amounts, template A/B/F present. 404 for row 296 (no company) and row 9999.
- Browser (5173):
  - 200 company links in the GFI table. Frigolakta opens its PB-1 page showing `-1.030.484` (red), line 25 `256.468,24 | 8.891,50 | 247.576,74 | 0,50%`, line 59 `-782.907,45`, and bold section rows.
  - Back returns to Home (2025). Filter Frigo shows the empty template with "No PB-1 values yet".
  - Dark mode OK; no page-level scroll.
  - GFI regression: editing still opens/cancels, formula cells read-only, name cells are links (not editable).
- Testing note: in this session the Chrome tool's clicks (coordinate and element-ref) did not reach the page. Navigation was exercised with DOM `click()` on the real `<a>` elements, which were confirmed to be the elements under those coordinates. Please confirm once with a real mouse.
- `2025 GFI TOKK 1.xlsx` unchanged (Git); `2025 PB-1.xls` mtime unchanged (2026-10-29 13:25). `tsc`, build pass; `npm audit` 0 vulnerabilities; no secrets in `app.log`.

### Notes
- `2025 PB-1.xls` is untracked in Git; it was left as is.
- Assumption to confirm: column F ("Komentar stopa konto": konto numbers, rates such as 0.05, comments) is treated as template, so it is shown for every company.
- PB-1 is read-only for now; editing PB-1 amounts would follow the GFI pattern (SQLite overrides).

### Open / next tasks
- Confirm the column-F assumption and whether the other two PB-1 sheets are needed.
- PB-1 editing (if required).
