/**
 * Search text as compared: lower case, without diacritics (č ć → c, š → s, ž → z, đ → dj, as the
 * PB-1 form writes them), spaces collapsed. "Porez", "POREZ" and "porež" all match "porez".
 */
export function searchText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value)
    .toLowerCase()
    .replace(/đ/g, "dj")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Whether any of the texts contains the query (already passed through searchText). */
export function matches(query: string, texts: unknown[]): boolean {
  if (!query) return false;
  return texts.some((t) => {
    const text = searchText(t);
    // "dj" in a query also finds a plain "d" written without the diacritic (Djordje / Dordje).
    return text.includes(query) || (query.includes("dj") && text.includes(query.replace(/dj/g, "d")));
  });
}
