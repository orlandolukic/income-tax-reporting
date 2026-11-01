from selenium.webdriver.common.by import By

from tim_automation.pages.base_page import BasePage


class HomePage(BasePage):
    """The main application page with the top menu (Registri, Finansije, ...)."""

    # Menu items call mnClk(group, item, dialog), e.g. mnClk(1,3,0) = Registri > Komitenti.
    MENU_ITEM = (By.CSS_SELECTOR, "a[href^='javascript:mnClk']")

    def is_open(self) -> bool:
        return bool(self.driver.find_elements(*self.MENU_ITEM))

    def company_label(self) -> str:
        """The open company as the site shows it at the top right, e.g. "FER VREDNOST 2026" (company
        name + year, on the button with the database icon). "" if not found."""
        return self.driver.execute_script("""
            const img = document.querySelector("img[class*='bazaicon']");
            const button = img && img.closest('button');
            return button ? button.textContent.trim() : '';
        """) or ""
