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

---

## 2026-11-03: Session 10: Project move and rename to "Income Tax Reporting"

### Completed
- The project moved from `D:\Desktop\tim-automation` to `D:\Desktop\income-tax-reporting`. This is now the only project directory.
- Renamed the application from `tim-automation` to **Income Tax Reporting**:
  - Backend: FastAPI title in `app/main.py` (shown in `/docs` and `/openapi.json`).
  - Frontend: sidebar logo text (`AppSidebar.tsx`), Login page logo text (`LoginPage.tsx`), browser tab title (`index.html`).
  - `frontend/package.json` and `package-lock.json`: package name `income-tax-reporting-frontend` (npm names must be lowercase).
- README rewritten: new name, feature overview (login, year selector, GFI table, editing with autosave, PB-1 page), data files, check commands. The outdated "Application is running" text was removed.
- CLAUDE.md: records the application name and states that the separate Selenium automation tool is not part of this application and must not be modified.

### Test results
- `tsc` and `npm run build` pass.
- The user's running dev servers (started from the new folder, auto-reload) picked up the changes; the backend reloaded without errors.
- API: health 200 (direct and through the 5173 proxy); `/api/auth/me` and `/api/reporting-years` 401 when logged out; OpenAPI title "Income Tax Reporting".
- Browser (5173): the Login page and the tab title show "Income Tax Reporting". The sidebar was checked in the served source only, because it needs a login.
- `backend/.venv` was created at the old path but works from the new folder (`python -m uvicorn` and imports OK).

### Changes
- No functional changes. Folder names and the Selenium tool (`tim_automation/`, `web/`, root `main.py`, root `requirements.txt`) were not touched.

### Open / next tasks
- Check the sidebar name once after logging in.
- If `.venv\Scripts\*.exe` wrappers are ever needed, recreate the venv; they still point to the old path. The documented `python -m` commands are not affected.
- Earlier open tasks (formula recalculation, editing empty cells, PB-1 column F, PB-1 editing, mobile layout check) are unchanged.

---

## 2026-11-03: Session 11: Compact Home table layout

Display-only changes. API, edits, autosave, company identification, SQLite and Excel files are unchanged.

### Completed
- **Sidebar collapsed by default** (`AuthenticatedLayout`: `SidebarProvider defaultOpen={false}`). The header toggle expands it. Every page load starts collapsed (the shadcn cookie is written but not read on the client).
- **GFI table (`CompanyTable.tsx`)**, with columns found by their Excel header (never by position):
  - The `#` column shows the exact value of the first **R.B.** column (A) instead of the Excel row number. The Excel row number is in the cell tooltip ("Excel row N"). Rows without an R.B. value show an empty `#`.
  - Hidden: both **R.B.** columns (A and B), **kom** (G), and **PIB** (D).
  - **PIB** is shown below the company name as `(PIB)` in muted small text, read-only. Only real 9-digit PIBs are shown (decided with the user). Other values in column D (1/0 flags in the lower sections, totals, 13-digit JMBGs, "UKUPNO") are not shown on Home. PIB is hidden only if the NAZIV column exists.
  - Name column header renamed to **"Naziv (PIB)"**. Company names are still links to their PB-1 pages; the hover preview shows the name and PIB.
  - Compact spacing: cells `px-1.5 py-1`, headers `px-1.5 py-1.5`, `#` column `w-10`. Headers keep their exact Excel text but may wrap (`whitespace-pre-wrap`, bottom-aligned).
- Decisions with the user: `#` = column A and both R.B. columns hidden. As a result, the 34 names that exist only in column B (lower sections of the sheet) are not visible on Home.

### Test results
- `tsc` and `npm run build` pass.
- Browser (5173, 1536 px wide): sidebar collapsed on load; 11 visible columns; no horizontal scroll with the sidebar collapsed or expanded (1231 px table width); 319 rows; 200 PB-1 links; `#` = R.B. (e.g. Excel row 2 → 1, row 107 → 106, row 429 → 35); PIB below names.
- Editing: a number cell opens the editor and Escape cancels. A save test was not run (writing test data was blocked); the edit and autosave code paths were not changed. `edits.db` still has 0 edits.
- PB-1 link opens the company's PB-1 page; the sidebar toggle expands the sidebar, which shows "Income Tax Reporting". No console errors.

### Changes
- Column D (PIB) and the hidden columns can no longer be edited from the Home table. The backend still accepts edits to them (`PUT /cells/...`), and existing data is unchanged.
- Not part of this session: `tim_automation/`, `web/`, root `main.py`, root `requirements.txt` and the folder shortcut were deleted from the working tree outside this session (not committed yet). `README.md` and `CLAUDE.md` still mention these files.

### Open / next tasks
- Confirm one real edit and save in the browser (H, I, K or L column).
- ~~Update `README.md` and `CLAUDE.md` after the removal of the Selenium tool files.~~ Done: the notes about the Selenium tool were removed from both files.
- PostgreSQL migration design is waiting for approval (decisions listed in the session conversation).

---

## 2026-11-03: Session 12: Home table: company list only, zeros, alignment, column borders

Display-only changes in `CompanyTable.tsx` and `HomePage.tsx`. API, stored values, edits, autosave, PB-1 navigation and the Excel files are unchanged.

### Completed
- **Row limit:** `mainListRows()` shows the rows from the top while R.B. (column A) continues the sequence 1, 2, 3, ... For 2025 that is R.B. 1–165, ending with **DAGOTTA d.o.o.** (Excel row 166). Totals, statistics and the other lists below are hidden. This rule was used instead of searching for the name, because DAGOTTA also appears again in row 195. If a workbook has no such sequence, all rows are shown. The subtitle now reads "165 companies · workbook".
- **Zeros:** from the **Preliminarni** column to the last column (H–N), empty or blank (`' '`) cells are displayed as `0` with the column's number format. The stored value stays empty. These cells stay read-only (tooltip "Empty in Excel (read-only)"), as the backend only allows editing cells that hold a number. Edited cells and the editor still use the real value.
- **Alignment:** numeric columns (Preliminarni onward) are right-aligned, including their headers, with tabular figures. Other numbers were already right-aligned.
- **Column borders:** a vertical line between all columns (`not-last:` inset shadow in the border colour, matching the sticky `#` column). It stays visible on the sticky header and works in light and dark mode.

### Test results
- `tsc` and `npm run build` pass.
- Browser (5173): 165 rows, first R.B. 1 (1. OKTOBAR), last R.B. 165 (DAGOTTA d.o.o., Excel row 166); 165 PB-1 links; 232 empty cells shown as `0` (matches the data: H 8, I 8, J 9, K 14, L 14, M 14, N 165); no empty cells left in H–N; numeric cells and headers right-aligned; borders on every column except the last; no horizontal scroll; dark mode OK; no console errors.
- Editing: a number cell opens the editor and Escape cancels; a zero-filled empty cell does not open an editor. `edits.db` still has 0 edits; the Excel files are unchanged.

### Open / next tasks
- Confirm one real edit and save in the browser (not tested by the assistant; writing test data was blocked).
- The hidden rows (below DAGOTTA) are still returned by the API and can still be edited through it.

---

## 2026-11-03: Session 13: Home table: hide column N, "-" for empty referent cells

Display-only changes in `CompanyTable.tsx`. API, stored values, edits, autosave, PB-1 navigation, SQLite and the Excel files are unchanged.

### Completed
- **Column N hidden:** the unnamed column right after "PB-1,PB-2 za rad" is no longer shown (with its zero-filled values). It is found by position relative to that header, not by letter. The table now has 10 columns, ending with "PB-1,PB-2 za rad".
- **"-" for empty cells** in the two referent columns: **REFERENT** (E) and the unnamed column right after it (F: SLAVIJA, FER, LJILJA, ADMIN, ...). The user referred to them as "Referent naziv". Empty or blank cells show a muted `-` with the tooltip "Empty in Excel (read-only)"; there is no hover preview for it. Cells that already contain `-` in Excel are shown as before, in normal text colour.

### Test results
- `tsc` and `npm run build` pass.
- Browser (5173, DOM checks): 165 rows, 10 columns; the last column is "PB-1,PB-2 za rad"; no empty cells left in E/F (4 placeholders in E, 7 in F, plus 4 real `-` values from Excel in F); 165 PB-1 links; no horizontal scroll; no console errors.
- Screenshots of the tab timed out in this session (the Chrome tool could not capture the page), so the result was checked through the DOM only. Please take a quick look in the browser.
- `edits.db` still has 0 edits; the Excel files are unchanged.

### Open / next tasks
- Visual check of this session's changes in the browser (screenshots were not available).
- Confirm one real edit and save in the browser.

---

## 2026-11-03: Session 14: PostgreSQL for GFI data (prepared, not yet active)

PostgreSQL is **not installed yet**: the user will install it when it is needed. The code is ready. The app keeps running on Excel + SQLite until `DATABASE_URL` is set in `backend/.env`. PB-1 data, users and sessions are unchanged. No Excel file or SQLite data was written.

### Decisions (with the user)
- Schema: the GFI part of the normalized design proposed earlier (it had not been built before; there were no earlier imports).
- Keep only the company list: rows while R.B. continues 1, 2, 3, … (2025: R.B. 1–165, Excel rows 2–166, ending with DAGOTTA d.o.o.). Same rule as the Home page.
- Company identity "as-is": each row is its own company; PIB stored exactly, not unique, not required. Problems are recorded as import issues, never merged.
- Values are stored exactly as shown, including the 18 hand-typed "GFI ZA RAD" values (17 differ from kom − GFI uradjen).

### Completed
- **Libraries** (`requirements.txt`): SQLAlchemy 2.1.6, Alembic 1.20.1, psycopg[binary] 3.3.6 (3.3.7 was only hours old), python-dotenv (already installed via uvicorn). Target: PostgreSQL 18.
- **Settings:** `app/settings.py` loads `backend/.env` (git-ignored) at startup; `backend/.env.example` documents `DATABASE_URL`, `LOG_LEVEL`, `GFI_DATA_DIR`, `DATABASE_PATH`.
- **Schema** (`app/models.py`, Alembic migration `migrations/versions/20261103_0001_gfi_schema.py`):
  - `reporting_year`
  - `source_file` (one per kind and year, with SHA-256 and file time), `gfi_column` (A–N headers and the field each maps to), `source_cell` (read-only snapshot of every original cell: value, number format, formula flag)
  - `company` (name, PIB as text), `company_year` (one company in one year: R.B., name, referent, office and the numeric status fields kom, preliminarni, gfi_uradjen, gfi_za_rad, pb, pb_predat, pb_za_rad; addressed by Excel row `source_row`)
  - `referent`, `office` (exact text lookups), `import_issue`, `change_log` (every edit with old/new value, user, time; kept when an import is replaced)
  - Columns are mapped by header text, not by letter. The PostgreSQL DDL was rendered offline (BIGSERIAL ids, NUMERIC values, CHECK and cascade rules); `alembic check` reports the migration matches the models.
