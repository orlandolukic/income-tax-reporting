"""Local web UI: a small HTTP server that serves the React app in web/dist and replaces the Tkinter
windows. The automation calls ask(), which shows a prompt in the browser page and blocks until the
user answers it there. Console output and status changes are streamed to the page (Server-Sent Events)."""
import ipaddress
import json
import mimetypes
import queue
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tim_automation import config, log
from tim_automation.screen import BrowserScreen

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DIST_DIR = WEB_DIR / "dist"
MAX_LOG_CHARS = 200_000
SCREEN_WAIT = 10  # seconds a live-view request waits for a newer frame


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status = ""
        self.prompt: dict | None = None
        self.log = ""
        self.clients: list[queue.Queue] = []
        self.next_id = 0
        self.answer = None
        self.answered = threading.Event()
        self.requests: queue.Queue = queue.Queue()  # requests the page sends while a prompt is open
        self.shared: dict[str, object] = {}  # other state the page shows, e.g. "jobs"
        self.apis: dict[str, object] = {}  # name -> handler(action, body) for POST /api/<name>/<action>
        self.files: dict[str, Path] = {}  # prefix -> folder served (as downloads) at GET /files/<prefix>/<name>

    def snapshot(self) -> dict:
        return {"type": "state", "status": self.status, "prompt": self.prompt, "build": _build_id()}

    def broadcast(self, message: dict) -> None:
        # Serialize now: the automation may change the same dicts while clients are still sending.
        text = json.dumps(message, ensure_ascii=False)
        for client in self.clients:
            client.put(text)


_state = _State()
_url = ""
_PC_NAMES = {n.lower() for n in (socket.gethostname(), socket.getfqdn()) if n}  # Host names of this PC


# Live view: one screencast per browser ("tim" = TiM ERP, "purs" = the ePorezi browser of purs_queue). The view shows
# the browser the program works in ("program"), unless the page chose a window ("auto" False).
_screens: dict[str, BrowserScreen] = {}
_view = {"active": "tim", "program": "tim", "auto": True}
_SCREEN_ORDER = ("tim", "purs")


def _active_screen() -> tuple[BrowserScreen | None, int]:
    name = _view["active"] if _view["active"] in _screens else next(iter(_screens), "")
    return _screens.get(name), (_SCREEN_ORDER.index(name) if name in _SCREEN_ORDER else 0)


def _code(screen: BrowserScreen, index: int) -> int:
    """The version the page sends back: changes with every frame and when another browser is shown."""
    return screen.version * len(_SCREEN_ORDER) + index


