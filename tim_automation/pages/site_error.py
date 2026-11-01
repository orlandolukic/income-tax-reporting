"""TiM ERP's own error message "Došlo je do nepredviđene greške": once the site shows it, the session is broken
and the only fix is a new browser and logging in again (main.py restarts it, the runner then runs the job again)."""
from selenium.common.exceptions import WebDriverException

MESSAGE = "Došlo je do nepredviđene greške"

# Text of the page and of its same-origin iframes (popups like "Fiskalni računi" are iframes), lower case,
# without diacritics; "đ" is written "dj" or "d", so both become "d".
_FIND_JS = """
const texts = [];
const add = (doc) => {
  try {
    if (doc && doc.body) texts.push(doc.body.innerText || "");
    for (const f of doc.querySelectorAll("iframe, frame")) add(f.contentDocument);
  } catch (e) { /* another origin */ }
};
add(document);
const norm = (t) => t.toLowerCase().replace(/đ/g, "d").replace(/dj/g, "d").normalize("NFD").replace(/[\\u0300-\\u036f]/g, "");
return texts.some((t) => norm(t).includes("nepredvidene greske"));
"""


class SiteError(Exception):
    """The site showed "Došlo je do nepredviđene greške"."""

    def __init__(self) -> None:
        super().__init__(f"Sajt je prijavio grešku: „{MESSAGE}“.")


def shown(driver) -> bool:
    """Whether the site's error message is on the page (False if the browser can't be asked)."""
    if driver is None:
        return False
    try:
        return bool(driver.execute_script(_FIND_JS))
    except WebDriverException:
        return False
