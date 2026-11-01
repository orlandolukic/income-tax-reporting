"""Params of kind "secret" (e.g. a card PIN): kept in the OS credential store (Windows Credential Manager), never in
data/jobs.json or in a run's results.

In a job a secret param's value is {"secret": "<id>"}; the page sends {"secret": "<old id or ''>", "value": "1234"}
when the user types a new one, and `stash` (on save) stores it under a new id. A duplicated task keeps the id, so the
copy uses the same secret until one of them gets a new value."""
import uuid

import keyring
import keyring.errors

SERVICE = "tim-erp-automation"
MASK = "••••"


def _entry(secret_id: str) -> str:
    return f"secret:{secret_id}"


def stash(value):
    """The value to store in the job for what the page sent: a new secret goes to the credential store."""
    if not isinstance(value, dict) or "secret" not in value:
        return value
    if "value" not in value:  # unchanged
        return {"secret": str(value["secret"] or "")} if value["secret"] else ""
    new = str(value["value"] or "")
    if not new:
        return ""
    secret_id = uuid.uuid4().hex[:16]
    keyring.set_password(SERVICE, _entry(secret_id), new)
    return {"secret": secret_id}


def is_secret(value) -> bool:
    return isinstance(value, dict) and "secret" in value


def reveal(value, label: str) -> str:
    """The stored secret for a job's value."""
    secret_id = value.get("secret") if isinstance(value, dict) else ""
    stored = keyring.get_password(SERVICE, _entry(secret_id)) if secret_id else None
    if stored is None:
        raise ValueError(f"„{label}“ nije sačuvan na ovom računaru: upišite ga ponovo i sačuvajte posao.")
    return stored


def ids(value) -> set[str]:
    """Ids of the secrets anywhere in a job (or any JSON value)."""
    if isinstance(value, dict):
        found = {value["secret"]} if isinstance(value.get("secret"), str) and value["secret"] else set()
        return found.union(*(ids(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(ids(v) for v in value))
    return set()


def forget(secret_ids: set[str], still_used: set[str]) -> None:
    """Remove secrets no job uses any more (replaced or deleted) from the credential store."""
    for secret_id in secret_ids - still_used:
        try:
            keyring.delete_password(SERVICE, _entry(secret_id))
        except keyring.errors.PasswordDeleteError:
            pass
