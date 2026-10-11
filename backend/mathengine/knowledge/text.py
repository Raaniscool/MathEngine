"""Text normalization shared by the index builder (writes terms) and the retriever (reads terms).

Both sides MUST use the same functions, otherwise a search for "fractions" would never find a record
whose title says "Fraction", and "times tables" would never find "multiplication table".

Pipeline for one word:  lowercase -> strip punctuation -> drop stopwords -> plural stem -> synonym map.
The synonym map is applied AFTER stemming, so "multiplication", "times", "multiplied" and "product"
all become the canonical term "multiply" both in the index and in the query.

Keep this module small and deterministic. It must never call an AI model.
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
        "with", "you", "your", "s", "there", "they", "their", "them", "one", "ones", "will", "would",
        "should", "could", "much", "many", "very", "really", "just", "also", "use", "using",
        # Modifiers describe the level of a topic, not the topic. "basic algebra" searches "algebra".
        "basic", "simple", "easy", "intro", "introduction", "beginner", "beginning", "advanced",
    }
)

# Words that describe what the user wants to do, not what they want to learn about.
# "Teach me fractions" should search for "fractions" only. Intent is classified in knowledge/query.py.
INTENT_WORDS = frozenset(
    {
        "answer", "check", "describe", "define", "definition", "example", "examples", "explain",
        "exercise", "exercises", "find", "give", "help", "learn", "lesson", "lessons", "need",
        "please", "practice", "problem", "problems", "question", "questions", "show", "tell",
        "teach", "understand", "understanding", "want", "wrong", "quiz", "drill", "tutorial",
        "mean", "meaning", "walk", "start", "begin", "calculate", "compute", "solve", "work",
    }
)

# Synonyms and alternate wording, mapped to one canonical term. Keys are AFTER stemming
# (for example "fractions" is stored as "fraction", so only the singular key is needed).
# Add an entry when a real learner phrase fails to find a record. Each entry needs a test.
SYNONYMS: dict[str, str] = {
    # multiplication
    "times": "multiply", "multiply": "multiply", "multiplication": "multiply", "multiplied": "multiply",
    "product": "multiply", "multiplying": "multiply", "multiplicative": "multiply",
    # division
    "divide": "divide", "division": "divide", "divided": "divide", "dividing": "divide",
    "quotient": "divide", "share": "divide", "sharing": "divide",
    # addition
    "add": "add", "addition": "add", "adding": "add", "added": "add", "plus": "add", "sum": "add",
    "total": "add",
    # subtraction
    "subtract": "subtract", "subtraction": "subtract", "subtracting": "subtract", "minus": "subtract",
    "difference": "subtract", "takeaway": "subtract",
    # regrouping
    "carry": "regroup", "carrying": "regroup", "regroup": "regroup", "regrouping": "regroup",
    "borrow": "regroup", "borrowing": "regroup",
    # integers and negative numbers
    "negative": "integer", "negatives": "integer", "integer": "integer", "signed": "integer",
    "positive": "integer",
    # fractions and decimals
    "fraction": "fraction", "fractional": "fraction", "numerator": "fraction", "denominator": "fraction",
    "decimal": "decimal", "decimals": "decimal", "tenth": "decimal", "hundredth": "decimal",
    # percentages and ratios
    "percent": "percentage", "percentage": "percentage", "percentages": "percentage", "pct": "percentage",
    "ratio": "ratio", "proportion": "ratio", "proportional": "ratio", "rate": "ratio",
    # factors, multiples, primes
    "factor": "factor", "factorise": "factor", "factorize": "factor", "gcf": "factor", "gcd": "factor",
    "lcm": "multiple", "prime": "prime", "composite": "prime", "divisibility": "divisible",
    "divisible": "divisible",
    # exponents
    "exponent": "exponent", "power": "exponent", "index": "exponent", "squared": "exponent",
    "cubed": "exponent", "indices": "exponent",
    # order of operations
    "pemdas": "order", "bodmas": "order", "bidmas": "order", "operation": "order", "order": "order",
    "bracket": "bracket", "parenthesis": "bracket", "parentheses": "bracket",
    # place value and number sense
    "digit": "digit", "place": "place", "tens": "tens", "ten": "ten", "hundreds": "hundred",
    "hundred": "hundred", "thousands": "thousand", "thousand": "thousand", "ones": "ones",
    "units": "unit", "unit": "unit",
    "round": "round", "rounding": "round", "approximate": "round", "nearest": "round",
    "count": "count", "counting": "count", "skip": "count",
    "compare": "compare", "comparing": "compare", "comparison": "compare", "greater": "compare",
    "larger": "compare", "smaller": "compare", "bigger": "compare", "less": "compare",
    # algebra
    "algebra": "algebra", "algebraic": "algebra", "variable": "variable", "unknown": "variable",
    "symbol": "variable", "letter": "variable", "expression": "expression", "term": "term",
    "equation": "equation", "equal": "equation", "equals": "equation",
    "simplify": "simplify", "simplified": "simplify", "combine": "combine", "combining": "combine",
    "like": "like",
    # geometry and measurement
    "perimeter": "perimeter", "area": "area", "angle": "angle", "triangle": "triangle",
    "rectangle": "rectangle", "square": "square", "shape": "shape", "measure": "measure",
    "measurement": "measure", "length": "length", "width": "width", "height": "height",
    # misc
    "reciprocal": "reciprocal", "flip": "reciprocal",
    "sign": "sign", "rule": "rule", "law": "law",
}


def normalize(text: str) -> str:
    """Lowercase, drop apostrophes, and turn every other non-alphanumeric run into one space.

    "%" becomes the word "percent", so "25%" and "25 percent" search the same way.
    The multiplication sign and the division sign become words too.
    """
    lowered = text.lower().replace("\u2019", "'").replace("'", "")
    lowered = lowered.replace("%", " percent ").replace("\u00d7", " times ").replace("\u00f7", " divided by ")
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


def canonical(word: str) -> str:
    """The canonical search term for one already-normalized word.

    The raw word is checked against the synonym table first, because the stemmer would turn
    "times" into "time" before the lookup. Then the stemmed form is checked.
    """
    if word in SYNONYMS:
        return SYNONYMS[word]
    stemmed = stem(word)
    return SYNONYMS.get(stemmed, stemmed)


def term_pairs(text: str) -> list[tuple[str, str]]:
    """(typed word, canonical term) for each meaningful word, in order. Duplicates are kept."""
    pairs: list[tuple[str, str]] = []
    for raw in normalize(text).split():
        if len(raw) < 2 or raw in STOPWORDS or raw in INTENT_WORDS:
            continue
        term = canonical(raw)
        if term in STOPWORDS or term in INTENT_WORDS:
            continue
        pairs.append((raw, term))
    return pairs


def tokens(text: str) -> list[str]:
    """Meaningful search/index terms from free text, in order (may contain duplicates)."""
    return [term for _, term in term_pairs(text)]


def typo_lexicon(vocabulary: list[str]) -> dict[str, str]:
    """Spellings a typo may be close to, mapped to the canonical term they stand for.

    Built from the words people type (synonym keys such as "multiplication") and from the index
    vocabulary. Used only when a typed word of 5+ letters matches nothing exactly.
    """
    lexicon = dict(SYNONYMS)
    for term in vocabulary:
        lexicon.setdefault(term, term)
    return lexicon


def phrase_key(text: str) -> str:
    """Canonical form of a whole phrase, used for exact title/alias matches.

    Keeps stopwords on purpose, so "order of operations" keeps its "of". Synonyms are applied, so
    "times tables" and "multiplication tables" give the same key.
    """
    return " ".join(canonical(word) for word in normalize(text).split())
