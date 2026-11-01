from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from tim_automation import config
from tim_automation.pages.base_page import BasePage


class LoginFailed(Exception):
    pass


class LoginPage(BasePage):
    BODY = (By.TAG_NAME, "body")
    USERNAME = (By.CSS_SELECTOR, "form[name='LOGINPAGE'] input[type='text']")
    PASSWORD = (By.CSS_SELECTOR, "form[name='LOGINPAGE'] input[type='password']")
    SUBMIT = (By.XPATH, "//form[@name='LOGINPAGE']//button[normalize-space()='Prijava']")
    ERROR = (By.XPATH, "//*[contains(normalize-space(), 'Pogrešna kombinacija')]")

    def load(self) -> "LoginPage":
        self.open(config.BASE_URL)
        self.wait.until(EC.presence_of_element_located(self.BODY))
        self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        return self

    def login(self, username: str, password: str) -> None:
        self.type(self.USERNAME, username)
        self.type(self.PASSWORD, password)
        self.click(self.SUBMIT)
        # A rejected login reloads the same page with an error message; a successful one leaves it.
        try:
            result = self.wait.until(
                lambda d: "loginPage" not in d.current_url and "ok"
                or any(e.is_displayed() for e in d.find_elements(*self.ERROR)) and "error"
            )
        except TimeoutException:
            raise LoginFailed("Server nije odgovorio na vreme.") from None
        if result == "error":
            raise LoginFailed("Pogrešno korisničko ime ili lozinka.")
