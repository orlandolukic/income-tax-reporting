import os

BASE_URL = os.getenv("TIM_ERP_URL", "https://www.tim-erp.com/ERPX_WEB/L36/loginPage.awp")
BROWSER = os.getenv("BROWSER", "chrome").lower()
# Strip: cmd's `set HEADLESS=1 && python main.py` stores "1 " with a trailing space.
HEADLESS = os.getenv("HEADLESS", "0").strip().lower() in ("1", "true", "yes", "da")
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "15"))
CREDENTIALS_TTL_HOURS = float(os.getenv("CREDENTIALS_TTL_HOURS", "24"))
UI_PORT = int(os.getenv("UI_PORT", "8765"))
# Address the web UI listens on: 0.0.0.0 = every network interface (other PCs can open it), 127.0.0.1 = this PC only.
UI_HOST = os.getenv("UI_HOST", "0.0.0.0").strip()
COMPANY_CACHE_DAYS = float(os.getenv("COMPANY_CACHE_DAYS", "5"))
PURS_URL = os.getenv("PURS_URL", "https://eporezi.purs.gov.rs/user/login.html")  # ePorezi login page
DEXPRESS_GP_URL = os.getenv("DEXPRESS_GP_URL", "https://usersupport.dexpress.rs/ExternalApi/GP")  # D Express grouped payment
