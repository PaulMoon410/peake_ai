"""Continuous math learning: verify, store, and recall mathematical facts.

The learner treats math as another compact language. Simple arithmetic is
checked outright; broader statements are stored as memory notes under the Math
category so they can be recalled and built on across sessions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from memory_store import MemoryStore


_EXPR_RE = re.compile(r"^[0-9\s\+\-\*\/\(\)\.]+$")
_MATH_CATEGORY = "Math"


@dataclass(frozen=True, slots=True)
class MathFact:
    """One learned mathematical fact."""

    expression: str
    result: str
    verified: bool


class MathLearner:
    """Learn and recall math continuously, backed by the MCF3 memory store."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def learn(self, statement: str) -> MathFact | None:
        """Verify and store one math statement. Returns the fact or None."""
        cleaned = statement.strip()
        if not cleaned:
            return None
        verified, result = self._verify(cleaned)
        note = f"{cleaned} = {result}" + (" (unverified)" if not verified else "")
        try:
            self.store.add(note, category=_MATH_CATEGORY)
        except ValueError:
            pass
        return MathFact(expression=cleaned, result=result, verified=verified)

    def recall(self, query: str, limit: int = 8) -> str:
        """Recall learned math facts relevant to the query."""
        return self.store.relevant(f"cat:Math {query}", limit=limit)

    def facts(self) -> list[MathFact]:
        """All learned math facts, newest first."""
        found: list[MathFact] = []
        for record in self.store.records:
            if str(record.get("c", "")) != _MATH_CATEGORY:
                continue
            note = record.get("n", "")
            if " = " not in note:
                continue
            expression, result = note.split(" = ", 1)
            verified = "(unverified)" not in result
            result = result.replace(" (unverified)", "").strip()
            found.append(MathFact(expression=expression.strip(), result=result, verified=verified))
        return found

    def evaluate(self, expression: str) -> str | None:
        """Safely evaluate a simple arithmetic expression."""
        _, result = self._verify(expression)
        return result if result != expression else None

    # -- verification -------------------------------------------------------
    @staticmethod
    def _verify(statement: str) -> tuple[bool, str]:
        """Check a simple arithmetic statement; return (verified, result)."""
        expr = statement
        for word, symbol in (("divided by", "/"), ("plus", "+"), ("minus", "-"), ("times", "*")):
            expr = expr.replace(word, symbol)
        expr = expr.replace("x", "*").replace("X", "*").replace("÷", "/")
        expr = re.sub(r"[^0-9\s\+\-\*\/\(\)\.]", "", expr)
        if not _EXPR_RE.match(expr.strip()):
            return False, statement
        try:
            value = eval(expr, {"__builtins__": {}}, {})
        except Exception:
            return False, statement
        if isinstance(value, float):
            result = str(round(value, 6)).rstrip("0").rstrip(".")
        else:
            result = str(value)
        return True, result
