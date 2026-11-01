"""User store. A single hard-coded test user for now; only the password hash is stored."""

USERS: dict[str, str] = {
    # username -> password hash (see app.security.hash_password)
    "nikola": "pbkdf2_sha256$600000$N8mWD88oAaOW53aiF98/KQ==$dsWte+8qkaQ+A9tyzPlx7S4zLC2tWjTX2b9e4q7oI/U=",
}

# Verified against when the username is unknown, so response time doesn't reveal which usernames exist.
DUMMY_HASH = "pbkdf2_sha256$600000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def get_password_hash(username: str) -> str | None:
    return USERS.get(username)
