from __future__ import annotations

import re

# Central place for high-value typo/slang normalization before routing.
# Keep this conservative: only map tokens we are confident about.
TOKEN_REPLACEMENTS: dict[str, str] = {
    # greetings
    "zdwavo": "zdravo",
    "zdravjo": "zdravo",
    # services
    "dermatologo": "dermatolog",
    "dermatalog": "dermatolog",
    "dermatlog": "dermatolog",
    "ortopet": "ortoped",
    "ortopd": "ortoped",
    "okulsit": "okulist",
    "botoc": "botox",
    "filer": "filler",
    "filerrr": "filler",
    # common chat slang
    "kolk": "koliko",
    "kolko": "koliko",
    "kksn": "kaksen",
    "kaksn": "kaksen",
    "napotnco": "napotnico",
}

# Phrase-level replacements first (before tokenization), to preserve intent wording.
PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("a lohk", "ali lahko"),
    ("bi lohk", "bi lahko"),
    ("lohk", "lahko"),
    ("mate ", "imate "),
)


def normalize_user_message(message: str) -> str:
    text = (message or "").strip()
    if not text:
        return text

    lowered = text.lower()
    for src, dst in PHRASE_REPLACEMENTS:
        lowered = lowered.replace(src, dst)

    # Replace whole-word tokens only.
    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return TOKEN_REPLACEMENTS.get(token, token)

    normalized = re.sub(r"\b[\wčšžćđ]+\b", _replace, lowered, flags=re.IGNORECASE)
    # Collapse repeated whitespace introduced by phrase replacements.
    normalized = " ".join(normalized.split())
    return normalized

