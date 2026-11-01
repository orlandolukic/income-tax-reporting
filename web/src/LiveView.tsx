import { useEffect, useState } from "react";
import { callApi } from "./api";

type BrowserWindow = { id: string; title: string; url: string };
type Windows = { windows: BrowserWindow[]; shown: string | null; auto: boolean; program: string | null };

const RETRY_DELAY_MS = 1000; // while the browser isn't running or the request failed
const STALE_MS = 5000; // no new frame for this long (and not minimized): the browser is busy

/** Live view of the automated browser. The program screencasts the browser in a background thread; each
 * request here waits on the server until a frame newer than the shown one exists (long polling). */
export default function LiveView({ onClose }: { onClose: () => void }) {
  const [src, setSrc] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [offline, setOffline] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [large, setLarge] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [windows, setWindows] = useState<Windows | null>(null);

  // The browser's windows / tabs (e.g. TiM ERP and ePorezi), to choose which one to watch.
  useEffect(() => {
    let stopped = false;
    const load = () =>
      callApi<Windows>("screen", "windows", {})
        .then((w) => !stopped && setWindows(w))
        .catch(() => undefined);
    load();
    const t = window.setInterval(load, 2000);
    return () => {
      stopped = true;
      clearInterval(t);
    };
  }, []);

  const show = (id: string | null) =>
    callApi<Windows>("screen", "show", { id })
      .then(setWindows)
      .catch(() => undefined);

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    let current: string | null = null;
    let version = -1;

    async function next() {
      let delay = 0;
      try {
        const res = await fetch(`/api/screen?v=${version}&t=${Date.now()}`, { cache: "no-store" });
        if (res.status === 204) return void (timer = window.setTimeout(next, 0)); // nothing new yet: ask again
        if (!res.ok) throw new Error(String(res.status));
        version = Number(res.headers.get("X-Version") ?? -1);
        const url = URL.createObjectURL(await res.blob());
        if (stopped) return URL.revokeObjectURL(url);
        await preload(url); // swap only a decoded image in, so the view never goes blank
        if (stopped) return URL.revokeObjectURL(url);
        if (current) URL.revokeObjectURL(current);
        current = url;
        setSrc(url);
        setUpdated(new Date(Number(res.headers.get("X-Taken-At")) || Date.now()));
        setOffline(false);
        setMinimized(res.headers.get("X-Minimized") === "1");
      } catch {
        if (stopped) return;
        version = -1;
        setOffline(true);
        delay = RETRY_DELAY_MS;
      }
      timer = window.setTimeout(next, delay);
    }

    next();
    return () => {
      stopped = true;
      clearTimeout(timer);
      if (current) URL.revokeObjectURL(current);
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && large && setLarge(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [large]);

  return (
    <>
      {large && <div className="live-backdrop" onClick={() => setLarge(false)} />}
      <section className={`live ${large ? "large" : ""}`} aria-label="Pretraživač uživo">
        <div className="live-head">
          <span className={`live-dot ${offline || minimized ? "off" : ""}`} />
          <span>Pretraživač uživo</span>
          <span className="live-time">
            {offline
              ? "nije pokrenut"
              : minimized
                ? `minimizovan · ${updated?.toLocaleTimeString("sr-Latn") ?? ""}`
                : updated && now - updated.getTime() > STALE_MS
                  ? `kasni · ${updated.toLocaleTimeString("sr-Latn")}`
                  : updated?.toLocaleTimeString("sr-Latn")}
          </span>
          <button onClick={() => setLarge(!large)} aria-label={large ? "Smanji" : "Uvećaj"} title={large ? "Smanji" : "Uvećaj"}>
            {large ? "⤡" : "⤢"}
          </button>
          <button onClick={onClose} aria-label="Zatvori pregled">✕</button>
        </div>
        {windows && windows.windows.length > 1 && (
          <div className="live-tabs" role="tablist" aria-label="Prozori pretraživača">
            <button
              role="tab"
              aria-selected={windows.auto}
              className={windows.auto ? "active" : ""}
              onClick={() => show(null)}
              title="Prikazuje prozor u kome program trenutno radi"
            >
              Automatski
            </button>
            {windows.windows.map((w) => (
              <button
                key={w.id}
                role="tab"
                aria-selected={!windows.auto && windows.shown === w.id}
                className={`${!windows.auto && windows.shown === w.id ? "active" : ""} ${windows.auto && windows.shown === w.id ? "shown" : ""}`}
                onClick={() => show(w.id)}
                title={w.url}
              >
                {windowName(w)}
                {windows.program === w.id && <span className="live-tab-mark" title="Program radi u ovom prozoru"> ●</span>}
              </button>
            ))}
          </div>
        )}
        <div className="live-body" onClick={() => !large && setLarge(true)}>
          {src ? <img src={src} alt="Snimak ekrana pretraživača" /> : <div className="live-empty">Učitavanje…</div>}
          {minimized && (
            <div className="live-note">
              Prozor pretraživača je minimizovan pa Chrome ne iscrtava stranicu — prikazan je poslednji snimak.
              Program i dalje radi. Vratite prozor (ne mora biti u fokusu) da bi se pregled nastavio.
            </div>
          )}
        </div>
      </section>
    </>
  );
}

function preload(url: string): Promise<void> {
  const img = new Image();
  img.src = url;
  return img.decode().catch(() => undefined);
}

/** A short name for a browser window: the site, else its title. */
function windowName(w: BrowserWindow): string {
  if (/tim-erp\.com/i.test(w.url)) return "TiM ERP";
  if (/purs\.gov\.rs/i.test(w.url)) return "ePorezi";
  if (/dexpress\.rs/i.test(w.url)) return "D Express";
  const t = w.title || w.url;
  return t.length > 24 ? `${t.slice(0, 23)}…` : t;
}
