from __future__ import annotations


def preferred_language(header: str | None) -> str:
    if not header:
        return "en"
    choices: list[tuple[float, str]] = []
    for item in header.split(","):
        locale, *parameters = item.strip().split(";")
        locale = locale.strip().lower().replace("_", "-")
        language = (
            "sw"
            if locale.startswith("sw")
            else "en"
            if locale.startswith("en")
            else None
        )
        if language is None:
            continue
        quality = 1.0
        for parameter in parameters:
            key, separator, value = parameter.strip().partition("=")
            if separator and key == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
                if not 0.0 <= quality <= 1.0:
                    quality = 0.0
        if quality > 0.0:
            choices.append((quality, language))
    return max(choices, key=lambda choice: choice[0])[1] if choices else "en"
