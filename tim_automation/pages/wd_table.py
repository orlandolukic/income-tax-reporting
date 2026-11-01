"""Generic reader for WebDev tables (WDTable), e.g. "I2" on Maloprodaja > Izlazi or "A3" on the company page.

A WebDev table "<ID>" renders as:
- hidden `<input name="_<ID>_OCC">`: total number of rows (after the site's filter)
- `#<ID>_TITRES_<c>`: column titles (hidden columns are not rendered; their values are empty anyway)
- `table#<ID>_TB > tbody > tr#<ID>_<r>`: only the ~10-15 rows that fit, with cells `#<ID>_<r>_<c>`
- the parent of `#<ID>_SB` is the scrollbar; scrolling it makes the site load the rows for that
  position via AJAX while `#<ID>_MASQUE` (loading overlay) is shown.
"""
import time
from collections.abc import Callable, Iterator

from selenium.webdriver.remote.webdriver import WebDriver

TABLES_JS = r"""
return [...document.querySelectorAll('input[name^="_"][name$="_OCC"]')].map((input) => {
  const id = input.name.slice(1, -4);
  const body = document.getElementById(id + '_TB');
  if (!body) return null;
  const columns = [];
  for (let c = 0; ; c++) {
    const title = document.getElementById(id + '_TITRES_' + c);
    if (!title) break;
    columns.push(title.textContent.trim());
  }
  // The caption above some tables, e.g. "STAVKE IZLAZNOG DOKUMENTA".
  const caption = document.getElementById('lz' + id);
  return {
    id, columns,
    total: parseInt(input.value, 10) || 0,
    visible: !!body.offsetParent,
    caption: caption ? caption.textContent.trim() : '',
  };
}).filter(Boolean);
"""

ROWS_JS = r"""
const id = arguments[0];
const pattern = new RegExp('^' + id + '_(\\d+)$');
return [...document.querySelectorAll('#' + id + '_TB > tbody > tr')]
  .filter((row) => pattern.test(row.id) && row.style.display !== 'none')
  .map((row) => {
    const n = row.id.match(pattern)[1];
    const cells = [];
    for (let c = 0; ; c++) {
      const cell = document.getElementById(id + '_' + n + '_' + c);
      if (!cell) break;
      cells.push(cell.innerText.trim());
    }
    return cells;
  })
  .filter((cells) => cells.some(Boolean));  // the site pads tables with empty rows
"""

LOADING_JS = "const m = document.getElementById(arguments[0] + '_MASQUE'); return !!(m && m.offsetParent);"
SCROLLER_JS = "const sb = document.getElementById(arguments[0] + '_SB'); return sb ? sb.parentElement : null;"
SCROLL_JS = ("const s = arguments[0]; s.scrollTop = arguments[1]; s.dispatchEvent(new Event('scroll'));"
             " return [s.scrollTop, s.clientHeight];")


def find_tables(driver: WebDriver) -> list[dict]:
    """All WebDev tables on the current page: {id, columns, total, visible, caption}."""
    return driver.execute_script(TABLES_JS)


def main_table(driver: WebDriver) -> "WDTable":
    """The page's main list: the first visible table that has column titles."""
    for info in find_tables(driver):
        if info["visible"] and any(info["columns"]):
            return WDTable(driver, info["id"])
    raise LookupError("Na stranici nije pronađena tabela.")


class WDTable:
    def __init__(self, driver: WebDriver, table_id: str):
        self.driver = driver
        self.id = table_id

    def info(self) -> dict:
        return next(t for t in find_tables(self.driver) if t["id"] == self.id)

    @property
    def columns(self) -> list[str]:
        return self.info()["columns"]

    @property
    def total(self) -> int:
        return self.info()["total"]

    def loading(self) -> bool:
        return self.driver.execute_script(LOADING_JS, self.id)

    def visible_rows(self) -> list[list[str]]:
        """Rows currently rendered, once the table has finished loading and stopped changing."""
        previous = None
        for _ in range(40):
            time.sleep(0.15)
            if self.loading():
                continue
            rows = self.driver.execute_script(ROWS_JS, self.id)
            if rows == previous:
                return rows
            previous = rows
        return previous or []

    def signature(self) -> tuple:
        """Changes when the table shows other data (used to notice that a search has been applied)."""
        return self.total, tuple(map(tuple, self.driver.execute_script(ROWS_JS, self.id)[:3]))

    def _pages(self) -> Iterator[list[list[str]]]:
        """Scroll from top to bottom, yielding the rendered rows at each position."""
        scroller = self.driver.execute_script(SCROLLER_JS, self.id)
        if scroller is None:
            yield self.visible_rows()
            return
        top, step = 0, None
        while True:
            actual, height = self.driver.execute_script(SCROLL_JS, scroller, top)
            yield self.visible_rows()
            if actual < top:  # could not scroll further: reached the bottom
                return
            step = step or max(height - 40, 20)
            top += step

    def read(self, limit: int = 0, attempts: int = 3,
             on_progress: Callable[[int, int], None] | None = None) -> list[dict]:
        """Rows as {column title: text}, in table order, up to `limit` rows (0 = all). Scrolling
        sometimes skips a page of rows, so if fewer rows than the table's total were read it reads
        again (up to `attempts` times). on_progress(rows read, rows expected) is called as it goes."""
        columns = self.columns
        expected = self.total if not limit else min(limit, self.total)
        best: list[tuple] = []
        for _ in range(attempts):
            rows: dict[tuple, None] = {}
            for page in self._pages():
                for row in page:
                    rows[tuple(row)] = None
                if on_progress:
                    on_progress(min(len(rows), expected), expected)
                if limit and len(rows) >= limit:
                    break
            if len(rows) > len(best):
                best = list(rows)
            if len(best) >= expected:
                break
        if limit:
            best = best[:limit]
        # Columns without a title (e.g. the selection checkbox) are left out.
        return [{c: v for c, v in zip(columns, row) if c} for row in best]
