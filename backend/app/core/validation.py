import re

USERNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,49}$")


def validate_username(username: str) -> str:
    value = username.strip()
    if not USERNAME_PATTERN.fullmatch(value):
        raise ValueError(
            "Username must be 3-50 characters, start with a letter, and contain only "
            "letters, numbers, dots, underscores, or hyphens"
        )
    return value


def validate_password(password: str, username: str | None = None) -> str:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must be between 12 and 128 characters")
    requirements = (
        any(character.islower() for character in password),
        any(character.isupper() for character in password),
        any(character.isdigit() for character in password),
        any(not character.isalnum() for character in password),
    )
    if not all(requirements):
        raise ValueError(
            "Password must include uppercase, lowercase, number, and special characters"
        )
    if username and username.casefold() in password.casefold():
        raise ValueError("Password must not contain the username")
    return password
