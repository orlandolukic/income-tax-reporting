import os
import re
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

from tim_automation import config

# Keep Chrome/Edge rendering and running timers at full speed when the window is hidden behind other
# windows or minimized, so the automation and the live view don't depend on the window being visible.
BACKGROUND_FLAGS = [
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]
# Headless Chrome/Edge start at 800x600, too small for the site's tables.
HEADLESS_SIZE = "--window-size=1920,1080"

# Without a driver path, Selenium runs Selenium Manager before the browser starts. About once an hour (when its
# cache expires) that downloads a large version list from googlechromelabs.github.io, with no time limit: on a
# slow connection the program sat on "Pokretanje pretraživača..." for minutes with no window (logs of 2026-10-11).
# So a cached driver for the installed browser version is used directly, and Selenium Manager only when there is
# none (e.g. right after a browser update); then it doesn't send usage statistics and its downloads time out.
os.environ.setdefault("SE_AVOID_STATS", "true")
os.environ.setdefault("SE_TIMEOUT", "60")
DRIVER_CACHE = Path.home() / ".cache" / "selenium"
# browser -> (driver folder in the cache, driver file, registry key with the installed version, install folders)
BROWSERS = {
    "chrome": ("chromedriver", "chromedriver.exe", r"Software\Google\Chrome\BLBeacon",
               [Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application",
                Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application",
                Path(os.getenv("LOCALAPPDATA", "")) / "Google/Chrome/Application"]),
    "edge": ("msedgedriver", "msedgedriver.exe", r"Software\Microsoft\Edge\BLBeacon",
             [Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application",
              Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application"]),
}
VERSION = re.compile(r"^\d+(\.\d+){3}$")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def installed_version(browser: str) -> str:
    """The installed Chrome / Edge version ("155.0.8059.39"), "" if it can't be told (not on Windows, not found)."""
    if browser not in BROWSERS or sys.platform != "win32":
        return ""
    import winreg

    _, _, key, folders = BROWSERS[browser]
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as k:
                version = str(winreg.QueryValueEx(k, "version")[0])
                if VERSION.match(version):
                    return version
        except OSError:
            pass
    # The install folder has a subfolder per version.
    versions = [d.name for folder in folders if folder.is_dir() for d in folder.iterdir() if VERSION.match(d.name)]
    return max(versions, key=_version_key, default="")


def cached_driver(browser: str, version: str) -> Path | None:
    """A driver Selenium Manager downloaded earlier for this browser version (same major version is enough):
    ~/.cache/selenium/chromedriver/win64/<version>/chromedriver.exe. None if there is none."""
    if browser not in BROWSERS or not version:
        return None
    folder, exe, _, _ = BROWSERS[browser]
    major = version.split(".")[0]
    found = [p for p in (DRIVER_CACHE / folder).glob(f"*/*/{exe}") if VERSION.match(p.parent.name)]
    exact = [p for p in found if p.parent.name == version]
    same_major = sorted((p for p in found if p.parent.name.split(".")[0] == major),
                        key=lambda p: _version_key(p.parent.name), reverse=True)
    return (exact or same_major or [None])[0]


def _options(browser: str):
    options = webdriver.EdgeOptions() if browser == "edge" else webdriver.ChromeOptions()
    for flag in BACKGROUND_FLAGS:
        options.add_argument(flag)
    if config.HEADLESS:
        options.add_argument("--headless=new")
        options.add_argument(HEADLESS_SIZE)
    return options


def _chromium(browser: str, on_status=None):
    """Start Chrome / Edge: with the cached driver if there is one for the installed version, else (or if that
    driver doesn't fit) through Selenium Manager, which may download a driver."""
    driver_class, service_class = ((webdriver.Edge, webdriver.EdgeService) if browser == "edge"
                                   else (webdriver.Chrome, webdriver.ChromeService))
    version = installed_version(browser)
    path = cached_driver(browser, version)
    if path:
        print(f"Starting {browser} {version} with the cached driver {path.parent.name}.")
        try:
            return driver_class(options=_options(browser), service=service_class(executable_path=str(path)))
        except SessionNotCreatedException as e:  # e.g. the browser was updated meanwhile
            print(f"The cached driver {path.parent.name} doesn't fit {browser} {version}: {str(e).splitlines()[0]}")
    else:
        print(f"No cached driver for {browser} {version or '(version unknown)'}.")
    if on_status:
        on_status("Pokretanje pretraživača: traženje drajvera na internetu (može da potraje)...")
    print("Looking for the browser driver with Selenium Manager (needs the internet, may download it)...")
    started = time.monotonic()
    driver = driver_class(options=_options(browser))
    print(f"Selenium Manager done in {time.monotonic() - started:.1f} s.")
    return driver


def create_driver(on_status=None) -> webdriver.Remote:
    """Create a WebDriver. on_status(text) is told when the start may take long (a driver download)."""
    started = time.monotonic()
    if config.BROWSER == "firefox":
        options = webdriver.FirefoxOptions()
        if config.HEADLESS:
            options.add_argument("-headless")
        driver = webdriver.Firefox(options=options)
    else:
        driver = _chromium("edge" if config.BROWSER == "edge" else "chrome", on_status)

    print(f"Browser: {config.BROWSER}, {'headless (no window)' if config.HEADLESS else 'with a window'} "
          f"(started in {time.monotonic() - started:.1f} s)")
    if not config.HEADLESS:  # a headless browser has no screen to maximize to; it uses HEADLESS_SIZE
        try:
            driver.maximize_window()
        except WebDriverException as e:  # the window was closed / crashed right away: say so instead of a traceback
            driver.quit()
            raise RuntimeError(f"Prozor pretraživača se zatvorio odmah po pokretanju ({str(e).splitlines()[0]}).") from e
    return driver
