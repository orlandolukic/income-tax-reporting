"""Background screenshots of the automated browser for the web UI's live view.

On Chrome/Edge a background thread keeps its own DevTools connection (not through chromedriver, so it
never queues up behind, or delays, the automation's WebDriver commands) and runs a screencast: Chrome
pushes a new JPEG whenever the page repaints, so the view follows the browser without polling delays.
While nothing repaints, a plain screenshot is taken every FALLBACK seconds (it also confirms the view is
current). Firefox falls back to WebDriver screenshots every INTERVAL seconds.

Only the newest frame is kept, in memory; nothing is written to disk.

Chrome keeps drawing a window that is covered or off-screen (see BACKGROUND_FLAGS in driver.py), but
not a minimized one: then no frame comes and the last one stays, with state "minimized". The
automation itself keeps working while minimized.

The page asks with `wait(version)`: it returns as soon as there is something newer than what the page
shows (long polling), so a new frame reaches the page right away."""
import base64
import json
import threading
import time
import urllib.request

import websocket

INTERVAL = 0.5  # seconds between WebDriver screenshots (Firefox)
MIN_GAP = 0.2  # at most ~5 screencast frames a second (the next frame is acknowledged after this)
FALLBACK = 2.0  # a screenshot when no screencast frame came for this long
WINDOW_CHECK = 1.0  # how often the window state (minimized or not) is checked
TIMEOUT = 8  # an answer from DevTools that takes longer than this means the connection is stuck
RECONNECT = 0.5  # wait before connecting again after an error
# Targets (tabs) the program uses in the background (e.g. the ePorezi report watcher): not offered in the live view.
HIDDEN: set[str] = set()


