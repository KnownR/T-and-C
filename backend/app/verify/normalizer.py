"""Text normalization for deterministic citation verification."""

import re

# Characters to unify
SINGLE_QUOTES = ("‘", "’", "‚", "‛", "′", "‵", "`", "´")
DOUBLE_QUOTES = ("“", "”", "„", "‟", "″", "‶")
DASHES = ("–", "—", "−", "―", "‒")


def normalize_text(text: str) -> str:
    """Normalize text for citation verification.

    Steps:
    1. Unify single quotes and apostrophes to standard ascii single quote.
    2. Unify double quotes to standard ascii double quote.
    3. Unify dashes (en-dash, em-dash, minus, horizontal bar) to ascii hyphen.
    4. Unify non-breaking spaces and zero-width characters.
    5. Convert to lowercase.
    6. Collapse whitespace runs to a single space and strip edges.
    """
    if not text:
        return ""

    # Unify quotes
    for q in SINGLE_QUOTES:
        text = text.replace(q, "'")
    for q in DOUBLE_QUOTES:
        text = text.replace(q, '"')

    # Unify dashes and collapse spaces around dashes
    for d in DASHES:
        text = text.replace(d, "-")
    text = re.sub(r"\s*-+\s*", "-", text)

    # Replace unicode non-breaking and zero-width spaces
    text = re.sub(r"[\u00a0\u200b\u200c\u200d\ufeff]+", " ", text)

    # Convert to lowercase
    text = text.lower()

    # Collapse whitespace and strip
    text = re.sub(r"\s+", " ", text).strip()

    return text
