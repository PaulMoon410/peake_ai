"""Continuous math learning: verify, store, and recall mathematical facts.

The learner treats math as another compact language. Simple arithmetic is
checked outright; broader statements are stored as memory notes under the Math
category so they can be recalled and built on across sessions.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass

if __package__:
    from .memory_store import MemoryStore
else:
    from memory_store import MemoryStore


_EXPR_RE = re.compile(r"^[0-9\s\+\-\*\/\(\)\.]+$")
_MATH_CATEGORY = "Math"
_MAX_EXPRESSION_CHARS = 256
_MAX_EXPRESSION_NODES = 64
_MAX_RESULT_MAGNITUDE = 1e100


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
        self.store.add(note, category=_MATH_CATEGORY)
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
        expr = expr.strip()
        if len(expr) > _MAX_EXPRESSION_CHARS or not _EXPR_RE.fullmatch(expr):
            return False, statement
        try:
            parsed = ast.parse(expr, mode="eval")
            nodes = list(ast.walk(parsed))
            if len(nodes) > _MAX_EXPRESSION_NODES:
                return False, statement
            value = MathLearner._evaluate_node(parsed.body)
        except Exception:
            return False, statement
        if isinstance(value, float):
            result = str(round(value, 6)).rstrip("0").rstrip(".")
        else:
            result = str(value)
        return True, result

    @staticmethod
    def _evaluate_node(node: ast.expr) -> int | float:
        """Evaluate only bounded numeric literals and basic arithmetic AST nodes."""
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = MathLearner._evaluate_node(node.operand)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp):
            left = MathLearner._evaluate_node(node.left)
            right = MathLearner._evaluate_node(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.Div):
                value = left / right
            else:
                raise ValueError("Unsupported arithmetic operator")
        else:
            raise ValueError("Unsupported arithmetic expression")

        if isinstance(value, int):
            if value.bit_length() > 334:
                raise ValueError("Arithmetic result is too large")
        elif not math.isfinite(value) or abs(value) > _MAX_RESULT_MAGNITUDE:
            raise ValueError("Arithmetic result is not finite or is too large")
        return value
