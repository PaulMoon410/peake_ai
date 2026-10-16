"""Vocabulary that decides whether a sentence says something about human experience.

Harold scrapes pages that are mostly navigation, adverts and legal notices. This
module is the small, explainable filter that keeps the parts of a page that
actually describe what a human feels, senses, does or believes.
"""

from __future__ import annotations

import re


WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Words that mark text as being about subjective human experience. Matching is
# stem-friendly (a leading match is enough), so "feel" also catches "feeling"
# and "felt" is listed separately because it is not a prefix of "feel".
EXPERIENCE_TERMS: frozenset[str] = frozenset({
    "feel", "felt", "emotion", "mood", "sense", "sensation", "perceive", "aware",
    "experience", "remember", "memory", "nostalgia", "longing", "grief", "mourn",
    "joy", "delight", "happy", "sad", "anger", "angry", "fear", "afraid", "anxious",
    "worry", "lonely", "comfort", "discomfort", "pain", "ache", "warmth", "tired",
    "exhaust", "hunger", "thirst", "appetite", "sleep", "dream", "breathe", "breath",
    "taste", "smell", "scent", "touch", "hear", "sound", "sight", "body", "bodily",
    "physical", "urge", "impulse", "habit", "routine", "ritual", "custom", "tradition",
    "believe", "belief", "value", "care", "love", "friend", "family", "parent",
    "child", "grief", "stress", "calm", "relief", "hope", "regret", "boredom",
    "attention", "conscious", "subjective", "empathy", "cope", "coping", "wellbeing",
    "human", "people", "person",
})

# Phrases that mean the sentence is page furniture rather than an observation.
BOILERPLATE_MARKERS: tuple[str, ...] = (
    "cookie", "privacy policy", "terms of service", "all rights reserved",
    "sign up", "log in", "subscribe", "newsletter", "advertisement", "sponsored",
    "click here", "read more", "share this", "follow us", "download the app",
    "skip to content", "jump to navigation", "back to top", "related articles",
    "accept all", "manage consent", "we use cookies", "javascript", "browser",
    "your email", "contact us", "about us", "advertise with", "affiliate",
)

_MIN_SENTENCE_CHARS = 45
_MAX_SENTENCE_CHARS = 460


def words(text: str) -> list[str]:
    """Lower-cased word tokens."""
    return [w.casefold() for w in WORD_RE.findall(text)]


def is_boilerplate(text: str) -> bool:
    """True when a sentence looks like navigation, advertising or legal text."""
    lowered = text.casefold()
    if any(marker in lowered for marker in BOILERPLATE_MARKERS):
        return True
    if lowered.count("|") >= 2 or lowered.count("»") >= 1:
        return True
    letters = sum(character.isalpha() for character in text)
    return letters < len(text) * 0.6


def experience_score(text: str, extra_keywords: tuple[str, ...] | set[str] = ()) -> int:
    """How strongly a sentence reads as human experience, not page furniture."""
    if is_boilerplate(text):
        return 0
    tokens = words(text)
    if not tokens:
        return 0
    score = 0
    for token in tokens:
        if token in EXPERIENCE_TERMS:
            score += 2
        elif len(token) > 4 and any(token.startswith(term) for term in _EXPERIENCE_PREFIXES):
            score += 1
    for keyword in extra_keywords:
        needle = keyword.casefold()
        if needle and needle in text.casefold():
            score += 3
    return score


_EXPERIENCE_PREFIXES: frozenset[str] = frozenset(
    term for term in EXPERIENCE_TERMS if len(term) >= 5
)


def is_experiential(text: str, extra_keywords: tuple[str, ...] | set[str] = ()) -> bool:
    """True when a sentence is a plausible observation about human experience."""
    stripped = text.strip()
    if not (_MIN_SENTENCE_CHARS <= len(stripped) <= _MAX_SENTENCE_CHARS):
        return False
    if stripped.endswith((":", ";", ",")) or stripped.count("?") > 0:
        return False
    if stripped.count(". ") > 3:
        return False
    return experience_score(stripped, extra_keywords) >= 2


def normalise(text: str) -> str:
    """Whitespace-collapsed form used before storing or comparing text."""
    return " ".join(text.split())


def note_key(text: str) -> str:
    """Comparison key for near-duplicate detection (case and punctuation agnostic)."""
    return " ".join(words(text))


def fit_note(text: str, limit: int) -> str:
    """Trim a note to ``limit`` characters on a word boundary, keeping it whole."""
    collapsed = normalise(text)
    if len(collapsed) <= limit:
        return collapsed
    clipped = collapsed[:limit]
    if " " in clipped:
        clipped = clipped[: clipped.rfind(" ")]
    return clipped.rstrip(" ,;:-") + "…"
