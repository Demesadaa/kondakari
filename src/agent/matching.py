import re

STAPLES = {"salt", "pepper", "black pepper", "water"}
_DESCRIPTORS = {
    "fresh", "chopped", "large", "small", "medium", "dried", "ground", "sliced",
    "minced", "whole", "organic", "free", "range", "of", "and", "raw",
}


def normalize(name: str) -> str:
    return " ".join(name.lower().split())


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(name: str) -> frozenset[str]:
    """Letter-only words (any script, so Georgian works too), singularised, minus cooking descriptors."""
    return frozenset(_singular(w) for w in re.findall(r"[^\W\d_]+", name.lower()) if w not in _DESCRIPTORS)


def matches(pantry_name: str, ingredient: str) -> bool:
    """Heuristic: 'eggs' matches 'Egg', 'chicken' matches 'Chicken Breast'."""
    p, i = tokens(pantry_name), tokens(ingredient)
    return bool(p and i) and (p <= i or i <= p)


def is_staple(ingredient: str) -> bool:
    return normalize(ingredient) in STAPLES