def _wait_screen(shown: int, timeout: float) -> bool:
    """Wait until the shown browser has a newer frame, or another browser is shown (True), or timeout (False)."""
    deadline = time.monotonic() + timeout
    while True:
        screen, index = _active_screen()
        if screen is not None and _code(screen, index) != shown:
            return True
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        if screen is None:
            time.sleep(min(left, 0.5))
        else:
            screen.wait(shown // len(_SCREEN_ORDER), min(left, 0.5))


_at_line_start = True


def _on_output(text: str) -> None:
    """Forward console output to the page, with "YYYY-MM-DD HH:MM:SS" in front of every line."""
    global _at_line_start
    if not text:
        return
    stamp = f"{datetime.now():%Y-%m-%d %H:%M:%S}  "
    lines = text.split("\n")
    text = "\n".join(
        (stamp + line if line and (i > 0 or _at_line_start) else line) for i, line in enumerate(lines))
    _at_line_start = text.endswith("\n")
    with _state.lock:
        _state.log = (_state.log + text)[-MAX_LOG_CHARS:]
        _state.broadcast({"type": "log", "text": text})


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:  # keep request logs out of the console
        pass

    def _host_ok(self) -> bool:
        # Reject other host names so pages from other sites can't reach the server via DNS rebinding:
        # only an IP address (this PC's, or its LAN address from another PC), localhost or this PC's name.
        port = self.server.server_address[1]
        name, _, given = (self.headers.get("Host") or "").rpartition(":")
        if given != str(port):
            return False
        name = name.strip("[]").lower()
        if name in ("localhost", *_PC_NAMES):
            return True
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            return False

    def _send(self, status: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, path.read_bytes(), content_type)

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN)
        path = self.path.split("?")[0]
        if path == "/api/events":
            return self._events()
        if path.startswith("/files/"):
            return self._download(path)
        if path == "/api/screen":
            # ?v=<version the page shows>: wait (long poll) until there is something newer
            query = parse_qs(urlsplit(self.path).query)
            if _screens and query.get("v"):
                try:
                    shown = int(query["v"][0])
                except ValueError:
                    shown = -1
                if not _wait_screen(shown, SCREEN_WAIT):
                    return self._send(HTTPStatus.NO_CONTENT)
            screen, index = _active_screen()
            frame = screen.frame if screen else None  # the newest background screenshot (memory only)
            if frame is None:
                return self._send(HTTPStatus.SERVICE_UNAVAILABLE, b"The browser is not running.")
            image, content_type, taken_at = frame
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(image)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Taken-At", str(int(taken_at * 1000)))
            self.send_header("X-Version", str(_code(screen, index)))
            self.send_header("X-Minimized", "1" if screen.minimized else "0")
            self.end_headers()
            self.wfile.write(image)
            return
        file = (DIST_DIR / path.lstrip("/")).resolve()
        if not file.is_relative_to(DIST_DIR) or not file.is_file():
            file = DIST_DIR / "index.html"
        self._send_file(file)

    def do_POST(self) -> None:
        parts = self.path.strip("/").split("/")  # ["api", name] or ["api", name, action]
        if not self._host_ok() or len(parts) not in (2, 3) or parts[0] != "api":
            return self._send(HTTPStatus.FORBIDDEN)
        # Requiring JSON means a cross-site form can't post here without a CORS preflight (which we never allow).
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return self._send(HTTPStatus.BAD_REQUEST)
        if len(parts) == 3:
            return self._api(parts[1], parts[2], body)
        if parts[1] not in ("answer", "request"):
            return self._send(HTTPStatus.NOT_FOUND)
        with _state.lock:
            if not _state.prompt or body.get("id") != _state.prompt["id"]:
                return self._send(HTTPStatus.CONFLICT, b"This prompt is no longer open.")
            if parts[1] == "request":
                _state.requests.put(body.get("value"))
            else:
                _state.answer = body.get("value")
                _state.answered.set()
        self._send(HTTPStatus.NO_CONTENT)

    def _download(self, path: str) -> None:
        parts = path.split("/")  # ["", "files", prefix, name]
        folder = _state.files.get(parts[2]) if len(parts) == 4 else None
        file = (folder / parts[3]).resolve() if folder else None
        if not file or not file.is_relative_to(folder.resolve()) or not file.is_file():
            return self._send(HTTPStatus.NOT_FOUND, "Fajl ne postoji.".encode())
        body = file.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        disposition = "inline" if file.suffix == ".pdf" else "attachment"  # a PDF opens in the browser's viewer
        self.send_header("Content-Disposition", f'{disposition}; filename="{file.name}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api(self, name: str, action: str, body: dict) -> None:
        handler = _state.apis.get(name)
        if handler is None:
            return self._send(HTTPStatus.NOT_FOUND)
        try:
            result = handler(action, body)
        except Exception as e:  # shown to the user in the page
            message = str(e) or type(e).__name__
            return self._send(HTTPStatus.BAD_REQUEST, json.dumps({"error": message}).encode(), "application/json")
        self._send(HTTPStatus.OK, json.dumps(result, ensure_ascii=False).encode(), "application/json")

    def _events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        client: queue.Queue = queue.Queue()
        with _state.lock:
            _state.clients.append(client)
            client.put(json.dumps({"type": "log", "text": _state.log, "reset": True}, ensure_ascii=False))
            client.put(json.dumps(_state.snapshot(), ensure_ascii=False))
            for key, value in _state.shared.items():
                client.put(json.dumps({"type": "shared", "key": key, "value": value}, ensure_ascii=False))
        try:
            while True:
                try:
                    message = client.get(timeout=15)
                    self.wfile.write(f"data: {message}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (ConnectionError, OSError):
            pass
        finally:
            with _state.lock:
                _state.clients.remove(client)


def _needs_build() -> bool:
    index = DIST_DIR / "index.html"
    if not index.exists():
        return True
    built = index.stat().st_mtime
    sources = [WEB_DIR / "index.html", WEB_DIR / "package.json", WEB_DIR / "vite.config.ts", *(WEB_DIR / "src").rglob("*")]
    return any(p.is_file() and p.stat().st_mtime > built for p in sources)


def _build_id() -> str:
    """The page's main script as the built index.html names it (e.g. /assets/index-YPQpkkJ1.js): a page that runs
    another one (left open while the program was updated and restarted) reloads itself."""
    import re
    try:
        match = re.search(r'src="(/assets/[^"]+\.js)"', (DIST_DIR / "index.html").read_text(encoding="utf-8"))
    except OSError:
        return ""
    return match.group(1) if match else ""


def build() -> None:
    """Build the React app with npm if web/dist is missing or older than the sources."""
    if not _needs_build():
        return
    npm = shutil.which("npm")
    if not npm:
        if (DIST_DIR / "index.html").exists():
            print("npm not found; using the existing web UI build.")
            return
        raise RuntimeError("The web UI is not built and npm was not found. Install Node.js (https://nodejs.org).")
    if not (WEB_DIR / "node_modules").exists():
        print("Installing web UI packages (first run only)...")
        subprocess.run([npm, "install", "--no-fund", "--no-audit"], cwd=WEB_DIR, check=True)
    print("Building web UI...")
    subprocess.run([npm, "run", "build"], cwd=WEB_DIR, check=True, stdout=subprocess.DEVNULL)


def start(open_browser: bool = True) -> str:
    """Build the React app if needed, start the server in the background and open it. Returns its URL."""
    global _url
    register_api("screen", _screen_api)
    build()
    try:
        server = ThreadingHTTPServer((config.UI_HOST, config.UI_PORT), _Handler)
    except OSError:  # port taken (e.g. a second instance): use any free port
        server = ThreadingHTTPServer((config.UI_HOST, 0), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.subscribe(_on_output)
    port = server.server_address[1]
    _url = f"http://127.0.0.1:{port}/"
    if config.UI_HOST not in ("127.0.0.1", "localhost"):
        others = [f"http://{address}:{port}/" for address in _lan_addresses()]
        print("Web UI from other PCs: " + (", ".join(others) or f"http://<this PC's IP>:{port}/")
              + " (allow Python in Windows Firewall if they can't connect)")
    if open_browser:
        webbrowser.open(_url)
    return _url


def _lan_addresses() -> list[str]:
    """This PC's IPv4 addresses other PCs can use (loopback left out)."""
    try:
        found = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        return []
    return sorted(a for a in found if not a.startswith("127."))


def set_browser(driver, name: str = "tim") -> None:
    """Start taking screenshots of this WebDriver's window in the background for the page's live view
    (a screencast on its own thread, independent of the automation; frames stay in memory only).
    `name`: "tim" (TiM ERP) or "purs" (the ePorezi browser). Pass None when the browser is closed."""
    old = _screens.pop(name, None)
    if old:
        old.stop()
    if driver:
        _screens[name] = BrowserScreen(driver)


def _screen_api(action: str, body: dict):
    """The live view's window switcher: POST /api/screen/windows, /api/screen/show {"id": target or null = auto}.
    Lists the windows of both browsers."""
    screens = dict(_screens)
    if not screens:
        return {"windows": [], "shown": None, "auto": True, "program": None}
    if action == "show":
        target = body.get("id") or None
        if target is None:
            _view.update(auto=True, active=_view["program"])
            for screen in screens.values():
                screen.choose(None)
        else:
            for name, screen in screens.items():
                if any(w["id"] == target for w in screen.windows()["windows"]):
                    _view.update(auto=False, active=name)
                    screen.choose(target)
                    break
    elif action != "windows":
        raise ValueError(f"Nepoznata akcija: {action}")
    windows = []
    for name, screen in screens.items():
        windows += [{**w, "browser": name} for w in screen.windows()["windows"]]
    active, _ = _active_screen()
    program = screens.get(_view["program"]) or active
    return {"windows": windows, "shown": active.target if active else None, "auto": _view["auto"],
            "program": program.auto_target if program else None}


def show_window(handle: str, browser: str = "tim") -> None:
    """The program works in this window of this browser now: show it in the live view (unless the page chose one)."""
    _view["program"] = browser
    if _view["auto"]:
        _view["active"] = browser
    if browser in _screens:
        _screens[browser].follow(handle)


def show_browser(browser: str) -> None:
    """The program works in this browser again (its last window), e.g. TiM ERP after an ePorezi step."""
    _view["program"] = browser
    if _view["auto"]:
        _view["active"] = browser


def set_shared(key: str, value) -> None:
    """Send state the page shows outside prompts (e.g. "jobs") to every open page, now and on connect."""
    with _state.lock:
        _state.shared[key] = value
        _state.broadcast({"type": "shared", "key": key, "value": value})


def get_shared(key: str, default=None):
    """The last value sent with set_shared (e.g. "session": the user and the open company)."""
    with _state.lock:
        return _state.shared.get(key, default)


def register_files(prefix: str, folder: Path) -> None:
    """Offer the files in `folder` as downloads at GET /files/<prefix>/<file name>."""
    _state.files[prefix] = folder


def register_api(name: str, handler) -> None:
    """Handle POST /api/<name>/<action> with handler(action, body) -> JSON result (server thread).
    An exception is returned to the page as {"error": message}."""
    _state.apis[name] = handler


def status(text: str) -> None:
    """Show what the program is doing right now in the page header."""
    with _state.lock:
        _state.status = text
        _state.broadcast(_state.snapshot())


def ask(kind: str, data: dict, done=None, on_request=None, tick=None, poll_seconds: float = 0.5):
    """Show a prompt in the page and wait for the answer. If done() becomes True first, returns True.
    While the prompt is open the page can send requests; on_request(request, data) handles them on this
    (the calling) thread, may change `data` in place, and the changed prompt is sent to the page.
    tick() is called about ten times a second on this thread, e.g. to run jobs the page asked for."""
    with _state.lock:
        _state.next_id += 1
        _state.prompt = {"id": _state.next_id, "kind": kind, "data": data}
        _state.answered.clear()
        _state.requests = queue.Queue()
        _state.broadcast(_state.snapshot())
    try:
        next_poll = time.monotonic() + poll_seconds
        while not _state.answered.is_set():
            try:
                request = _state.requests.get(timeout=0.1)  # short waits keep Ctrl+C working
            except queue.Empty:
                request = None
            if tick:
                tick()
            if request is not None and on_request:
                try:
                    on_request(request, data)
                except Exception as e:
                    print(f"Request {request} failed: {e}")
                with _state.lock:
                    _state.broadcast(_state.snapshot())
            if done and time.monotonic() >= next_poll:
                next_poll = time.monotonic() + poll_seconds
                try:
                    if done():
                        return True
                except Exception:
                    pass
        return _state.answer
    finally:
        with _state.lock:
            _state.prompt = None
            _state.broadcast(_state.snapshot())


def ask_credentials(default_username: str = "", message: str = "") -> tuple[str, str] | None:
    """Show the login form. Returns (username, password), or None if cancelled."""
    answer = ask("login", {"username": default_username, "message": message})
    if not answer:
        return None
    return answer["username"].strip(), answer["password"]


def wait_for_user(message: str, done) -> bool:
    """Show a message until done() returns True or the user clicks "Nastavi". False if they click "Otkaži"."""
    return bool(ask("wait", {"message": message}, done))
