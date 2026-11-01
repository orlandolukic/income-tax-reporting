// Excel-like display of numbers using the cell's Excel number format.
//
// Supported: "General", numeric patterns ("0", "#,##0", "#,##0.00", ...), up to four
// sections (positive;negative;zero;text), [Color] codes ([Red] negatives are flagged),
// literals (\x, "text", ( ) - etc.), "_x" padding, "%" and "@". Date/time formats are not
// rendered as dates yet; such numbers fall back to General.

// Separators of the Serbian locale, as Excel shows them on a Serbian Windows.
export const THOUSANDS_SEPARATOR = ".";
export const DECIMAL_SEPARATOR = ",";

export type FormattedNumber = { text: string; red: boolean };

const NUMBER_PLACEHOLDERS = /[0#?,.]/;
const DATE_TOKENS = /[dmyhs]/i;

function splitSections(format: string): string[] {
  const sections: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < format.length; i++) {
    const ch = format[i];
    if (ch === '"') inQuotes = !inQuotes;
    if (ch === "\\" && !inQuotes) {
      current += ch + (format[i + 1] ?? "");
      i++;
      continue;
    }
    if (ch === ";" && !inQuotes) {
      sections.push(current);
      current = "";
      continue;
    }
    current += ch;
  }
  sections.push(current);
  return sections;
}

function withSeparators(integerDigits: string, grouped: boolean): string {
  if (!grouped) return integerDigits;
  return integerDigits.replace(/\B(?=(\d{3})+(?!\d))/g, THOUSANDS_SEPARATOR);
}

/** Formats a non-negative number with a placeholder pattern such as "#,##0.00". */
function formatDigits(value: number, pattern: string): string {
  const [intPattern, decPattern = ""] = pattern.split(".");
  const maxDecimals = (decPattern.match(/[0#?]/g) ?? []).length;
  const minDecimals = (decPattern.match(/0/g) ?? []).length;
  const minIntegerDigits = (intPattern.match(/0/g) ?? []).length;
  const grouped = intPattern.includes(",");

  let [intPart, decPart = ""] = value.toFixed(maxDecimals).split(".");
  // Optional decimal places ("#") drop trailing zeros.
  while (decPart.length > minDecimals && decPart.endsWith("0")) decPart = decPart.slice(0, -1);
  if (intPart === "0" && minIntegerDigits === 0) intPart = "";
  intPart = intPart.padStart(minIntegerDigits, "0");

  const integer = withSeparators(intPart, grouped);
  return decPart ? `${integer}${DECIMAL_SEPARATOR}${decPart}` : integer;
}

/** Excel "General": integers as-is, otherwise up to 10 significant digits. */
export function formatGeneral(value: number): string {
  const abs = Math.abs(value);
  if (Number.isInteger(value) && abs < 1e11) return String(value);
  if (abs !== 0 && (abs >= 1e11 || abs < 1e-4)) {
    const [mantissa, exponent] = value.toExponential(4).split("e");
    const exp = Number(exponent);
    const trimmed = String(Number(mantissa)).replace(".", DECIMAL_SEPARATOR);
    return `${trimmed}E${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  return String(Number(value.toPrecision(10))).replace(".", DECIMAL_SEPARATOR);
}

function renderSection(value: number, section: string): string {
  let out = "";
  let digitsRendered = false;
  const percent = section.includes("%") && !/"[^"]*%[^"]*"/.test(section);
  const scaled = percent ? value * 100 : value;

  for (let i = 0; i < section.length; i++) {
    const ch = section[i];
    if (ch === "\\") {
      out += section[i + 1] ?? "";
      i++;
    } else if (ch === '"') {
      const end = section.indexOf('"', i + 1);
      out += section.slice(i + 1, end === -1 ? undefined : end);
      i = end === -1 ? section.length : end;
    } else if (ch === "_" || ch === "*") {
      // "_x" pads with the width of x, "*x" repeats x to fill: skip both.
      i++;
    } else if (ch === "[") {
      const end = section.indexOf("]", i);
      i = end === -1 ? section.length : end;
    } else if (NUMBER_PLACEHOLDERS.test(ch)) {
      let j = i;
      while (j < section.length && NUMBER_PLACEHOLDERS.test(section[j])) j++;
      if (!digitsRendered) out += formatDigits(Math.abs(scaled), section.slice(i, j));
      digitsRendered = true;
      i = j - 1;
    } else if (ch === "@") {
      out += formatGeneral(value);
    } else {
      out += ch;
    }
  }
  return out;
}

export function formatNumber(value: number, format: string | null | undefined): FormattedNumber {
  if (!format || format === "General" || format === "@") {
    return { text: formatGeneral(value), red: false };
  }
  const sections = splitSections(format);
  let section = sections[0];
  let addMinus = value < 0;
  if (value < 0 && sections.length > 1) {
    section = sections[1]; // negative section carries its own sign or parentheses
    addMinus = false;
  } else if (value === 0 && sections.length > 2) {
    section = sections[2];
  }

  const unquoted = section.replace(/"[^"]*"|\\./g, "").replace(/\[[^\]]*\]/g, "");
  if (!/[0#?]/.test(unquoted) || DATE_TOKENS.test(unquoted)) {
    // Date/time or text-only formats: not supported yet.
    return { text: formatGeneral(value), red: false };
  }

  const text = renderSection(value, section).trim();
  return { text: addMinus ? `-${text}` : text, red: /\[red\]/i.test(section) };
}

/** Value shown in the cell editor: plain number with the locale decimal separator. */
export function toEditText(value: number | null): string {
  return value === null ? "" : String(value).replace(".", DECIMAL_SEPARATOR);
}

/**
 * Parses user input into a number. Returns null for empty input (clear the cell) and
 * undefined when the input is not a valid number. Accepts "1234,56", "1.234,56" and
 * "1234.56"; a "." followed by groups of exactly three digits is a thousands separator.
 */
export function parseNumberInput(input: string): number | null | undefined {
  let s = input.trim().replace(/\s/g, "");
  if (s === "") return null;
  if (s.includes(",") && s.includes(".")) {
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (s.includes(",")) {
    s = s.replace(",", ".");
  } else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) {
    s = s.replace(/\./g, "");
  }
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(s)) return undefined;
  const value = Number(s);
  return Number.isFinite(value) ? value : undefined;
}
