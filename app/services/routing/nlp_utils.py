import re

# Slovenian stop words - ignore these in loop detection
STOP_WORDS = {
    "je", "in", "za", "na", "se", "so", "ali", "kako", "kdaj", "kje", "kaj", "katere",
    "kateri", "kakšen", "kakšna", "ima", "imate", "imajo", "bi", "bo", "bom", "boste",
    "ste", "sem", "smo", "si", "lahko", "tudi", "mi", "te", "me", "ga", "jo", "jim",
    "iz", "do", "pri", "od", "po", "ta", "te", "to", "ta", "ti", "teh", "tem",
    "a", "ali", "ampak", "vendar", "ker", "če", "ko", "da", "ki"
}

# Affirmative keywords
AFFIRMATIVE_KEYWORDS = {
    "da", "ja", "yes", "seveda", "lahko", "ok", "okay",
    "v redu", "sure", "dobro", "prosim", "please", "grem naprej", "nadaljuj",
    "ajde", "idemo", "idem", "gremo", "dejmo", "idemooo"
}

# Greeting keywords
GREETING_KEYWORDS = {"pozdrav", "zdravo", "hej", "hello", "hi", "dober dan", "živjo"}


def tokenize_meaningful(message: str) -> set[str]:
    """Extract meaningful tokens (remove stop words and punctuation)."""
    cleaned = re.sub(r"[^\w\s]", "", message.lower())
    tokens = cleaned.split()
    return {t for t in tokens if len(t) > 2 and t not in STOP_WORDS}


def is_affirmative(message: str) -> bool:
    """Check if message is an affirmative response."""
    lowered = message.lower().strip()
    if lowered.startswith(("ajde", "idemo", "idem", "gremo", "dejmo")):
        return True
    tokens = lowered.split()
    if len(tokens) <= 2:
        return any(word in AFFIRMATIVE_KEYWORDS for word in tokens)
    return False


def is_negative(message: str) -> bool:
    """Check if message is a negative response."""
    tokens = message.lower().strip().split()
    if len(tokens) <= 3:
        return any(
            word in {"ne", "no", "ne hvala", "preklic", "prekliči", "preklici", "stop", "ne bom"}
            for word in tokens
        ) or message.lower().strip().startswith("ne ")
    return False


def is_greeting(message: str) -> bool:
    """Check if message is a greeting."""
    lowered = message.lower()
    return any(greet in lowered for greet in GREETING_KEYWORDS)
