import * as Checkbox from "@radix-ui/react-checkbox";
import { ReactNode, useEffect, useState } from "react";
import Select from "react-select";
import CreatableSelect from "react-select/creatable";

/** Checkbox (Radix UI) with its label; Space / click toggles it, like a native one. */
export function Check(props: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children?: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <label className={`check-field ${props.className ?? ""}`} title={props.title}>
      <Checkbox.Root className="check-box" checked={props.checked} onCheckedChange={(c) => props.onChange(c === true)}>
        <Checkbox.Indicator className="check-mark">
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden>
            <path d="M3 8.5l3.2 3L13 4.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Checkbox.Indicator>
      </Checkbox.Root>
      {props.children !== undefined && <span className="check-label">{props.children}</span>}
    </label>
  );
}

type Option = { value: string; label: string };

/** Searchable dropdown of known names (e.g. columns or totals: Virman, Gotovina, …) that also accepts a typed
 * name that isn't in the list (react-select, Creatable). With `strict` only the listed names can be chosen (a saved
 * value that isn't among them is shown as missing). The menu is drawn over the page so windows don't cut it. */
export function NameSelect(props: {
  value: string;
  options: string[];
  placeholder?: string;
  onChange: (value: string) => void;
  ariaLabel?: string;
  strict?: boolean;
}) {
  const options: Option[] = props.options.map((o) => ({ value: o, label: o }));
  const missing = props.strict ? `${props.value} (ne postoji)` : props.value;
  const selected = props.value ? (options.find((o) => o.value === props.value) ?? { value: props.value, label: missing }) : null;
  const Component = (props.strict ? Select : CreatableSelect) as typeof CreatableSelect;
  return (
    // Inside a <label> (e.g. a param's field) a click would also go to the label's first control and take the
    // focus away, closing the menu at once.
    <span className="name-select-wrap" onClick={(e) => e.preventDefault()}>
    <Component<Option, false>
      className={`name-select${props.strict && props.value && !props.options.includes(props.value) ? " is-missing" : ""}`}
      classNamePrefix="ns"
      aria-label={props.ariaLabel}
      value={selected}
      options={options}
      placeholder={props.placeholder ?? "Izaberite…"}
      isClearable
      onChange={(o) => props.onChange(o?.value ?? "")}
      formatCreateLabel={(text) => `Koristi „${text}“`}
      noOptionsMessage={() => (props.strict ? "Nema takve kolone" : "Nema ponuđenih — upišite naziv")}
      menuPortalTarget={document.body}
      menuPlacement="auto"
      styles={{
        control: (base, state) => ({
          ...base,
          minHeight: 32,
          minWidth: 170,
          borderRadius: 6,
          borderColor: state.isFocused ? "var(--accent)" : "var(--border)",
          boxShadow: state.isFocused ? "0 0 0 2px var(--selected)" : "none",
          background: "var(--card)",
          "&:hover": { borderColor: "var(--accent)" },
        }),
        valueContainer: (base) => ({ ...base, padding: "0 8px" }),
        singleValue: (base) => ({ ...base, color: "var(--text)", fontWeight: 600 }),
        input: (base) => ({ ...base, margin: 0, color: "var(--text)" }),
        placeholder: (base) => ({ ...base, color: "var(--muted)" }),
        indicatorSeparator: () => ({ display: "none" }),
        dropdownIndicator: (base) => ({ ...base, padding: 4 }),
        clearIndicator: (base) => ({ ...base, padding: 4 }),
        menuPortal: (base) => ({ ...base, zIndex: 1000 }),
        menu: (base) => ({ ...base, borderRadius: 8, overflow: "hidden", background: "var(--card)", boxShadow: "0 8px 24px rgba(0,0,0,.15)" }),
        option: (base, state) => ({
          ...base,
          cursor: "pointer",
          color: state.isSelected ? "var(--accent-text)" : "var(--text)",
          background: state.isSelected ? "var(--accent)" : state.isFocused ? "var(--selected)" : "transparent",
        }),
      }}
    />
    </span>
  );
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Older browsers / no permission: copy through a hidden text field.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <button
      type="button"
      className={`copy-button ${copied ? "copied" : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        copyText(text).then(() => setCopied(true));
      }}
      title="Kopiraj"
    >
      {copied ? "✓ Kopirano" : "Kopiraj"}
    </button>
  );
}

/** A value shown as formatted JSON (or text), with a Copy button in its corner. */
export function CodeBlock({ value, className }: { value: unknown; className?: string }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="code-block">
      <CopyButton text={text} />
      <pre className={className}>{text}</pre>
    </div>
  );
}

/** The text of a date field as the user types or pastes, shown as DD/MM/YYYY: digits fill the day, month and
 * year; a separator (".", "/", "-", space) after a one-digit day or month pads it ("1.9.2026" → "01/09/2026"). */
export function maskDate(text: string): string {
  const ymd = /^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$/.exec(text);
  if (ymd) return `${ymd[3].padStart(2, "0")}/${ymd[2].padStart(2, "0")}/${ymd[1]}`;
  const parts = ["", "", ""];
  let i = 0;
  for (const ch of text) {
    if (/\d/.test(ch)) {
      if (i < 2 && parts[i].length === 2) i++;
      if (parts[i].length === (i === 2 ? 4 : 2)) break;
      parts[i] += ch;
    } else if (/[./\- ]/.test(ch) && i < 2 && parts[i].length > 0) {
      parts[i] = parts[i].padStart(2, "0");
      i++;
    }
  }
  return parts.slice(0, i + 1).join("/");
}

/** Why a DD/MM/YYYY date is not valid ("" if it is, or if it is empty). */
export function dateProblem(text: string): string {
  if (!text) return "";
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text);
  if (!m) return "Datum u obliku DD/MM/GGGG.";
  const [d, mo, y] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const real = new Date(y, mo - 1, d);
  return real.getFullYear() === y && real.getMonth() === mo - 1 && real.getDate() === d ? "" : "Taj datum ne postoji.";
}

/** What a date field shows behind the typed digits: the rest of the mask stays visible while typing. */
const DATE_MASK = "dd/MM/YYYY";

/** Date field with the program's input mask: DD/MM/YYYY, "/" as the separator. The mask is always shown: the part
 * not typed yet stays in grey behind the text ("15/1" shows as 15/1M/YYYY). */
export function DateInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const problem = dateProblem(value);
  return (
    <span className="date-input">
      <span className="date-mask">
        <span className="date-mask-ghost" aria-hidden>
          <span className="date-mask-typed">{value}</span>
          {DATE_MASK.slice(value.length)}
        </span>
        <input
          value={value}
          inputMode="numeric"
          aria-label={`Datum (${DATE_MASK})`}
          maxLength={10}
          onChange={(e) => onChange(maskDate(e.target.value))}
          aria-invalid={!!problem}
        />
      </span>
      {problem && value.length === 10 && <span className="error small">{problem}</span>}
    </span>
  );
}
