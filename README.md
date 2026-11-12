# Income Tax Reporting

Client-server web application for income tax reporting: **FastAPI** backend (Python) + **React + TypeScript** frontend (Vite).

## Features

- **Login** with server-side sessions (Log out from the header or sidebar menu).
- **Reporting year selector.** The years come from the GFI workbook file names (`<year> GFI *.xlsx`).
- **GFI company table** for the selected year (columns A–N of the workbook), shown with each cell's Excel number format (Serbian separators, `1.234,56`).
- **Editing with autosave.** Plain numeric cells can be edited in place. Edits are saved (SQLite now, PostgreSQL once set up) and shown on top of the Excel values. The Excel workbooks are never modified. Formula and empty cells are read-only.
- **Company Registry** (sidebar → Companies). All 165 companies with every GFI column. Besides the numeric fields, the company name, PIB, referent and office can be edited here. Changes show on Home too, and PB-1 links are kept.
- **PB-1 form per company, with three tabs** (Poreski bilans, Uporedo, Preliminarni rezultat), from `<year> PB-1.xls`. Open them with the three buttons in the Actions column on Home. The amounts are shown only for the company the file belongs to (linked once and stored); every other company sees the empty form. Read-only.
- Light, dark and system theme.

```
backend/    FastAPI app (port 8000)
frontend/   React app (port 5173, proxies /api -> backend)
DEVLOG.md   Development log (read this first in each new session)
CLAUDE.md   Project rules and design guidelines
```

## Data files

- GFI workbooks `<year> GFI *.xlsx` and PB-1 files `<year> PB-1.xls` are read from `GFI_DATA_DIR` (default: the project root). They are read-only.
- GFI data is stored in **PostgreSQL** once it is set up (see below). Until then, the app reads the GFI workbook directly and stores edits in `backend/data/edits.db` (SQLite, `DATABASE_PATH`; git-ignored).
- PB-1 is always read from the `.xls` file for now.

## Database (PostgreSQL)

The app switches to PostgreSQL as soon as `DATABASE_URL` is set in `backend/.env`. Without it, it keeps using Excel + SQLite.

1. Install **PostgreSQL 18** (Windows installer from https://www.postgresql.org/download/windows/). Choose a password for the `postgres` superuser.
2. Create a database and an app user (for example in **SQL Shell (psql)**, logged in as `postgres`):

   ```sql
   CREATE USER income_tax WITH PASSWORD 'choose-a-password';
   CREATE DATABASE income_tax_reporting OWNER income_tax;
   ```

3. Copy `backend/.env.example` to `backend/.env` and set:

   ```
   DATABASE_URL=postgresql://income_tax:choose-a-password@localhost:5432/income_tax_reporting
   ```

4. Install the Python packages and create the tables (from `backend/`):

   ```powershell
   .venv\Scripts\python -m pip install -r requirements.txt
   .venv\Scripts\alembic upgrade head
   ```

5. Import the GFI workbook. First check it, then import (from `backend/`):

   ```powershell
   .venv\Scripts\python -m app.gfi_import 2025 --dry-run
   .venv\Scripts\python -m app.gfi_import 2025
   ```

   The import keeps the company list (165 companies, up to DAGOTTA). It carries over all edits saved in SQLite, verifies every cell against the current table, and lists data issues such as missing or shared PIBs. If anything doesn't match, nothing is saved. The Excel file and `edits.db` are only read.

6. Restart the backend. The log shows `GFI data source: PostgreSQL`.

To import a year again later, use `--replace`. It refuses while any value has been changed in the database, so no edits are lost.

## Prerequisites

- Python 3.11+
- Node.js 20+
- VS Code (recommended extensions: Python, ESLint)

## First-time setup

Open the project folder in VS Code, then open a terminal (**Terminal → New Terminal**).

**Backend:**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**Frontend:**

```powershell
cd frontend
npm install
```

## Running locally

### Option A: VS Code task (both servers at once)

1. Press `Ctrl+Shift+P` → **Tasks: Run Task** → **Start all**.
2. Both servers start in separate terminal panels with auto-reload.

### Option B: Two terminals

Terminal 1 (backend):

```powershell
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Terminal 2 (frontend):

```powershell
cd frontend
npm run dev
```

### View in the browser

- Application: http://localhost:5173. Log in to see the company table for the selected reporting year.
- Backend health endpoint: http://localhost:8000/api/health
- API docs (Swagger): http://localhost:8000/docs

Editing any file under `backend/app/` or `frontend/src/` reloads the matching server automatically.

### Checks

From `frontend/`:

```powershell
npx tsc -p .      # type check
npm run build     # production build
```

## Application logging

Supported levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

**Backend:** set the `LOG_LEVEL` env var (default `INFO`). Logs go to the console and to `backend/logs/app.log` (rotating, 1 MB × 5 files).

```powershell
$env:LOG_LEVEL="DEBUG"; .venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Use it in code:

```python
from app.logging_config import get_logger
logger = get_logger(__name__)
logger.warning("Something happened")
```

**Frontend:** set `VITE_LOG_LEVEL` in `frontend/.env.local` (default `INFO`). Logs go to the browser console (F12).

```ts
import { getLogger } from "./logger";
const logger = getLogger("MyComponent");
logger.error("Something failed");
```