- **Data source switch** (`app/gfi_store.py`): `PostgresGfiStore` when `DATABASE_URL` is set, otherwise `ExcelGfiStore` (the previous behaviour). Both return the same tables, so the API and frontend are unchanged. `companies.py`, `reporting_years.py` (year list) and `pb1.py` (company name/PIB lookup) use it. The startup log says which source is used.
- **Import** (`python -m app.gfi_import <year> [--dry-run] [--replace]`), one transaction:
  - Reads the workbook (read-only) and keeps the company list.
  - First import of a year: carries over every SQLite edit (with `change_log` entries). If any edit is outside the 165 rows or not in an editable GFI column, it stops.
  - `--replace` removes an earlier import only if none of its values were changed in the database; unused companies, referents and offices are removed; the history is kept. SQLite edits are not applied again on a replace.
  - Verifies every cell (value, format, formula, editable, edited, original) against the Excel + SQLite table; any unexpected difference rolls back.
- **Database mode differences** (intended): R.B. and PIB are read-only (only the numeric status columns can be edited); numeric PIBs are returned as text (26 cells); only the 165 company rows are returned.

### Test results
- Dry run against the real files (scratch SQLite database standing in for PostgreSQL): 165 companies, 13 referents, 8 offices, 2,310 cells; verification passed; 10 import issues: 3 without PIB (rows 148, 150, 156), 2 shared PIBs (114113887: rows 5 and 58; 105750945: rows 73 and 120), 2 JMBGs (rows 14, 45), text `' '` in J71.
- End-to-end test, 23 checks, all passed (scratch SQLite database and a scratch copy of the edits database, real files read-only): migration; import with two SQLite edits carried over (a change and a cleared value); API in database mode equals Excel mode cell by cell; edit and revert through the API with `change_log`; PIB and formula edits rejected (409); PB-1 lookup (Frigolakta has values, 1. Oktobar empty); `--replace` refused while values are changed; replace after revert keeps history and leaves no orphans; old SQLite edits are not re-applied on replace; an edit outside the 165 rows stops the import.
- The running backend reloaded in Excel mode without errors. Excel files unchanged; `edits.db` unchanged (still 0 edits).
- Not tested: a real PostgreSQL server (not installed). The browser check was not possible: the backend reloads logged the browser session out.

### Notes
- The test runs wrote their log lines (including expected "Import stopped" errors) to `backend/logs/app.log`, from 16:43 to 16:47.
- Formula columns (GFI ZA RAD in formula rows, PB-1,PB-2 za rad) are stored as values and are still not recalculated after an edit, as before.

### Open / next tasks
- When PostgreSQL is installed: follow README "Database (PostgreSQL)", run `alembic upgrade head`, `app.gfi_import 2025 --dry-run`, then the import, restart the backend, and check Home, editing and PB-1 in the browser.
- Correct the 7 company identity issues (no tooling for this yet).
- Later: PB-1 in the database (once its layout is final), users and sessions in the database.

---

## 2026-11-06: Session 15: Company Registry page (editable company details)

### Completed
- **New page "Company Registry"** (`/company-registry`, sidebar group "Companies", lucide `Building2`): all 165 companies with every GFI column (A–N, original headers, no hidden columns or display substitutions). `#` = R.B. as on Home.
- **Editable in the Registry:** every numeric field that is editable on Home, plus the company details **NAZIV, PIB, REFERENT and the unnamed office column after it** (decided with the user: "Naziv, PIB and 2 columns for REFERENT"). They are edited as text: NAZIV can't be empty, PIB is digits only, empty clears REFERENT/office. Same validation in the browser and on the backend (422).
- **Home unchanged:** same columns, display rules and editing (company details stay read-only there; checked: no text cell is editable on Home).
- **One data source for both pages:** the same API, edits and a single app-wide autosave queue (`CellAutosaveProvider` in `AuthenticatedLayout`). Each page loads fresh data when opened, so changes on one page show on the other. Before, each page had its own queue instance, and moving between pages during a save could overwrite the browser copy of the queue.
- **Backend (both storage modes):**
  - `edit_kind()` in `app/gfi_store.py` decides per cell: "number" (numeric status columns, plain numbers), "text" (company details) or read-only. The API sends `editable` plus `text: true` for company details. `PUT /cells/...` accepts a number or text accordingly.
  - Company identity is unchanged by edits (Excel row; in the database, the same `company`/`company_year` rows are updated in place).
  - **PB-1 link preserved:** PB-1 is matched on the original (Excel/imported) name and PIB; the PB-1 page shows the current (edited) name and PIB.
  - SQLite (`edits.db`): new columns `value_text`, `original_text`, added in place at startup. A backup (`edits.db.bak-<timestamp>`) is made first; existing edits are kept.
  - PostgreSQL: migration `0002` adds `old_text`/`new_text` to `change_log`; text edits update `company_year.name` / `company.name`, `company.pib`, or the referent/office lookup (created if new). The import carries over text edits from SQLite too.
- Frontend: `CompanyTable` has a `variant` ("home" | "registry"); text cell editor with validation; shared page body `GfiTableView` and hook `useGfiEditor`; `HomePage` uses them.

### Changes
- R.B. and numeric PIB cells are no longer editable as numbers in Excel mode (they were accepted by the API but not shown on Home). PIB is now edited as text in both modes.
- The database mode now returns the original values exactly as Excel mode does (e.g. numeric PIBs are no longer turned into text), so both modes produce identical API responses.

### Test results
- Backend, scratch data only (real `edits.db` and Excel read-only):
  - Registry suite, 35 checks, all passed: SQLite schema upgrade with backup keeps existing edits; text/number validation (422) and R.B. read-only (409); rename, PIB change, referent change, office cleared, numeric edit; revert to the original (spaces ignored, numeric PIB); PB-1 link kept after renaming and changing the PIB (Excel and database mode) and not given to another company; import carries text + numeric edits; database API equals Excel API for all 165 rows; database text edits with `change_log`; company id unchanged after a rename; `--replace` refused while edits exist.
  - Earlier database suite updated to the new rules (PIB text-editable): 23 checks, all passed. Migration 0002 generated and checked with `alembic check`; PostgreSQL SQL rendered offline.
- Frontend: `tsc` and `npm run build` pass. Browser (against the running backend, which still had the old code): Registry shows 165 rows, 14 columns + `#`, no horizontal scroll; Home unchanged (10 columns, 165 links, 160 PIB lines, 4 + 7 "-" placeholders, 67 zeros, no editable text cells); no console errors. Screenshots timed out again; checks were done through the DOM.
- **Not yet tested in the browser:** text editing on the Registry page. The running backend's auto-reload stopped picking up file changes (the reloader process has been running since 2026-11-03), so it still runs the old code until it is restarted. The real `edits.db` will get its new columns (with a backup) at that restart.

### Open / next tasks
- Restart the backend ("Start all" or the backend task), log in, and check Registry editing: rename a company, change a PIB / referent, check Home and the PB-1 page.
- Until the backend is restarted, don't edit company details: the old backend shows them read-only anyway.
- Correct the 7 company identity issues, now possible in the Registry (PIB, name).

