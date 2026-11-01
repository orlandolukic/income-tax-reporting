import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { callApi, ReportsState, ReportTypeInfo } from "../api";
import { Check } from "../controls";

type Values = Record<string, string | boolean>;

/** "⚙": the report's settings for the open company (saved by the program, checked there too). */
export function SettingsButton({ state, type, disabled }: { state: ReportsState; type: ReportTypeInfo; disabled?: string }) {
  const [open, setOpen] = useState(false);
  if (!type.settings.length) return null;
  return (
    <>
      <button
        className="icon-button"
        title={disabled || "Podešavanja izveštaja"}
        aria-label="Podešavanja izveštaja"
        disabled={!!disabled || !state.company}
        onClick={() => setOpen(true)}
      >
        ⚙
      </button>
      {open && <SettingsDialog state={state} type={type} onClose={() => setOpen(false)} />}
    </>
  );
}

function SettingsDialog({ state, type, onClose }: { state: ReportsState; type: ReportTypeInfo; onClose: () => void }) {
  const defaults: Values = Object.fromEntries(type.settings.map((s) => [s.name, s.default]));
  const [values, setValues] = useState<Values>({ ...defaults, ...(state.settings[type.id] ?? {}) });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const changed = type.settings.some((s) => values[s.name] !== defaults[s.name]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, select")?.focus();
    document.body.classList.add("modal-open");
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.classList.remove("modal-open");
    };
  }, []);

  async function save() {
    setError("");
    setSaving(true);
    try {
      await callApi("reports", "settings", { report: type.id, company: state.company?.key, values });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return createPortal(
    <div ref={ref} className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form
        className="modal settings-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Podešavanja izveštaja"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <div className="modal-head">
          <strong className="settings-title">Podešavanja · {type.title}</strong>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Zatvori">
            ✕
          </button>
        </div>
        <div className="modal-body settings-body">
          {state.company && <p className="muted small">Važe za firmu {state.company.label}.</p>}
          {type.settings.map((s) => {
            const value = values[s.name];
            const isDefault = value === defaults[s.name];
            const set = (v: string | boolean) => setValues((old) => ({ ...old, [s.name]: v }));
            return (
              <div key={s.name} className="settings-field">
                {s.kind === "bool" ? (
                  <Check checked={value === true} onChange={set}>
                    {s.label}
                  </Check>
                ) : (
                  <label>
                    <span className="settings-label">{s.label}</span>
                    {s.kind === "select" ? (
                      <select value={String(value)} onChange={(e) => set(e.target.value)}>
                        {s.options.map((o) => (
                          <option key={o}>{o}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        inputMode={s.kind === "number" ? "decimal" : undefined}
                        className={s.kind === "number" ? "number-input" : undefined}
                        value={String(value)}
                        onChange={(e) => set(e.target.value)}
                      />
                    )}
                  </label>
                )}
                <div className="muted small">
                  {s.help}
                  {!isDefault && (
                    <>
                      {s.help && " "}
                      <button type="button" className="link-button" onClick={() => set(defaults[s.name])}>
                        Podrazumevano: {defaults[s.name] === true ? "da" : defaults[s.name] === false ? "ne" : String(defaults[s.name])}
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
          {error && <p className="error">{error}</p>}
        </div>
        <div className="modal-foot">
          <button type="button" disabled={!changed} onClick={() => setValues(defaults)}>
            Vrati sve na podrazumevano
          </button>
          <span className="buttons">
            <button type="button" onClick={onClose}>
              Otkaži
            </button>
            <button type="submit" className="primary" disabled={saving}>
              Sačuvaj
            </button>
          </span>
        </div>
      </form>
    </div>,
    document.body,
  );
}

/** One line with the settings a result was made with (or the current ones), e.g. "Konta 6–65 · bez 6050 · …". */
export function settingsSummary(type: ReportTypeInfo, values: Values | undefined): string {
  if (!values) return "";
  return type.settings
    .map((s) => {
      const v = values[s.name];
      if (s.kind === "bool") return v ? s.label : `${s.label}: ne`;
      return `${s.label}: ${v === "" ? "—" : v}`;
    })
    .join(" · ");
}
