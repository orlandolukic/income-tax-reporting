"""Environment settings.

Values come from environment variables. `backend/.env` (git-ignored) is loaded first if
it exists; variables already set in the environment take precedence. See
`backend/.env.example` for the available settings.
"""

from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"


def load_settings() -> None:
    load_dotenv(ENV_FILE, override=False)
