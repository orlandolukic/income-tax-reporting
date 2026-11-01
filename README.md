# tim-automation

Client-server application: **FastAPI** backend (Python) + **React + TypeScript** frontend (Vite).

```
backend/    FastAPI app (port 8000)
frontend/   React app (port 5173, proxies /api -> backend)
DEVLOG.md   Development log (read this first in each new session)
```

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

- Application: http://localhost:5173. It shows **"Application is running"** and the backend status.
- Backend health endpoint: http://localhost:8000/api/health
- API docs (Swagger): http://localhost:8000/docs

Editing any file under `backend/app/` or `frontend/src/` reloads the matching server automatically.

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
