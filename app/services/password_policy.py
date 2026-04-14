from __future__ import annotations

PASSWORD_MIN_LENGTH = 12
PASSWORD_POLICY_SUMMARY = (
    "12+ caracteres, com letra maiuscula, minuscula, numero e simbolo"
)


def _join_requirements(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} e {items[1]}"
    return f"{', '.join(items[:-1])} e {items[-1]}"


def password_validation_error(password: str) -> str | None:
    normalized = str(password or "")
    requirements: list[str] = []

    if len(normalized) < PASSWORD_MIN_LENGTH:
        requirements.append(f"pelo menos {PASSWORD_MIN_LENGTH} caracteres")
    if not any(character.islower() for character in normalized):
        requirements.append("uma letra minuscula")
    if not any(character.isupper() for character in normalized):
        requirements.append("uma letra maiuscula")
    if not any(character.isdigit() for character in normalized):
        requirements.append("um numero")
    if not any((not character.isalnum()) and (not character.isspace()) for character in normalized):
        requirements.append("um simbolo")

    if not requirements:
        return None
    return f"A senha precisa ter {_join_requirements(requirements)}."