class BrowserScreen:
    def __init__(self, driver) -> None:
        self.driver = driver
        caps = driver.capabilities
        options = caps.get("goog:chromeOptions") or caps.get("ms:edgeOptions") or {}
        self.debugger = options.get("debuggerAddress")  # e.g. "localhost:51234"
        # Chromedriver window handles are DevTools target ids. Read it here, on the automation thread.
        self.target = driver.current_window_handle if self.debugger else None
        self.ws: websocket.WebSocket | None = None
        self.next_id = 0
        self.frame: tuple[bytes, str, float] | None = None  # (image, content type, time taken)
        self.version = 0  # grows with every new frame or change of `minimized`
        self.changed = threading.Condition()
        self.error = ""
        self.minimized = False
        self.stopped = threading.Event()
        self.retarget = threading.Event()  # follow() / choose() changed the window: connect to it
        self.auto = True  # show the window the program works in (else the one the user chose on the page)
        self.auto_target = self.target
        threading.Thread(target=self._run, daemon=True, name="browser-screen").start()

    def stop(self) -> None:
        self.stopped.set()
        with self.changed:
            self.changed.notify_all()

    def follow(self, handle: str) -> None:
        """The program now works in this window / tab (its WebDriver window handle = DevTools target id): show it,
        unless the user chose another one on the page."""
        self.auto_target = handle
        if self.auto:
            self._show(handle)

    def choose(self, target: str | None) -> None:
        """The page's choice: a target id from `windows()`, or None = follow the program."""
        self.auto = not target
        self._show(target or self.auto_target)

    def _show(self, target: str | None) -> None:
        if self.debugger and target and target != self.target:
            self.target = target
            self.retarget.set()

    def windows(self) -> dict:
        """The browser's pages (windows and tabs) for the page's view switcher."""
        pages = []
        if self.debugger:
            try:
                with urllib.request.urlopen(f"http://{self.debugger}/json", timeout=TIMEOUT) as response:
                    pages = [{"id": t["id"], "title": t.get("title") or t.get("url", ""), "url": t.get("url", "")}
                             for t in json.load(response)
                             if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")
                             and t["id"] not in HIDDEN]
            except Exception:
                pass
        return {"windows": pages, "shown": self.target, "auto": self.auto, "program": self.auto_target}

    def wait(self, version: int, timeout: float) -> bool:
        """Wait until there is something newer than `version` (True) or the timeout passes (False)."""
        with self.changed:
            return self.changed.wait_for(lambda: self.version != version or self.stopped.is_set(), timeout)

    def _publish(self, image: bytes | None = None, content_type: str = "", minimized: bool | None = None) -> None:
        with self.changed:
            if image is not None:
                self.frame = (image, content_type, time.time())
            if minimized is not None:
                if minimized == self.minimized and image is None:
                    return
                self.minimized = minimized
            self.version += 1
            self.changed.notify_all()

    def _run(self) -> None:
        while not self.stopped.is_set():
            try:
                if self.debugger:
                    self._screencast()
                    self._disconnect()  # follow(): connect to the other tab
                else:
                    started = time.monotonic()
                    self._publish(self.driver.get_screenshot_as_png(), "image/png")
                    self.error = ""
                    self.stopped.wait(max(0.0, INTERVAL - (time.monotonic() - started)))
            except Exception as e:  # e.g. the browser closed or restarted; keep the last frame and try again
                self.error = str(e).splitlines()[0] if str(e) else type(e).__name__
                self._disconnect()
                self.stopped.wait(RECONNECT)
        self._disconnect()

    def _screencast(self) -> None:
        """One DevTools connection: start the screencast and handle its frames until an error or stop."""
        self._connect()
        pending: dict[int, tuple[str, float]] = {}  # call id -> (what, sent at)

        def send(method: str, params: dict, what: str) -> None:
            self.next_id += 1
            self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
            pending[self.next_id] = (what, time.monotonic())

        send("Page.startScreencast", {"format": "jpeg", "quality": 60, "everyNthFrame": 1}, "start")
        last_frame = last_window = 0.0
        ack: tuple[int, float] | None = None  # (screencast session id, when to acknowledge it)
        self.ws.settimeout(0.1)
        while not self.stopped.is_set():
            if self.retarget.is_set():
                self.retarget.clear()
                return
            now = time.monotonic()
            if ack and now >= ack[1]:  # acknowledging asks Chrome for the next frame
                send("Page.screencastFrameAck", {"sessionId": ack[0]}, "ack")
                ack = None
            if now - last_window >= WINDOW_CHECK and "window" not in (w for w, _ in pending.values()):
                # Asking a minimized window for a screenshot would just wait until it's restored.
                send("Browser.getWindowForTarget", {}, "window")
                last_window = now
            if (now - last_frame >= FALLBACK and not self.minimized
                    and "shot" not in (w for w, _ in pending.values())):
                send("Page.captureScreenshot", {"format": "jpeg", "quality": 60}, "shot")
                last_frame = now
            for what, sent in pending.values():
                if now - sent > TIMEOUT:
                    raise TimeoutError(f"DevTools did not answer ({what})")
            try:
                message = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if message.get("method") == "Page.screencastFrame":
                params = message["params"]
                self._publish(base64.b64decode(params["data"]), "image/jpeg")
                self.error = ""
                last_frame = time.monotonic()
                ack = (params["sessionId"], last_frame + MIN_GAP)
                continue
            what, _ = pending.pop(message.get("id"), ("", 0))
            if not what:
                continue
            if "error" in message:
                if what == "shot":  # e.g. during a page load; the screencast goes on
                    continue
                raise RuntimeError(f"{what}: {message['error'].get('message', 'DevTools error')}")
            result = message.get("result", {})
            if what == "window":
                self._publish(minimized=result.get("bounds", {}).get("windowState") == "minimized")
            elif what == "shot":
                self._publish(base64.b64decode(result["data"]), "image/jpeg")
                self.error = ""

    def _connect(self) -> None:
        self.retarget.clear()
        url = f"ws://{self.debugger}/devtools/page/{self.target}"
        try:
            self.ws = websocket.create_connection(url, timeout=TIMEOUT, suppress_origin=True)
        except Exception:
            # The tab may have been replaced: use the first page target instead.
            with urllib.request.urlopen(f"http://{self.debugger}/json", timeout=TIMEOUT) as response:
                pages = [t for t in json.load(response) if t.get("type") == "page" and t["id"] not in HIDDEN]
            if not pages:
                raise
            self.target = pages[0]["id"]
            self.ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=TIMEOUT,
                                                  suppress_origin=True)

    def _disconnect(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
