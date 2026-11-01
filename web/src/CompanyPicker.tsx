import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { answer, Company, Prompt, request } from "./api";

/** Lowercase and strip diacritics, so "sabac" matches "Šabac". */
function normalize(text: string, dj = "dj"): string {
  return text.toLowerCase().replaceAll("đ", dj).normalize("NFKD").replace(/\p{M}/gu, "");
}

// Index "đ" both as "dj" and "d", so "djurdjevic" and "durdevic" both find "Đurđević".
function searchable(c: Company): string {
  const text = `${c.name} ${c.pib}`;
  return `${normalize(text)} ${normalize(text, "d")}`;
}

function formatDate(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString("sr-Latn", { dateStyle: "short", timeStyle: "short" });
}

type Filter = "all" | "active" | "inactive";

const FILTERS: [Filter, string][] = [
  ["all", "Sve firme"],
  ["active", "Aktivne"],
  ["inactive", "Neaktivne"],
];

const MOVES: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, PageDown: 10, PageUp: -10 };

export default function CompanyPicker({ prompt }: { prompt: Extract<Prompt, { kind: "company" }> }) {
  const { companies, years, savedAt } = prompt.data;
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("active");
  const [year, setYear] = useState(prompt.data.year);
  const [selected, setSelected] = useState(prompt.data.selected);
  const [pending, setPending] = useState<number | null>(null);
  const openAfterCheck = useRef(false);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const yearRef = useRef<HTMLSelectElement>(null);

  const index = useMemo(() => companies.map(searchable), [companies]);
  const shown = useMemo(() => {
    const words = normalize(query).split(/\s+/).filter(Boolean);
    return companies
      .map((_, i) => i)
      .filter((i) => filter === "all" || companies[i].active === (filter === "active"))
      .filter((i) => words.every((w) => index[i].includes(w)));
  }, [companies, index, query, filter]);

  const counts = useMemo(() => {
    const active = companies.filter((c) => c.active).length;
    return { all: companies.length, active, inactive: companies.length - active };
  }, [companies]);

  // Keep a visible row selected while filtering.
  const current = shown.includes(selected) ? selected : (shown[0] ?? -1);

  useEffect(() => {
    bodyRef.current?.querySelector(".selected")?.scrollIntoView({ block: "nearest" });
  }, [current]);

  // Not every company has every year: the year list shows the years confirmed in the browser for the
  // selected company, or the initial list until it has been checked.
  const check = prompt.data.checked[String(current)];
  const yearOptions = check ? check.years : years;
  const shownYear = yearOptions.includes(year) ? year : check?.year || yearOptions[0] || "";
  const checking = pending !== null;
  // Each company's years are checked once; after that they come from the cache until "Osveži listu".
  const needsCheck = !check;

  function checkYears(open: boolean) {
    if (current < 0 || !needsCheck || checking) return;
    setPending(current);
    openAfterCheck.current = open;
    request(prompt.id, { type: "years", index: current });
  }

  function changeYear(value: string) {
    setYear(value);
    request(prompt.id, { type: "year", index: current, year: value });
  }

  // When the check arrives: keep the browser on the year shown here, and open the list that was clicked.
  useEffect(() => {
    if (pending === null || prompt.data.inBrowser !== pending || !prompt.data.checked[String(pending)]) return;
    setPending(null);
    if (pending !== current || !check) return;
    if (shownYear && shownYear !== check.year) request(prompt.id, { type: "year", index: current, year: shownYear });
    if (openAfterCheck.current && yearRef.current) {
      yearRef.current.focus();
      try {
        yearRef.current.showPicker();
      } catch {
        // needs a recent click; otherwise the list is just focused
      }
    }
  }, [check, pending, current, shownYear, prompt.id, prompt.data]);

  function choose(i = current) {
    if (i < 0) return;
    const c = prompt.data.checked[String(i)];
    const options = c ? c.years : years;
    answer(prompt.id, { index: i, year: options.includes(year) ? year : c?.year || options[0] || "" });
  }

  function onKey(e: KeyboardEvent) {
    const move = MOVES[e.key];
    if (move && shown.length && !(e.target instanceof HTMLSelectElement)) {
      e.preventDefault();
      const pos = shown.indexOf(current);
      setSelected(shown[Math.max(0, Math.min(pos + move, shown.length - 1))]);
    } else if (e.key === "Enter" && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault();
      choose();
    } else if (e.key === "Escape") {
      answer(prompt.id, null);
    }
  }

  return (
    <div className="card picker" onKeyDown={onKey}>
      <div className="picker-head">
        <h2>Izbor firme</h2>
        <span className="muted">{savedAt && `Lista učitana ${formatDate(savedAt)}`}</span>
        <button onClick={() => answer(prompt.id, { refresh: true })} title="Ponovo pročitaj listu firmi sa sajta">
          ↻ Osveži listu
        </button>
      </div>
      {prompt.data.message && <p className="warning">{prompt.data.message}</p>}
      <div className="segmented" role="radiogroup" aria-label="Prikaz firmi">
        {FILTERS.map(([value, label]) => (
          <button
            key={value}
            role="radio"
            aria-checked={filter === value}
            className={filter === value ? "on" : ""}
            onClick={() => setFilter(value)}
          >
            {label} <span className="count">{counts[value]}</span>
          </button>
        ))}
      </div>
      <input
        className="search"
        placeholder="Pretraga po nazivu ili PIB-u"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        autoFocus
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Naziv firme</th>
              <th className="pib">PIB</th>
            </tr>
          </thead>
          <tbody ref={bodyRef}>
            {shown.map((i) => (
              <tr
                key={i}
                className={`${i === current ? "selected" : ""} ${companies[i].active ? "" : "inactive"}`}
                onClick={() => setSelected(i)}
                onDoubleClick={() => choose(i)}
              >
                <td>
                  {companies[i].name}
                  {!companies[i].active && <span className="badge">neaktivna</span>}
                </td>
                <td className="pib">{companies[i].pib}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="buttons spread">
        <span className="muted">
          {shown.length} od {counts[filter]} firmi
        </span>
        <span className="buttons">
          {check?.error && <span className="error">{check.error}</span>}
          {checking && (
            <span className="muted checking">
              <span className="spinner" /> Provera godina…
            </span>
          )}
          {(years.length > 0 || check) && (
            <label className="inline">
              Godina:
              <select
                ref={yearRef}
                value={shownYear}
                disabled={checking || (check && !check.years.length)}
                title={check ? "Godine ove firme (sačuvane do osvežavanja liste)" : "Kliknite da proverite godine ove firme"}
                onMouseDown={(e) => {
                  if (needsCheck) {
                    e.preventDefault();
                    checkYears(true);
                  }
                }}
                onFocus={() => checkYears(false)}
                onChange={(e) => changeYear(e.target.value)}
              >
                {yearOptions.map((y) => (
                  <option key={y}>{y}</option>
                ))}
              </select>
            </label>
          )}
          <button className="primary" disabled={current < 0} onClick={() => choose()}>Izaberi</button>
          <button onClick={() => answer(prompt.id, null)}>Otkaži</button>
        </span>
      </div>
    </div>
  );
}
