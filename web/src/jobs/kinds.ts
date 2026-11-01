import { createContext } from "react";

/** What a column holds: amounts, dates or anything else. */
export type Kind = "number" | "date" | "text";

/** Kind of each column, by task id (from the task type's known columns and the values of its last run). */
export const KindsContext = createContext<Record<string, Record<string, Kind>>>({});

const NUMBER = /^[-+]?\s*(\d{1,3}([. ]\d{3})+|\d+)([.,]\d+)?$/;
const DATE = /^(\d{1,2}[./-]\d{1,2}[./-]\d{4}\.?|\d{4}-\d{1,2}-\d{1,2})$/;

export function kindOf(text: string): Kind {
  const t = text.trim();
  return DATE.test(t) ? "date" : NUMBER.test(t) ? "number" : "text";
}

/** Kinds of the columns of a value with rows ({kolone, redovi}): a column whose non-empty cells are all numbers
 * is "number", all dates "date", else "text"; columns without values are left out. */
export function inferKinds(value: unknown): Record<string, Kind> {
  const v = value as { kolone?: string[]; redovi?: Record<string, unknown>[] } | null | undefined;
  if (!v || !Array.isArray(v.redovi)) return {};
  const columns = v.kolone?.length ? v.kolone : Object.keys(v.redovi[0] ?? {});
  const out: Record<string, Kind> = {};
  for (const c of columns) {
    const cells = v.redovi.map((r) => r?.[c]).filter((x) => x !== undefined && x !== null && String(x).trim() !== "");
    if (!cells.length) continue;
    const kinds = new Set(cells.map((x) => (typeof x === "number" ? "number" : kindOf(String(x)))));
    out[c] = kinds.size === 1 ? [...kinds][0] : "text";
  }
  return out;
}

export const KIND_WORDS: Record<Kind, string> = { number: "broj", date: "datum", text: "tekst" };

/** A warning when a value of kind `got` goes into a field that expects `expect` (number / date fields only). */
export function kindProblem(what: string, got: Kind | undefined, expect: string | undefined): string {
  if (!got || !expect || (expect !== "number" && expect !== "date") || got === expect) return "";
  return `${what} je ${KIND_WORDS[got]}, a polje očekuje ${KIND_WORDS[expect as Kind]}.`;
}