### Addendum (2026-11-07)
- The user restarted the backend (00:01). The real `edits.db` got the new text columns; the backup `backend/data/edits.db.bak-20261107-000148` was made first. Still 0 edits.
- Clarified with the user: Home's "Naziv (PIB)" column is a display notation for two data fields, NAZIV (column C) and PIB (column D, shown below the name in parentheses). The Registry keeps them as separate columns NAZIV and PIB (as built); editing PIB in the Registry changes the value in parentheses on Home. A short-lived change that merged them into one cell in the Registry was reverted.
- Browser (new backend): Registry shows NAZIV, PIB, REFERENT and office as editable on all 165 rows; the name and PIB editors open with the current value and Escape cancels (nothing saved). Home unchanged (10 columns, 165 links, 160 PIB lines, no editable text cells). No console errors. `tsc` and build pass.
- Still to do by the user: one real edit of a name and a PIB in the Registry, then check Home and the PB-1 page (saving test data from the assistant's browser session is blocked).

---

## 2026-11-07: Session 16: R.B. columns removed everywhere; "#" is the list position

Decided with the user: the R.B. columns (both) are not kept anywhere. Only "#" matters. R.B. was only how the company list was first defined, and it is still used for that alone when reading the Excel workbook.

### Completed
- **Company Registry:** both R.B. columns removed from the table (done first, on request).
- **Backend:** `company_list()` in `app/gfi_workbook.py` returns the company list as the app uses it: only the list rows (165 for 2025) and no R.B. columns. Used by the Excel + SQLite store and by the import. The API therefore returns 165 rows without R.B. in both modes (before, Excel mode returned all 319 rows and the frontend cut the list).
- **Database:** `company_year.rb` removed from the model; migration `0003` drops the column (downgrade adds it back, nullable). The import no longer stores the R.B. columns in the snapshot (`gfi_column`, `source_cell`).
- **Frontend:** `#` is the position in the list (1, 2, 3, …), with the Excel row in its tooltip; `mainListRows()` and all R.B. handling removed. Home looks the same (the numbers are identical).
- CLAUDE.md and README updated.

### Test results
- Migration 0003: generated with Alembic autogenerate, `alembic check` clean, upgrade/downgrade/upgrade on a scratch database, PostgreSQL SQL rendered offline (`ALTER TABLE company_year DROP COLUMN rb`).
- Backend suites on scratch data (real data only read): Registry suite 38 checks (new: no A/B columns returned, Excel mode returns exactly 165 rows ending at Excel row 166, R.B. edits get 404, no `rb` column and no R.B. cells in the database), earlier database suite 23 checks, all passed.
- `tsc` passes. The backend auto-reloaded (00:23), which logged the browser out, so the browser check is still to do by the user.

### Notes
- Edits saved earlier on R.B. cells would block the import (the import never drops edits); `edits.db` has none.

### Open / next tasks
- Log in and check Home and Company Registry (`#` 1–165, no R.B. columns in the Registry).
- From Session 15: one real edit of a name and a PIB in the Registry, then check Home and PB-1.

---

## 2026-11-07: Session 17: Company Registry layout (fits the screen, quiet read-only cells)

Frontend only (`CompanyTable.tsx`, registry variant). Home, data, API and editing rules unchanged.

### Completed (user's requests for the Registry)
- **Fits the screen width, never a horizontal scrollbar:** fixed table layout (`table-fixed`) with column widths in percent: `#` 3%, NAZIV 22%, PIB 9%, REFERENT 11%, office 8%, the numeric columns share the rest. Long values are truncated; headers wrap. Editors fit inside their cell (no minimum width in the Registry). The scroll container only scrolls vertically.
- **The table ends with "PB-1,PB-2 za rad":** the unnamed column after it (N) is no longer shown (same rule as Home, now shared in `withoutColumnAfterLast`).
- **`#` stays read-only** (unchanged).
- **Read-only cells don't react to the mouse:** no highlight, no enlarged preview and no tooltip (no "Excel row", "Column X", "Formula (read-only)" or "Empty in Excel" texts), including `#` and the column headers. Editable cells keep their highlight, preview and edit tooltips.
- CLAUDE.md: Registry layout rules added.

### Test results
- `tsc` and `npm run build` pass.
- Browser (1536 px window, sidebar collapsed): Registry table 1408 px wide with scroll width = client width (no horizontal scroll); 12 columns ending with "PB-1,PB-2 za rad"; 165 rows; 522 read-only cells with no hover class, no tooltip and no preview; no header tooltips; 1458 editable cells. Home unchanged (10 columns, `#` 1–165, 165 PB-1 links, 160 PIB lines, no horizontal scroll). No console errors.
- Not checked: narrower windows (fixed layout keeps the table within the width; columns get narrower).

---

## 2026-11-07: Session 18: Registry shows everything and fills empty cells

### Completed (user's requests for the Registry)
- **No truncation ("…") anywhere in the Registry:** cells wrap (`whitespace-normal`, `break-words`) and rows grow, so every value is fully visible. The table still fits the screen width.
- **Empty cells get display values** (same two rules as Home):
  - from **kom** (included) to the right: `0`;
  - left of kom (NAZIV, PIB, REFERENT, office): `-` (muted).
  These are display only; nothing is stored.
- **They stay editable:** text cells were already editable when empty. Empty cells in the numeric columns could not be edited before; now they can be filled in on the Registry. Opening one shows an empty editor (with `0` / `-` as a hint), so just clicking and leaving never stores a value. The new value is saved immediately through the autosave queue.
- **Backend** (`edit_kind`, `is_original`, `load_table` in `app/gfi_store.py`, both storage modes): empty or blank-text (e.g. `' '` in J71) non-formula cells in the numeric GFI columns are editable as numbers; formulas stay read-only. Clearing a filled cell back to empty counts as "not edited" (the edit is removed). In the database, a filled empty cell is shown as an edit of the original empty value. The import carries such SQLite edits over.
- **Home unchanged:** it still edits only cells that hold a number in Excel (frontend rule: original value is a number); its empty cells stay read-only with "Empty in Excel (read-only)".
- CLAUDE.md editing and Registry rules updated.

### Test results
- Backend suites on scratch data: Registry suite 47 checks (new: empty numeric cells editable, fill and clear back = not edited, blank-text J71 editable, formula still 409, filled cells carried over by the import and editable in database mode), earlier database suite 23 checks: all passed.
- `tsc` and `npm run build` pass.
- Browser check not done: the backend auto-reloaded on the change and logged the browser out.

### Open / next tasks
- Log in and check the Registry: no "…", `0` / `-` in empty cells (most visible in the last rows), filling an empty cell saves it; Home's empty cells still read-only.

---

## 2026-11-07: Session 19: Formula columns computed in every row

Decided with the user: GFI ZA RAD and PB-1,PB-2 za rad stay read-only and depend only on their formulas, consistently for the whole table, on both Home and the Company Registry, regardless of empty (shown as 0) or hand-typed values.

### Completed
- **Formulas** (`FORMULA_FIELDS` in `app/models.py`, `apply_formulas` in `app/companies.py`), for all 165 rows, in both storage modes:
  - GFI ZA RAD = kom − GFI uradjen
  - PB-1,PB-2 za rad = PB-1, PB-2 − PB-1, PB-2 Predat
  - An empty (or non-numeric) input counts as 0. Computed from the current values (edits included), marked as formula, never editable (PUT returns 409).
- **Live update:** `PUT /cells/...` returns `formulas` (the row's recomputed formula columns); the page applies them right after the save, so editing kom, GFI uradjen, PB-1, PB-2 or Predat updates the result at once on the same page, and on the other page when it is opened.
- **Database:** `company_year.gfi_za_rad` and `pb_za_rad` removed (migration `0004`); the original Excel values stay in the import snapshot (`source_cell`). `NUMERIC_FIELDS` now holds only the user-entered fields.
- CLAUDE.md editing rules updated.

### Effect on the displayed values (real data, read-only check)
- GFI ZA RAD shows a different number in 18 rows: the 17 hand-typed values that differed from kom − GFI uradjen (16 × 0 → 1, #157 1 → 0) and #153 MERKOL (empty → 1). The other changes are empty cells that were already shown as 0.
- PB-1,PB-2 za rad: no visible change (the 14 empty cells were already shown as 0; all other rows were formulas).
- Edits stored earlier on the hand-typed GFI ZA RAD cells would no longer be applied (and would block a PostgreSQL import); `edits.db` has none.

### Test results
- Migration 0004: autogenerated, `alembic check` clean, upgrade/downgrade/upgrade on a scratch database.
- Backend suites on scratch data: Registry suite 54 checks (new: J = G − I and M = K − L in all rows and read-only, both modes; J/M edits 409; edits of K and G return the recomputed M / J; formulas follow carried-over edits after the import; no za_rad columns stored), earlier database suite 23 checks: all passed.
- `tsc` and `npm run build` pass. Browser check still to do (the backend reload logs the browser out).

### Open / next tasks
- Log in and check: GFI ZA RAD / PB-1,PB-2 za rad on Home and Registry; change kom or PB-1, PB-2 in the Registry and watch the formula column update.

### Addendum: formula cells don't react to the mouse (2026-11-07)
- On Home, hovering GFI ZA RAD or PB-1,PB-2 za rad showed the highlight and the enlarged preview, which looked like an edit box that can't be typed into. Formula cells now have no hover highlight, no preview and no tooltip on every page (`still` in `DataCell`; the Registry already behaved this way for read-only cells).
- Browser check (Home, logged in): both formula columns, 165 cells each: 0 with hover, preview, tooltip or edit; GFI uradjen unchanged (hover, preview, 157 editable). Formula values visible as expected (#153 MERKOL 1, #157 0, #13 1). No console errors. `tsc` and build pass.

### Addendum: hover preview over right-aligned numbers (2026-11-07)
- The enlarged hover preview of a cell opened from the cell's left edge, except in the last three columns. In right-aligned numeric columns (e.g. Preliminarni, GFI uradjen) it therefore appeared away from the value. Numeric cells now open the preview from the right edge, over the value, on both pages; text cells still open from the left.
- Browser check (Home): Preliminarni, GFI uradjen and PB-1, PB-2 previews 165/165 right-anchored; Naziv (PIB) and REFERENT left-anchored; hovering a Preliminarni cell shows the box over the value. No console errors. `tsc` and build pass.

---

## 2026-11-07: Session 20: PB-1 linked by company identity; data sweep

### Completed
- **PB-1 is linked to a company's identity, not found by its name/PIB** (which the Company Registry can change):
  - The link "PB-1 file → company" is stored: SQLite table `pb1_links` in `edits.db` (year, PB-1 file, company name as written in the PB-1 file, GFI workbook, GFI row), PostgreSQL table `pb1_link` → `company_year` (migration `0005`, FK with ON DELETE CASCADE, so it can only point at one of the imported 165 companies).
  - `pb1_owner_row()` in `app/pb1.py`: uses the stored link. The link is made once from the company name in the PB-1 file (the file has no PIB), compared with the **original** GFI names; exactly one company of the list must match. It is made again only if the PB-1 file names a different company, the linked row is not in the company list, or the GFI workbook file was replaced. Otherwise renaming a company or changing its PIB never affects PB-1.
  - The PostgreSQL import carries SQLite PB-1 links over by company identity (links to rows outside the list are not carried).
  - Removed the old per-request name/PIB identity matching (`_owner_identity`).
- **Data sweep (real data, read-only check):**
  - No PB-1 data is stored anywhere (amounts are read from `2025 PB-1.xls` on request), so there was nothing stored for companies outside the 165 to delete. With the stored link, PB-1 can only belong to one of the 165 companies.
  - `edits.db`: 0 cell edits, `pb1_links` empty (the 2025 link is written on the first PB-1 page view).
  - Superfluous: `backend/data/edits.db.bak-20261107-000148` (backup made before the text columns were added; held 0 edits). Deleted with the user's approval.
- CLAUDE.md PB-1 rules updated.

### Test results
- Migration 0005: autogenerated, `alembic check` clean, upgrade/downgrade/upgrade on a scratch database.
- Backend suites on scratch data: Registry suite 61 checks (new: link stored on first view; PB-1 follows the stored link even when it points elsewhere, i.e. not the name; a link outside the 165 is replaced by the right company; a PB-1 file naming another company is linked again; the import carries the link to `pb1_link` by identity; PB-1 still shown after renaming in the database; no other company gets the values), earlier database suite 23 checks: all passed.

### Open / next tasks
- Next: finalize the PB-1 pages; only then store PB-1 data in the database (user's plan: layout first, then a clean migration).

---

## 2026-11-07: Session 21: Home Actions column and the three PB-1 tabs

Reminder from the user: every company has one PB-1 form with three tabs (the three sheets of the PB-1 workbook); only FRIGOLAKTA has real values, every other company has the empty frame. Nothing else was to change.

### Completed
- **Home:** new last column **Actions** with three small buttons in three colors, one per PB-1 tab:
  - **PB** (orange, `chart-1`): Poreski bilans, i.e. what clicking the company name opened before;
  - **Uporedo** (teal, `chart-2`): "Uporedo 2025 i 2024";
  - **Prelim.** (dark blue, `chart-3`): "Preliminarni rezultat".
  The full tab name is in each button's tooltip. Company names are no longer links. The table still fits without horizontal scroll.
- **Theme:** shadcn chart tokens `--chart-1..3` added to `src/index.css` for light and dark (`--color-chart-*` in `@theme`), so the colors come from the theme. CLAUDE.md lists them.
- **PB-1 page with three tabs** (shadcn `tabs`, added with the CLI; the `cn` import problem happened again and was fixed, the stray `cn` package uninstalled). The tab is part of the URL: `/companies/:year/:row/pb1/:tab` (`poreski-bilans` default, `uporedo`, `preliminarni`).
- **Backend:** `app/pb1_workbook.py` reads the three sheets (`PB1_TABS`: columns, amount columns, header row or first row, wrapping columns). `GET .../pb1/{tab}` (and `.../pb1` = Poreski bilans) returns the tab plus the list of tabs; columns carry `wrap`. The owner (stored PB-1 link) is the same for all three tabs; other companies get the template without amounts.
  - Poreski bilans unchanged (84 rows, 70 amounts for FRIGOLAKTA).
  - Uporedo: rows 6–25, header R.b. | Opis | 2025 | 2024 | Index.
  - Preliminarni rezultat: rows 2–42, columns A–G (two tables side by side and the sections below), no header row; helper columns H–J are left out.
- `Pb1Table`: column widths through `<colgroup>` (also without a header row); the header row is only rendered when the sheet has one; wrapping columns come from the API (B, and F in Preliminarni rezultat).

### Notes
- The "Uporedo" sheet of `2025 PB-1.xls` names "TIL TIM d.o.o. Beograd-Zemun" at the top although its numbers are FRIGOLAKTA's: a leftover in the Excel template. That name is not used; the owner comes from the stored link.
- Excel errors in the sheets (e.g. `#DIV/0!` in the Index column) are shown as in Excel.

### Test results
- Backend suites on scratch data: Registry suite 64 checks (new: for each of the three tabs only FRIGOLAKTA has amounts and every other company has the same frame; tab list), earlier database suite 23 checks: all passed. Unknown tab → 404.
- `tsc`, `npm run build` pass; `npm audit --omit=dev`: 0 vulnerabilities.
- Browser: Home has 11 columns ending with Actions; 165 rows with three buttons; no name links; no horizontal scroll. FRIGOLAKTA: PB → Poreski bilans (84 rows), Uporedo → Uporedo tab with values (20 rows, header R.b. | Opis | 2025 | 2024 | Index), switching to "Preliminarni rezultat" with a real click works (33 rows, no header row). 1. OKTOBAR Prelim. → same frame, no amounts, "No PB-1 values yet". No console errors.

### Open / next tasks
- Finalize the PB-1 pages (layout of the three tabs), then migrate PB-1 to the database.

---

## 2026-11-10: Session 22: Statistics under the Home table

Requested by the user: statistics under the whole Home table, based on Preliminarni, GFI uradjen and GFI ZA RAD. Chosen with the user: totals plus each total's share of the kom total.

### Completed
- **Backend** (`app/companies.py`): `stats` in `GET /companies` and in the `PUT /cells/...` result (`TableStats`: kom column and total, then per column `key`, `header`, `total`, `share` = total / kom total, omitted when the kom total is 0).
  - Fields are found by header (`STATS_FIELDS` = preliminarni, gfi_uradjen, gfi_za_rad; `STATS_BASE_FIELD` = kom). They sum all companies of the list using the current values (edits included) and the computed formula column GFI ZA RAD. An empty or non-numeric cell counts as 0 (same as the formulas). `stats` is omitted when the workbook layout is unknown.
- **Frontend:** `GfiStats` (three shadcn `Card`s, `sm:grid-cols-3`) under the table, **Home only**. Shows the total (`#,##0.##`) and "8,5% of kom (153)" (`0.0%`, Serbian separators). After each save the totals from the server replace the old ones (`setStats` in `useCompanyTable`, `useGfiEditor.onSaved`).

### Values (2025, real data, no edits)
- Preliminarni 13 (8,5%), GFI uradjen 131 (85,6%), GFI ZA RAD 22 (14,4%), kom 153.
- Excel's SUM row (row 173) shows the same 13 and 131. For GFI ZA RAD it shows 6, because Excel uses the hand-typed values, and the app computes kom − GFI uradjen in every row (Session 19).

### Test results
- Endpoint functions on a scratch copy of `edits.db` (the real one was not written; still 0 edits): GFI uradjen 1 → 0 in one row gives 130 / 23 (GFI ZA RAD follows); Preliminarni +5 gives 18; reverting restores 13 / 131 / 22; a text edit (NAZIV) leaves the totals unchanged; the scratch DB is back to 0 edits.
- `tsc` and `npm run build` pass; formatter checks: `8,5%`, `85,6%`, `1.234,5`.
- Browser (Home, logged in): 165 rows; three cards "Preliminarni 13 · 8,5% of kom (153)", "GFI uradjen 131 · 85,6% …", "GFI ZA RAD 22 · 14,4% …" under the table; no horizontal scroll.

### Notes
- Totals change when the server confirms a save (immediately while online). A change still waiting in the autosave queue (e.g. offline) is visible in the table, but not in the totals until it is saved.

### Open / next tasks
- Commit sessions 10–22 (nothing since `cf34664` is committed).
- Finalize the PB-1 pages, then migrate PB-1 to the database.

---

## 2026-11-10: Session 23: PB-1 tabs: zeros, right alignment, column borders, two decimals

Requested by the user for all three PB-1 tabs (reviewed on FRIGOLAKTA, applied to every company's form).

### Completed
- **Amount fields** (`Pb1Cell.amount` in `app/pb1_workbook.py`, sent as `amount` per cell): an amount-column cell that holds a number, an Excel error (`#DIV/0!`) or only spaces in the PB-1 file. Empty cells outside the form (e.g. columns C and E of lines 4–21 in Poreski bilans, where the form has only D) and template text ("RSD" in Preliminarni rezultat) are not amount fields. Same for every company: Poreski bilans 70, Uporedo 54, Preliminarni rezultat 49.
- **Zeros:** an amount field without a number shows `0,00` (`0,00%` in the Index column). For FRIGOLAKTA that covers the empty/blank fields and the `#DIV/0!` cells; every other company sees `0,00` in all amount fields.
- **Two decimals:** every amount is shown with exactly two decimals (`withDecimals` in `src/lib/excel-format.ts` rewrites the cell's Excel format; red negatives, minus/parentheses and `%` are kept; General → `#,##0.00`). E.g. `-1.030.484,19`, `8.891,50`, `33,34%`. Template numbers (line numbers in A/E, konto and rates in F) are unchanged.
- **Right alignment:** amount columns (`amount` per column: C–E, C–E, C and G) are right-aligned, headers included; hover previews open over the value.
- **Column borders:** a vertical line between all columns (same inset-shadow border as Home), also in the sticky header.
- **Fix:** template text in amount columns was hidden for companies other than the owner ("RSD" in Preliminarni rezultat C4). Now only amount fields are emptied.

### Test results
- Endpoint function on a scratch copy of `edits.db`: for each tab, FRIGOLAKTA and 1. OKTOBAR have the same amount fields; all non-amount cells are identical; 1. OKTOBAR gets no amounts; "RSD" stays for both.
- Formatter: all formats used in the file give two decimals with their negative styling.
- `tsc`, `npm run build` pass.
- Browser (before the backend reload): FRIGOLAKTA Poreski bilans `-1.030.484,19` (red), `1.778.299,20`, line 25 `256.468,24 | 8.891,50 | 247.576,74 | 0,50%`, empty fields `0,00`, borders between columns, amounts right-aligned; 1. OKTOBAR shows `0,00` in all amount fields; no horizontal scroll in the three tabs. The "RSD" fix was checked through the API only (the backend reload logged the browser out).

### Open / next tasks
- User: log in and review the three tabs on FRIGOLAKTA.
- Commit sessions 10–23.

### Addendum: amount fields checked against the form's logic (2026-11-10)
The user asked to check every row by the structure of the form, not only by the Excel cell types (the workbooks are hand-made and may have mistakes). Corrections are listed per tab in `PB1_TABS[].amount_fixes` (`AmountFix`: Excel row, start of the row's description, the row's amount columns). A fix is skipped with a WARNING if the row's description no longer matches (e.g. a changed template). It never turns template text into an amount field.
- **Poreski bilans** (70 → 84 fields): form lines without any amount cell get their section's column: line 2 → C (section I); lines 31 "Rashod banke…" and 34 → D (section III); lines 51–54, 56, 58 → C (V–VIII, like 55 and 57); lines 63, 65–68 → C (B. Kapitalni dobici, like 64).
- **Uporedo** (54 fields): "Poreski gubitak" had only Index → 2025, 2024, Index; lines 16 and 17 had no 2024 → added; the two unlabelled spacer rows (after lines 14 and 18) no longer show stray zeros.
- **Preliminarni rezultat** (49 → 47 fields): "Poreski gubitak" (left table) gets RSD; the left spacer rows (after lines 14 and 18) and the row below both tables no longer show stray zeros; the right table is unchanged.
- Check (endpoint function, scratch DB): FRIGOLAKTA and 1. OKTOBAR have identical amount fields in all three tabs, identical template cells, no amounts for 1. OKTOBAR. No fix was skipped. Not checked in the browser (the backend reload logged the browser out).
- Decided with the user: the heading "III Uskladjivanje rashoda" has no amount (its stray 0 in D removed, like the other headings; Poreski bilans now 83 fields); line 29 keeps its amount in E (Prekoracenje) as in Excel.
- A cell removed from the form by a fix also loses its Excel value (e.g. the stray 0 in C25 of Preliminarni rezultat, which FRIGOLAKTA still showed as a plain number). Checked through the endpoint function: rows 13 (Poreski bilans), 19/24 (Uporedo) and 20/25/28 (Preliminarni) show no stray values for FRIGOLAKTA either; the amount fields are identical for FRIGOLAKTA and 1. OKTOBAR.

### Addendum: "#" columns, Konto, full comments (2026-11-10)
- **Line-number columns** (`narrow_columns`: A in all tabs, and E in Preliminarni rezultat, the right table's numbering): header `#` (also the "R.b." cell inside Preliminarni rezultat, which has no header row), as narrow as their numbers (28 px; `width: 1%`), right-aligned, muted small text. A longer text in them (the right table's section headings in E: "Uvecanje…", "Umanjenje…", "Poreske olaksice") overflows into the empty cells to its right (`colSpan`), as in Excel.
- **Konto** (Poreski bilans only, as the user specified): column G of the sheet, header "Konto" (`header_overrides`, `konto_columns`). Konto numbers are shown as written (no number format: 5627, 554, "480 489 Potrazni saldo"); the stray 0 in G28 is not a konto and is left out. G..Q were helper columns before; now G is part of the form, H..Q are still left out.
- **Nothing truncated:** text cells wrap and are shown in full (long comments in "Komentar stopa konto", descriptions, konto texts); numbers stay on one line. The enlarged hover preview is kept only for numbers.
- Checked in the browser (FRIGOLAKTA and 1. OKTOBAR, all three tabs): headers `#`/Konto, first column 28 px, no truncated cells, no horizontal scroll; template cells identical for both companies (API).

### Addendum: typo corrections and konto/comment alignment (2026-11-10)
- **Typos** in the descriptive texts of all three tabs are corrected for display (`app/pb1_texts.py`; the workbook is still only read). First a general cleanup (single spaces, no trailing spaces, the conjunction typed as "I" → "i"), then `CORRECTIONS` (cleaned original → corrected text, 70 entries, applied wherever the text appears, headers included). All 70 matched a text in the 2025 file. Examples: uspwha → uspeha, Dobitci/Gubitci → Dobici/Gubici, predhodne → prethodne, porske → poreske, dobt → dobit, kaptalni/kapiotalni → kapitalni, rezistentnog → rezidentnog, jurizdiukcije/prefencijalnim → jurisdikcije/preferencijalnim, obugvaćene UPPE-om → obuhvaćene UPPR-om, "B Poreska osnovica" → "V. Poreska osnovica" (A., B., V.), missing commas/semicolons between joined legal phrases, "r.b.16" → "r.b. 16", "(11-12)>0" → "(11-12) > 0". The spelling without diacritics used throughout the form (Troskovi, placanja, ...) is kept.
- The corrections run after the amount fixes, which check the original descriptions; the company name used for the PB-1 link is not affected.
- **Alignment** (accounting rule): numbers and numbers written as text (konto lists "57, 58", "6704, 6705") are right-aligned; comments with words ("Procenjuje Poreska uprava", "480 489 Potrazni saldo") are left-aligned. Checked in the browser on FRIGOLAKTA; template texts identical for FRIGOLAKTA and 1. OKTOBAR (API).
- Not changed (content, not typos), for the user to decide: Preliminarni rezultat says "Za uplatu porez na dobit po godisnjem obracunu **za 2024**" and "Placene mesecne akontacije **za 2026**" in the 2025 form; Uporedo says "Placene mesecne akontacije za 2024".

### Addendum: Poreski bilans summary table, one-line left-aligned headers (2026-11-10)
- **Summary table** (Poreski bilans only): the form's last four rows ("V. Poreska osnovica", line 69 Poreska osnovica, Porez 15%, Mesecna akontacija) are shown as a separate table below the form, as the total of everything. Backend: `summary_label` in the tab spec (the row whose original description starts with "B Poreska osnovica" and all rows after it; WARNING and no summary if not found), `summary_start` on the sheet, `summary` in the API response (moved out of `rows`; 80 + 4 rows). Frontend: the summary table has the form's columns, with widths measured from the form table (`useColumnWidths`, ResizeObserver), so the amounts line up; it stays visible below the scrolling form.
- **Headers** on one line (`whitespace-nowrap`; a column is at least as wide as its header, e.g. "Komentar, stopa, konto" 16 → 22 characters) and left-aligned in all tabs (amount and `#` headers were right-aligned before).
- Checked: API (FRIGOLAKTA and 1. OKTOBAR: 80 form rows + 4 summary rows, Uporedo/Preliminarni without summary), `tsc` and build. Not checked in the browser: the backend reload logged the browser out.

---

## 2026-11-11: Session 24: PB-1 tables: no hover, shaded sections, editing

### Completed
- **No mouse reaction** in the PB-1 tables (rows and cells): no hover highlight, no enlarged preview.
- **Shaded section rows:** rows whose description (column B) is bold in the sheet get a grey background (`bg-muted/60`), in all three tabs (API `shaded` per row). Poreski bilans: the section headings A., I–IX, B., V. and the summary rows; Uporedo: lines 11, 13, 15; Preliminarni rezultat: the title, the "R.b./Opis" row and lines 11, 13, 15.
- **Every PB-1 field can be edited** (decided with the user), except the line numbers (`#`):
  - **Amounts** are saved for the company (its identity: GFI workbook + GFI row, like the PB-1 link). **Template fields** (descriptions, comments, konto, the section headings written in Preliminarni rezultat column E) are shared: a change applies to every company.
  - Click a field (or Enter / F2 on it) to edit: numbers in an input (`1.234,56`, `1234.56`, empty clears), texts in a textarea; Enter or leaving saves, Escape cancels. No hover reaction; edited fields get the corner marker used on Home.
  - Saving the value shown before any edit removes the edit (amounts compared to two decimals, since the file may hold more).
  - **Storage:** SQLite `edits.db`, new table `pb1_edits` (created at startup; also used in PostgreSQL mode for now). The PB-1 workbook is never written. PostgreSQL follows with the planned PB-1 migration.
  - **Service for automation:** `save_pb1_cell()` in `app/pb1.py` validates and saves one field without HTTP (raises `Pb1EditError` with a status code); the API endpoint `PUT /api/reporting-years/{year}/companies/{row}/pb1/{tab}/cells/{column}/{cell_row}` only calls it. The user expects most data to be filled in by the app itself later, so automation should call this function. `load_pb1_form()` / `build_pb1_table()` build the response.
  - **Frontend:** PB-1 edits use the app-wide autosave queue (`PendingEdit.pb1`: company, tab, shared), so they are kept in `localStorage` until saved, retried, and resumed after a session expiry like GFI edits. `usePb1` shows the change at once and applies unsaved changes after a reload; the Home/Registry editor ignores PB-1 results. The PB-1 page shows the save status, and the badge says "N values entered" for a company without file values that has entered amounts.

### Test results
- Backend, scratch copy of `edits.db` (`test_pb1_edits.py` in the scratchpad), 20 checks passed: `#` read-only (409); amounts numeric; an amount saved for 1. OKTOBAR is not shown for FRIGOLAKTA or another company; a description edit and a konto edit apply to every company; a summary-row amount; FRIGOLAKTA clearing an amount is an edit; text into an amount and a number into a text 422; unknown field / tab 404; Uporedo amount; Preliminarni heading in E editable, its line numbers 409; 7 edits stored, all removed again by saving the original values.
- Real `edits.db`: `pb1_edits` created (empty); 0 GFI edits.
- `tsc` and `npm run build` pass.
- **Not checked in the browser:** the backend reload logged the browser out.

### Open / next tasks
- User: log in and check FRIGOLAKTA: no hover, grey section rows; edit a field and see it saved (and that a description change shows for other companies, an amount does not).
- Later (user): refine how template edits work.
- Commit sessions 10–24.

### Addendum: which PB-1 fields are editable (2026-11-11)
Narrowed by the user: the "Opis" column is not editable in any tab, and in Preliminarni rezultat neither the right table ("Uvecanje poreske osnovice po Poreskom bilansu": headings in E, descriptions in F) nor anything above "Opis".
- Rule now (`pb1_edit_kind`): **amount fields** are editable (per company) in all tabs; **template fields** only in the tab's `editable_template_columns`: Poreski bilans F ("Komentar, stopa, konto") and G ("Konto"); none in Uporedo and Preliminarni rezultat. Everything else is read-only: `#`, Opis, "RSD", the right table's texts, and empty cells outside the form.
- The real `edits.db` had no PB-1 edits, so nothing was lost.
- Backend test suite updated, 25 checks passed (new: Opis 409 and never editable in any tab, empty cell outside the form 409, Preliminarni E heading / F / "RSD" 409, Preliminarni G amount editable, comment F shared by all companies).

### Addendum: editable again except the listed fields; blank amounts (2026-11-11)
- Corrected by the user: everything stays editable except what was listed. Rule now (`pb1_edit_kind(sheet, row, column, cell)`): read-only are the line-number columns (`#`), the tab's `readonly_columns` (Opis = B in every tab; in Preliminarni rezultat also F, the right table's texts "Uvecanje poreske osnovice po Poreskom bilansu" etc.; its column E is a line-number column) and `readonly_top` (Preliminarni rezultat rows up to 4 in A–C: the title above Opis and the "R.b. | Opis | RSD" header row). Everything else is editable: amounts per company; template fields for every company, also empty ones (empty fields in amount columns as numbers, elsewhere as text) and non-empty ones (comments, konto, the Uporedo spacer rows, the gap column D of Preliminarni rezultat). G3 (an amount next to the title rows) stays editable.
- **Bug fixed:** clicking an amount field whose file value is a blank `" "` (shown as 0,00) and leaving it stored an empty "edit". The real `edits.db` has 4 such records (FRIGOLAKTA: Uporedo E14, Preliminarni C35, C37, C42; made by clicking on 2026-11-11 00:40–00:41; no value). Now: for amounts, a blank or an Excel error counts as empty when comparing (`_same_value`), so saving such a field removes the record; records equal to what is shown are ignored when the tab is built (the 4 records show no marker, nothing deleted); the editor sends nothing when the value did not change (`editValue`).
- Backend test suite: 32 checks passed (new: empty field in an amount column edited as a shared number, Uporedo spacer and Preliminarni D editable, Preliminarni title / header row 409, G3 editable, blank-over records not shown as edits and removed by saving).

### Addendum: Poreski bilans head rows 1–3 (2026-11-11)
- The sheet's first three rows (above the header) are shown for every company as a separate table above the form, in the form's columns A–G, with column widths measured from the form table (`AlignedTable`, shared with the summary table):
  - row 1: "PB 1 2025" and three numbers (D 12, E 4.874.508,00, F 9.749.016,00);
  - row 2: the company name and "Klasa 5 | Klasa 6": the name written in the file (FRIGOLAKTA) is replaced by the name of the company whose form it is (`company_name_cell`);
  - row 3: the class 5 / class 6 totals (C, D and again E, F).
- Every number in these rows is the company's amount (`head_rows=3` in the spec; any column, not only C–E): FRIGOLAKTA sees the file's values, other companies 0,00; editable per company. Their texts are read-only. Not shaded.
- API: `head` (rows 1–3, moved out of `rows`), `Pb1Sheet.head_end`.
- **Bug caught before it reached real data:** the company name for the PB-1 link was read from the rows above "the first row read"; with the head rows read too, it was not found and the link was removed (in the scratch test database only; the real `pb1_links` still links FRIGOLAKTA to row 119, as no PB-1 page was opened in between). Fixed: the header row is found from the first form row after the head rows. The test suite now checks that FRIGOLAKTA keeps its values.
- Backend test suite: 37 checks passed (new: FRIGOLAKTA has values, 80 + 4 rows; head rows 1–3; company name per company; head numbers are editable amounts, file values only for FRIGOLAKTA; head texts read-only). `tsc` and build pass. Not checked in the browser (logged out by the backend reload).
- Open question for the user: D1 = 12 (probably the number of months for the monthly advance) is treated as a company amount like the other numbers, so other companies see 0,00 there.

### Addendum: D1 = 12 constant; Excel fill colors of the head rows (2026-11-11)
- **D1 = 12** (months; Mesecna akontacija = porez / 12) is a constant of the form (decided with the user): `head_constants` in the spec. Shown to every company as `12`, editable as a shared template number (a change applies to every company), no longer a company amount.
- **Fill colors** of the head rows (rows 1–3) come from the sheet (`Pb1Cell.fill`, API `fill` "#rrggbb", only solid non-white fills, head rows only): E1/F1 and the company name B2 light blue `#a6caf0`, "Klasa 5"/"Klasa 6" gold `#ffcc00`, class 5 totals C3/E3 light yellow `#ffffcc`, class 6 totals D3/F3 peach `#ffcc99`.
  - Exception to "only theme colors", requested by the user: the colors are data from the workbook, passed as the CSS variable `--cell-fill` (`FILL` in `Pb1Table`). Light theme: the color as in Excel; dark theme: mixed into the background (`color-mix(in oklab, fill 25%, background)`) so the text stays readable.
- Backend test suite 37 checks passed; the constant edit is shared (seen by FRIGOLAKTA). `tsc` and build pass. Not checked in the browser (logged out by the backend reload).
- Head table without its empty last column (G, below nothing: confirmed by the user, "iznad konta nema nista"): `usedColumnCount` leaves out trailing columns with no value, amount field or fill in the head rows; the remaining columns A–F keep the form table's widths, and the head table is narrower by G's width (`w-fit`, `tableWidth`). The form and the summary table keep all columns. `tsc` and build pass; not checked in the browser (logged out).
- Also the empty first column (A, above `#`) is left out of the head table (user's request): `usedColumns` returns the range from the first to the last column with content (B–F); `AlignedTable` draws only that range, as wide as those columns and moved right by the width of the columns left out at the start (`marginLeft`), so every column stays above its own. `tsc` and build pass; not checked in the browser (logged out).

### Addendum: Home status colors (2026-11-11)
- Home, columns Preliminarni … PB-1,PB-2 za rad (the numeric columns shown on Home, holding only 0 and 1): every **1 is green**, every **0 red** (text color, also for empty cells shown as 0, for the formula columns, and in the hover preview). Other numbers keep their normal color (negative Excel numbers stay red). Company Registry unchanged.
- Theme: new semantic token `--success` (green) in `src/index.css` for light and dark (`--color-success`, class `text-success`); red is the existing `text-destructive`. `DataCell` prop `statusColors`.
- Real data (2025), values in these columns: Preliminarni 13 × 1 / 144 × 0 / 8 empty, GFI uradjen 131 / 26 / 8, GFI ZA RAD 22 / 143, PB-1, PB-2 145 / 6 / 14, Predat 1 / 150 / 14, PB-1,PB-2 za rad 144 / 21: only 0, 1 and empty.
- `tsc` and build pass; not checked in the browser (logged out).

---

## 2026-11-11: Session 25: Excel formula logic in the app

Requested by the user: cells that hold a calculation in Excel are computed the same way in the app; references follow the internal tables, not the "#" line numbers.

### Completed
- **Home:** the GFI workbook has formulas only in GFI ZA RAD (`=+G-I`, 139 company rows) and PB-1,PB-2 za rad (`=K-L`, 151 rows), both already computed in every row since Session 19 (checked again; nothing to change).
- **PB-1 formulas extracted** from the workbook once: Excel (COM, PowerShell) opened a **copy** of `2025 PB-1.xls` in the scratchpad read-only and listed its 125 formulas (xlrd can't read .xls formulas). The original file was not opened (mtime still 2026-10-29). 116 are kept in `app/pb1_formulas.py` (`FORMULAS`, generated from that list, keyed by tab and Excel address); left out: copies of descriptions / company name in Preliminarni rezultat (B1, F5, F7, F8), the check value G28 in the Konto column, cells below the form (rows 105, 108).
- **Evaluator** (`app/pb1_formulas.py`): numbers, cell / range / other-sheet references, `+ - * /`, unary signs, comparisons, `IF`, `SUM`; Excel errors (#DIV/0!) propagate; text and empty count as 0. Formulas reference Excel addresses and the app keys every form row by its Excel row, so they map one to one ("#" line numbers are display only).
- **Verification:** whenever a PB-1 workbook is loaded, every formula is evaluated from the file's own values and compared with the result Excel stored (`verify_formulas`); all 116 match for 2025 (log: "PB-1 formulas verified against 2025 PB-1.xls: 76 computed cells"). If any differs (e.g. a changed template), computed cells are switched off for that workbook and an ERROR is logged.
- **Computed cells** (`computed_cells` in `app/pb1.py`): the 76 amount fields holding a formula (Poreski bilans 20 incl. head C3, D3, F1 and summary C86, C88; Uporedo 31; Preliminarni 25). They are calculated from the current values of the whole form, across tabs (Uporedo and Preliminarni use Poreski bilans), with edits; helper cells outside the form (H–Q, e.g. the amortization in K29 → D29) come from the file for the file's company and are empty for the others. Read-only (`formula: true`, 409 on save). `PUT` returns the tab's recomputed cells (`computed`), applied at once on the page; other tabs recompute when opened.
- `Pb1Workbook.raw`: every non-empty cell of each sheet (helper columns included), used as formula inputs and for the check.

### Test results
- Formula check: 116/116 equal to Excel's stored results (numbers to 0.005, #DIV/0! where Excel has it).
- Backend suite on a scratch copy of `edits.db`: 54 checks passed (new: formula cells read-only and 409; C3 = E3 + J15, C5/C7 IF, D30 = D3 × F30, C74 sum, F1 = E1 × 2, C88 = C87 / D1, Uporedo C6 = PB!D3, C8, E6 #DIV/0! shown empty, Preliminarni C5/C7 follow edits on another tab; FRIGOLAKTA's C74 follows a D28 change; another company untouched; all test edits removed). Older tests moved off cells that are now formulas.
- Browser (FRIGOLAKTA, read-only checks): head table above columns B–F (aligned to the pixel), 12, fills; summary −782.907,45; Uporedo 33,34% / 49,88% / 346,92% / 2519,94% / 97,02%; Preliminarni −782.907,45, 78.526,21, −1.030.484,19: all as in Excel. `tsc`, build pass. Real `edits.db` unchanged.

### Notes / open
- Preliminarni rezultat C25 (unlabelled spacer row) has a formula in Excel (`IF(C8+C16-C22+C23<0, …, 0)`); it is not shown, as decided earlier for that spacer row. To decide with the user.
- The descriptions' own line references (e.g. "Ostatak oporezive dobiti (52-54)") follow the official form numbering, not this sheet's "#"; the app follows Excel's formulas.

---

## 2026-11-12: Session 26: PB-1 comments beside the table, one per row and company

Agreed with the user: the column "Komentar, stopa, konto" (Poreski bilans, F) is taken out of the table and shown beside it as description-comment pairs, one comment per row. What the table held so far is the **default** (the user had not added anything); anything written from now on applies **only to that company**, saved in the database.

### Completed
- **Settings (defaults):** SQLite table `pb1_comment_defaults` (year, PB-1 file, tab, row, number or text, source "workbook"), filled once from the workbook the first time it is used (`comment_defaults` → `seed_pb1_comment_defaults`, never overwrites an existing default). 19 defaults for 2025. Rates (numbers in a percent format: 5%, 5%, 0,10%, 0,50%) stay numbers; konto numbers become text ("670", "5797", "57, 58").
- **Per company:** a company's comment is a `pb1_edits` row of column F with the company's identity (like its amounts); it replaces the default for that company only. Saving the default again removes it. Edit kind `comment` (`pb1_edit_kind`): text, or a number for a rate (422 for text there).
- **Formulas:** the rates are formula inputs (D30–D33 = D3 × rate), so a company's own rate is used in its formulas; other companies keep the default.
- **API:** `columns` no longer contain F; `comment_column: "F"` (the comments are the F cells of the rows, with `editable`, `number`, `edited`); `head_columns` (A–F): the head table's own columns, one to one with the table's (the head amounts F1 / F3 stand in the last column's place, above Konto).
- **Frontend:** `Pb1Comments` panel beside the table (`xl:` two columns, below the table on narrower screens): "Komentari", for every row with a description "# · Opis" and the comment (or "-"); a click edits it (text area; rates as percent: "5" or "5%" = 0,05), saved through the autosave queue; edited comments get the corner marker; no hover reaction; section rows shaded like in the table.
- Spec: `comment_column`, `head_columns` in `PB1_TABS` (Poreski bilans only; Uporedo and Preliminarni have no comment column).

### Test results
- Backend suite on a scratch copy of `edits.db`: 59 checks passed (new: F not a table column, head columns A–F; defaults from the workbook (comment, konto as text, rate as number); a comment saved for one company is not seen by FRIGOLAKTA or another company; konto comment as free text; text into a rate 422; a company's own rate changes its D30 only).
- Real `edits.db`: `pb1_comment_defaults` created, filled on the first PB-1 view (no company comments yet).
- Browser (FRIGOLAKTA): table columns # | Opis | Priznati | Ostvareni | Prekoracenje | Konto; head table aligned to the pixel; comments panel beside it with 84 pairs; no horizontal scroll. `tsc` and build pass.
- Testing note: reloading the page through the Chrome tool's script left that tab unresponsive (the tool, not the app: a fresh tab loads the same page normally).

### Open / next tasks
- A settings page for editing the default comments (the defaults are stored, there is no page for them yet).
- PostgreSQL: `pb1_comment_defaults` and `pb1_edits` move with the PB-1 migration.

---

## 2026-11-12: Session 27: Tax loss ("Gubitak!")

Requested by the user: if the tax base (Poreska osnovica) is negative, there is a tax loss: a short red "Gubitak!" banner at the top, and the tax and the monthly advance are automatically 0.

### Completed
- In the workbook the tax is typed in (no formula) and the monthly advance is a formula of it. New rule (`LOSS_RULES` in `app/pb1.py`): when a tax base is negative, its tax is 0 and read-only (computed, 409 on save); the advance follows through its formula:
  - Poreski bilans: Porez 15% (C87) ← Poreska osnovica (C86); Mesecna akontacija C88 = C87 / D1 → 0;
  - Uporedo: Porez na dobit za godinu C13 ← C12 (and the previous year D13 ← D12); Konacni porez and the advances C15/C20 (D15/D20) follow;
  - Preliminarni rezultat: Porez na dobit C14 ← C13; C16, C21 follow.
  When the base is not negative, the tax is a normal input again; a tax typed earlier is kept and comes back.
- **Banner:** `loss: {base}` in the PB-1 API (from the Poreski bilans base) and in each save result; the PB-1 page shows a destructive `Alert` "Gubitak!" with "Poreska osnovica −782.907,45: porez i mesečna akontacija su 0." on every tab. When a save starts or ends a loss, the tab reloads (cells become locked or editable again).

### Test results
- Backend suite on a scratch copy of `edits.db`: 68 checks passed (new: FRIGOLAKTA loss with its base; tax 0 read-only and advance 0; tax edit 409; loss also in Uporedo and Preliminarni; no loss without a negative base; positive base: typed tax 150 → advance 12,50; negative base: loss, tax and advance 0; positive again: the typed tax is back). An older test (company 2 with Dobici od prodaje 1.234,50 → base −1.234,50) now correctly expects the tax to be locked.
- `tsc` and build pass. **Not checked in the browser:** the backend reload logged the browser out.

### Addendum: monthly advance = tax / months in business (2026-11-12)
- Rule from the user: akontacija = porez / broj meseci poslovanja firme (for now 12). The months are therefore the **company's own** value, no longer a constant shared by all companies (Session 25 had made D1 = 12 shared).
- D1 of Poreski bilans (the "12" in the first head row; the formulas already divide by it: PB C88 = C87/D1, Uporedo C20 = C15/PB!D1, Preliminarni C21 = C16/PB!D1) is now `months_cell` in the spec, edit kind `months`: saved per company (company identity, like amounts), default 12 for every company (the file's value), a whole number 1–12 (422 otherwise; empty = back to 12).
- Not changed: Uporedo D20 (previous year) = D15/12 as in Excel (that year's months in business are not known).
- Real `edits.db` had no edit of D1, so nothing to migrate.
- Backend suite 75 checks passed (new: default 12 for every company; months 6 for one company → advance 150/6 = 25 in all three tabs; other companies and FRIGOLAKTA keep 12; 0, 13, 6.5, text → 422; 12 again = no edit). `tsc` passes; not checked in the browser (logged out).
- **Label and fixed value (user's follow-up):** the label "Meseci poslovanja" is written in the empty head cell left of the number (C1, `months_label`; read-only, right-aligned like the column), so the row reads "PB 1 2025 | Meseci poslovanja | 12 | …". For now the months are **fixed at 12** (read-only for every company, 409 on save): `MONTHS_EDITABLE = False` in `app/pb1.py`. The per-company months (edit kind `months`, 1–12) stay in the code for the planned automatic calculation; switching the flag turns them on. Backend suite 73 checks passed (label, 12 read-only, 409, advance = tax / 12). Not checked in the browser (logged out).

---

## 2026-11-12: Session 28: PB-1 company actions: save, download PDF, print PDF

Requested by the user: buttons for the whole company form (all three tabs), above the tabs: save all changes, download the PDF, print the PDF, each in a fitting color; and one more save before switching tabs.

### Completed
- **Buttons** (`Pb1CompanyActions`, above the tabs): "Sačuvaj izmene" (green `success`, Save icon), "Preuzmi PDF" (`chart-2`, Download), "Štampaj PDF" (`chart-3`, Printer). Tinted outline buttons; a spinner while working; "Sve izmene su sačuvane." or an error alert.
  - Sačuvaj izmene: sends every unsaved change now and waits (`flush()` in the autosave queue: resolves true when the queue is empty, false when changes stay unsaved, e.g. offline).
  - Preuzmi PDF: saves first, then downloads `PB-1 <year> <company>.pdf`.
  - Štampaj PDF: saves first, then loads the same PDF (inline) in a hidden frame and opens the browser's print dialog (print, or save as PDF there).
- **Save before leaving:** switching tabs and the Back button first `flush()` the queue, then navigate.
- **PDF** (`app/pb1_pdf.py`, endpoint `GET /api/reporting-years/{year}/companies/{row}/pb1-pdf[?inline=true]`, login required): built by the backend from the same tables the API returns (`build_pb1_table` for each tab), so it matches the page: values with edits and formulas, amounts with two decimals (Serbian separators, red negatives), the "Gubitak!" notice, the head table with its Excel fill colors above its own columns, grey section rows, line-number spans, the summary table, and the comments as a last column "Komentar" in Poreski bilans. A4 landscape, one tab per page (Poreski bilans spans 5 pages for 2025), header row repeated on each page.
- **New dependency:** `reportlab>=5.1,<5.2` (5.1.0, released 2026-10-22) in `requirements.txt` and the venv. Font: a system TrueType font for č/ć/đ (Arial on Windows, DejaVu / Liberation on Linux; `PDF_FONT` / `PDF_FONT_BOLD` override, documented in `.env.example`).

### Test results
- PDFs for FRIGOLAKTA and 1. OKTOBAR generated on a scratch copy of `edits.db` and checked as images (rendered with pypdfium2 in a separate scratch venv, not a project dependency): headers, colors, values, loss notice (FRIGOLAKTA only), comments, the two side-by-side tables of Preliminarni rezultat. Fixed while checking: the `#` column was too narrow for two digits; section headings spanning from a line-number column were grey.
- Backend suite 73 checks passed; the PDF endpoint returns 401 without a login. `tsc` and build pass.
- **Not checked in the browser:** the backend reload logged the browser out (buttons, download, print dialog, save-before-tab-switch to be tried by the user).

---

## 2026-11-12: Planned: company registry across years and the 2026 year (design agreed, not built)

Agreed with the user:
- A **company registry** across years: the same company identity in 2025 and 2026 (`company` / `company_year`).
- A new sidebar section **"Migracija"** (not an option in the Reporting year dropdown): choose source and target year (2025 → 2026), a dialog lists all registry companies (search, select all / none, a checkbox each), "Konstruiši 2026" creates the year. Companies can be added / removed later from the same dialog (a removed company keeps its 2026 data if it comes back).
- Carried over: company details (NAZIV, PIB, REFERENT, office); the 2026 status columns start at 0; formulas as before.
- After construction, 2026 appears in the Reporting year dropdown (Home, Company Registry) like a year from a workbook.
- Later: PB-1 for 2026 (no `2026 PB-1.xls`).
- **Order:** this is built in PostgreSQL. Next step: the user installs PostgreSQL 18, creates the database and writes `DATABASE_URL` in `backend/.env`; then `alembic upgrade head`, `app.gfi_import 2025 --dry-run` and the import (SQLite edits carried over), then the registry and the Migracija page.
- Refined by the user: the Migracija page does not ask for years; it offers the **next year** directly (latest year + 1, built from the latest year): "Sledeća godina: 2026 (iz 2025)" with "Konstruiši 2026" and the company dialog. After 2026 exists it offers 2027 from 2026; the companies of an existing year are changed through the same dialog.

---

## 2026-11-12: Session 29: PostgreSQL active; company registry and Migracija (constructing the next year)

### PostgreSQL
- The user installed PostgreSQL 18 (18.6), created `income_tax_reporting` and set `DATABASE_URL` in `backend/.env`.
- `alembic upgrade head` (0001–0005), `alembic check` clean; `app.gfi_import 2025 --dry-run`, then the import: 165 companies, 165 company years, 13 referents, 8 offices, 1,980 snapshot cells, PB-1 link (FRIGOLAKTA, row 119) carried over, verification of all 165 rows × 12 columns passed, 9 import issues (PIB). SQLite had 0 GFI edits, so nothing was carried. The running backend now serves GFI data from PostgreSQL. PB-1 edits, comments and links stay in SQLite `edits.db` until the PB-1 migration (unchanged plan).

### Migracija (as agreed with the user)
- **Schema** (migration `0006`, round trip tested): `source_file.origin` ('workbook' | 'constructed', CHECK), `based_on_year`, `sha256` / `file_mtime` nullable (constructed years have no file); `company_year.active` (a deselected company of a constructed year is hidden, not deleted). Downgrade fails while a constructed year exists (no silent data loss).
- **Service** (`app/migration.py`, endpoints under `/api/migration`, PostgreSQL only, 409 otherwise):
  - `migration_status`: years (origin, source, companies shown), `next_year` = latest + 1, built from the latest year.
  - `registry(year)`: every company of the database with its details from its most recent year before `year`, its years, and whether it is in `year` (for the next year: proposed = the companies of the source year).
  - `construct_year(year, company_ids)`: only the next year; new `source_file` ("2026 (iz 2025)"), the source year's columns (headers, fields) copied; per selected company a `company_year` with the same `company` identity and Excel row as in the source year, **only NAZIV, PIB, REFERENT and the office carried over (current values, edits included)**, kom / Preliminarni / GFI uradjen / PB-1, PB-2 / Predat = **0**; snapshot cells (the year's "original" values: the carried details and the zeros, the source row's number formats; formula columns flagged) so later changes show as edits and Home can edit the zeros like numbers from Excel. GFI ZA RAD / PB-1,PB-2 za rad computed as always.
  - `set_year_companies(year, company_ids)`: constructed years only; new companies added like at construction, deselected ones hidden (`active = false`), reselected ones shown again with their values.
  - `load_table` and cell saves only use active company years (a hidden company's cell → 404).
- **Frontend:** sidebar group "Administracija" → **Migracija** (`/migration`): "Sledeća godina: 2026 — Pravi se iz 2025" with "Konstruiši 2026…"; a list of years (workbook / "konstruisana iz …", companies shown) with "Izmeni firme…" for constructed years and "Otvori" (selects the year, goes to Home). `CompanySelectDialog` (shadcn `dialog` + `checkbox`, added with the CLI; the `cn` import problem fixed again, stray `cn` package removed): registry with search, "Izaberi sve" / "Poništi sve" (on the shown list), "Izabrano X od Y", a checkbox per company with PIB · referent · office · years. After a change the Reporting year list reloads (`reloadYears` in `ReportingYearProvider`), so 2026 appears in the selector.

### Test results
- Scratch PostgreSQL database `income_tax_reporting_scratch` (schema + the same 2025 import; dropped afterwards; the real database was only migrated to 0006): 27 checks passed: status and next year; registry proposes 165; constructing 2026 with 160 companies; again 409; 2026 in the year list, constructed from 2025, next 2027; the 2026 table has the same columns and 160 rows; a 2025 rename and referent change are carried, PIB and office too; statuses 0, editable, not edited; formulas 0; no edits at start; excluded companies absent; a 2026 edit leaves 2025 unchanged and the formula follows; hide 2 + add 1; hiding a company removes it from the table (its cells 404) and restoring it brings back its 2026 value; registry marks the shown ones; changing a workbook year 409; empty selection 422; a year that is not next 409; 2025 still 165.
- Browser (logged in): Migracija page shows next year 2026 from 2025 and the 2025 row; the dialog lists 165 companies, all proposed; closed with "Otkaži" (nothing constructed). `tsc`, build, `npm audit --omit=dev` 0 vulnerabilities.
- Real database after the session: only 2025 (workbook), 165 company years, 0 changes: **2026 is to be constructed by the user** on the Migracija page.

### Open / next tasks
- User: construct 2026 on the Migracija page; then the planned review of the whole database content together.
- PB-1 for 2026 (no `2026 PB-1.xls`): the PB-1 buttons on Home lead to "No PB-1 template for reporting year 2026".
- Note for the review: PIB is stored on `company` (shared by all years): a PIB corrected in one year is the PIB in every year.

---

## 2026-11-12: Session 30: Database review before constructing 2026

Requested by the user before constructing 2026: check the transfer, editing, leftovers, PB-1 for every company, and the whole. Agreed: the SQLite storage stays in the background (fallback; PB-1 edits / comments still live there); PostgreSQL is the main database.

### Checks and results
1. **Transfer, Home, Company Registry:** the app reads GFI data from PostgreSQL. The API output from the database equals the Excel output for all 165 companies, cell by cell (0 differences, same columns and statistics 13 / 131 / 22, kom 153); the workbook's SHA-256 equals the imported one. Browser: Home 165 companies (2025 GFI TOKK 1.xlsx, statistics 13 / 131 / 22), Company Registry 165 rows (#118 FRIGOLAKTA | 101202434 | Keti | LJILJA); no unsaved changes waiting in the browser.
2. **Editing and autosave (end to end, real database):** Home: FRIGOLAKTA Preliminarni 0 → 1 ("All changes saved", statistic 14, saved in `company_year`, `change_log` entry), still 1 with "Changed. Excel value: 0" after a reload, back to 0 (no edit marker, statistic 13). Company Registry: REFERENT Keti → "Keti TEST" → Keti, saved both times.
   - **Found and fixed:** changing a referent / office to a new name left that name in the lookup table after changing back ("Keti TEST", unused). `set_text` now removes a referent / office no company uses any more (`_drop_if_unused`); tested on a scratch database (new name and back, office, moving to another name and back: lookup counts unchanged).
   - The test artifacts were removed from the real database: the unused referent "Keti TEST", the 4 `change_log` rows of the test, and row 119's `updated_at` / `updated_by` set back to the import state (like all other rows).
3. **Leftovers:** PostgreSQL: only the 165 companies of the list (165 `company`, 165 `company_year`, 1,980 snapshot cells = 165 × 12, 13 referents, 8 offices, 9 import issues, 1 PB-1 link; no orphans, no unused lookups, no cells outside the company rows). SQLite `edits.db`: 0 GFI edits; the **4 empty PB-1 records** (FRIGOLAKTA, Uporedo E14, Preliminarni C35 / C37 / C42, made by the click bug of 2026-11-11, no values) were deleted after a backup (`backend/data/edits.db.bak-20261112-cleanup`). Kept: 19 default comments (settings) and the SQLite PB-1 link (the same as in PostgreSQL: FRIGOLAKTA, row 119).
4. **PB-1 for every company:** PB-1 is not stored per company; every company's form is built from `2025 PB-1.xls` plus its own amounts / comments. Built for all 165 companies × 3 tabs from the database: 0 errors, the same shape for all (Poreski bilans 3 head + 80 + 4 summary rows, Uporedo 20, Preliminarni 33), file values and the loss banner only for FRIGOLAKTA (row 119), every head row shows its own company name, 0 edited cells, 0 entered amounts; the PDF builds. No PB-1 leftovers.
5. **Whole:** `alembic check` clean (0006); integrity queries all 0 (orphans, dangling lookups, duplicate rows, names company vs company year, rows without 12 cells, inactive rows, constructed years, `change_log`); database output == Excel output; Excel files unchanged (2026-10-29); no errors in today's log; Migracija ready: next year 2026 from 2025, registry 165 companies, all proposed. Scratch database dropped (only `income_tax_reporting` and `postgres` remain).

### Open / next tasks
- User: construct 2026 on the Migracija page.
- The backup `backend/data/edits.db.bak-20261112-cleanup` can be deleted once the user agrees.
- Backup `backend/data/edits.db.bak-20261112-cleanup` deleted (user's approval).
- Checked on a scratch database (dropped afterwards; the real database still has only 2025): after constructing 2026 (162 of 165 companies), Migracija offers **2027 from 2026**; its registry lists all 165 companies: the 162 of 2026 proposed, the 3 only in 2025 shown unchecked and selectable (their details from 2025); constructing 2027 with all 165 works, then 2028 is offered.

---

## 2026-11-12: Session 31: 2026 constructed; PB-1 forms of constructed years

### Review after the user constructed 2026
- `source_file` 2026: constructed from 2025 ("2026 (iz 2025)", by nikola); all **165** companies (all active), the same `company` identity and Excel row as in 2025; `gfi_column` identical to 2025; 1,980 snapshot cells; NAZIV / referent / office equal to 2025, all statuses 0; `change_log` empty; no unused lookups; 2025 untouched. App output for 2026: 165 rows, details equal 2025, statuses and formulas 0, statistics 0, no edits.

### PB-1 for constructed years (user's requirements)
- Every company of a constructed year gets the **same three PB-1 tabs**, with everything set up for them (head rows and fills, summary table, comments panel, formulas, tax loss, months, PDF), all amounts 0. Created **by the migration step**, not as a hard-coded fallback: `ensure_pb1_form` (in `construct_year`) records a constructed `pb1` `source_file` ("2026 PB-1 (iz 2025)", `based_on_year`).
- `pb1_template(year)` (app/pb1.py): the year's own `<year> PB-1.xls`, or for a constructed 'pb1' source the form of the year it was built from (followed back to a workbook: 2027 → 2026 → 2025). A form from another year's workbook has no file values for anyone (FRIGOLAKTA's 2025 amounts are not in 2026) and its read-only texts have their years moved on (`shift_years`: "PB 1 2026", "Uporedo 2026 i 2025", "Porez na dobit za 2026", "Preliminarni rezultati 2026. godine"; company names are never changed). Edits, comments and settings of 2026 are kept apart from 2025 (keyed by year).
- **As in the 2025 view in the browser, not only the workbook** (user's note): the form-level settings of the source year are taken over at construction (`copy_pb1_form_settings` in `edits_store`): the shared template edits (konto, comments changed for every company) and the default comments (settings, source "year 2025"). Company amounts and company comments are not carried over.
- Migracija page: each year shows its PB-1 form ("PB-1: 2025 PB-1.xls" / "2026 PB-1 (iz 2025)"); the description mentions the PB-1 form.
- The existing 2026 got its PB-1 form by running the same step once (`ensure_pb1_form(2026, 2025)`): 19 default comments taken over, 0 template edits (2025 has none).

### Test results
- Scratch database: PB-1 migration suite 19 checks passed: the status lists the PB-1 forms; 2026 PB-1 for all 165 × 3 tabs, same structure as 2025, all amounts 0; FRIGOLAKTA 2026 without file values or loss, 2025 unchanged; years moved on in tab titles, headers and texts; head (name, months, label, fills); 2025 settings taken over (a konto edit and a changed default comment), a 2025 company comment not; formulas; 2026 edits and comments apart from 2025; the loss rule in 2026; PDF; 2027 via 2026 ("PB 1 2027", "Uporedo 2027 i 2026"). The **2026 view equals the 2025 view cell by cell for all 165 × 3 tabs** (flags, formats, fills, shading, texts with years moved on), except the differences that come from 2025's values (FRIGOLAKTA's tax locked by its 2025 loss). Migration suite 27 and PB-1 suite 73 checks passed.
- Real database (read-only comparison): 2026 PB-1 for all 165 × 3 tabs, 0 differences to the 2025 view, 0 non-zero amounts; PDF 200. Browser: FRIGOLAKTA 2026 — tabs "Poreski bilans | Uporedo 2026 i 2025 | Preliminarni rezultat", head "PB 1 2026 | Meseci poslovanja | 12 | 0,00 | 0,00", 80 rows, comments panel, the three company buttons, no loss banner.
