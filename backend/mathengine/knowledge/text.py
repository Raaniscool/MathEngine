"""Text normalization shared by the index builder (writes terms) and the retriever (reads terms).

Both sides MUST use the same functions, otherwise a search for "fractions" would never find
a record whose title says "Fraction". Keep this module small and deterministic.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Words that carry no topic meaning in a search ("the", "of", "is" ...).
STOPWORDS = frozenset(
    {
        "a", "about", "am", "an", "and", "any", "are", "as", "at", "be", "by", "can", "dont", "do",
        "does", "for", "from", "get", "how", "i", "if", "im", "in", "into", "is", "it", "its", "ive",
        "let", "lets", "me", "my", "no", "not", "of", "on", "or", "our", "so", "some", "t", "than",
        "that", "the", "this", "to", "was", "we", "what", "when", "where", "which", "who", "why",
        "with", "you", "your", "s",
    }
)

# Words that describe what the user wants to do, not what they want to learn about.
# "Teach me fractions" should search for "fractions" only.
INTENT_WORDS = frozenset(
    {
        "answer", "check", "describe", "define", "example", "examples", "explain", "exercise",
        "exercises", "find", "give", "help", "learn", "lesson", "lessons", "need", "please",
        "practice", "problem", "problems", "question", "questions", "show", "tell", "teach",
        "understand", "understanding", "want", "wrong",
    }
)


def normalize(text: str) -> str:
    """Lowercase, drop apostrophes, and turn every other non-alphanumeric run into one space."""
    lowered = text.lower().replace("'", "").replace("\u2019", "")
    return _NON_ALNUM.sub(" ", lowered).strip()


def stem(word: str) -> str:
    """A deliberately simple plural stemmer: 'fractions' -> 'fraction', 'laws' -> 'law'.

    Words ending in 'ss', 'us' or 'is' are left alone ('process', 'calculus', 'analysis').
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    """Meaningful search/index terms from free text, in order (may contain duplicates)."""
    result: list[str] = []
    for raw in normalize(text).split():
        if len(raw) < 2 or raw in STOPWORDS or raw in INTENT_WORDS:
            continue
        term = stem(raw)
        if term in STOPWORDS or term in INTENT_WORDS:
            continue
        result.append(term)
    return result


def phrase_key(text: str) -> str:
    """Stemmed, normalized form of a whole phrase, used for exact title/alias matches.

    Keeps stopwords on purpose: "solve for x" and "solve for x" must match exactly.
    """
    return " ".join(stem(word) for word in normalize(text).split())
