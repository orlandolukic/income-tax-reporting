"""Store TiM ERP credentials in the OS credential store (Windows Credential Manager,
macOS Keychain, Secret Service on Linux) and re-prompt once they are older than the TTL."""
import json
import time
from dataclasses import dataclass

import keyring

from tim_automation import config
from tim_automation.ui import ask_credentials

SERVICE = "tim-erp-automation"
ENTRY = "credentials"


class CredentialsCancelled(Exception):
    pass


@dataclass
class Credentials:
    username: str
    password: str
    saved_at: float

    @property
    def expired(self) -> bool:
        return time.time() - self.saved_at > config.CREDENTIALS_TTL_HOURS * 3600


def load() -> Credentials | None:
    raw = keyring.get_password(SERVICE, ENTRY)
    if not raw:
        return None
    try:
        return Credentials(**json.loads(raw))
    except (ValueError, TypeError):
        return None


def save(username: str, password: str) -> Credentials:
    creds = Credentials(username, password, time.time())
    keyring.set_password(SERVICE, ENTRY, json.dumps(creds.__dict__))
    return creds


def forget() -> None:
    try:
        keyring.delete_password(SERVICE, ENTRY)
    except keyring.errors.PasswordDeleteError:
        pass


def prompt(default_username: str = "", message: str = "") -> Credentials:
    entered = ask_credentials(default_username, message)
    if entered is None:
        raise CredentialsCancelled()
    return save(*entered)


def get() -> Credentials:
    """Return stored credentials, asking for new ones if missing or expired."""
    creds = load()
    if creds and not creds.expired:
        return creds
    message = ""
    if creds:
        message = f"Sačuvani podaci su stariji od {config.CREDENTIALS_TTL_HOURS:g}h. Unesite ih ponovo."
    return prompt(creds.username if creds else "", message)
