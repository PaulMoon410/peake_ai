"""Bridge between Harold's persistent memory and an external trading bot.

The trading bot posts market context and a question; Harold recalls the
mechanisms it has already learned, checks them against the outcomes reported so
far, and returns guidance the bot can act on. The bot then reports what
actually happened, and Harold folds that result back into the mechanism
records, so the next recommendation rests on measured evidence rather than
the bot's original guesses.

Everything is stored as ordinary MCF3 notes under the ``Trading/`` categories,
which means the trading knowledge travels with the same FTP-synced memory the
rest of Harold uses and survives redeploys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Callable, Optional


MECHANISM_CATEGORY = "Trading/Mechanisms"
OUTCOME_CATEGORY = "Trading/Outcomes"
LESSON_CATEGORY = "Trading/Lessons"

_MECHANISM_RE = re.compile(r"^MECHANISM\s+([A-Za-z0-9_\-]+)\s*:\s*(.*)$", re.IGNORECASE)
_OUTCOME_RE = re.compile(r"^OUTCOME\s+([A-Za-z0-9_\-]+)\s*:\s*(.*)$", re.IGNORECASE)
_LESSON_RE = re.compile(r"^LESSON\s+([A-Za-z0-9_\-]+)\s*:\s*(.*)$", re.IGNORECASE)
_FIELD_RE = re.compile(r"(?:^|\|\s*)(\w+)\s*=\s*([^|]*)")
_WORD_RE = re.compile(r"[a-z0-9]+", re.UNICODE)


def _parse_fields(payload: str) -> tuple[str, dict[str, str]]:
    """Split a note body into its leading text and its ``key=value`` fields."""
    fields = {
        key.strip().casefold(): value.strip()
        for key, value in _FIELD_RE.findall(payload)
    }
    cleaned = _FIELD_RE.sub("", payload).replace("|", " ").strip()
    return cleaned, fields


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


@dataclass
class Mechanism:
    """A trading mechanism plus the outcomes measured for it so far."""

    key: str
    description: str = ""
    market: str = ""
    timeframe: str = ""
    tags: list[str] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    lessons: list[str] = field(default_factory=list)
    updated: str = ""

    @property
    def observations(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.observations if self.observations else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.pnl / self.observations if self.observations else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "description": self.description,
            "market": self.market,
            "timeframe": self.timeframe,
            "tags": list(self.tags),
            "wins": self.wins,
            "losses": self.losses,
            "observations": self.observations,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.pnl, 6),
            "avg_pnl": round(self.avg_pnl, 6),
            "lessons": list(self.lessons),
            "updated": self.updated,
        }

    def summary(self) -> str:
        parts = [f"{self.key}: {self.description}".strip(": ")]
        if self.market or self.timeframe:
            parts.append(f"({self.market or 'any market'} {self.timeframe or 'any timeframe'})")
        if self.observations:
            parts.append(
                f"[{self.wins}W/{self.losses}L, win rate {self.win_rate:.0%}, "
                f"avg PnL {self.avg_pnl:.3f}]"
            )
        else:
            parts.append("[no measured outcomes yet]")
        if self.lessons:
            parts.append("lessons: " + "; ".join(self.lessons[:3]))
        return " ".join(parts)


@dataclass
class Advice:
    """A recommendation plus the evidence behind it."""

    advice: str
    mechanisms: list[Mechanism] = field(default_factory=list)
    confidence: float = 0.0
    question: str = ""
    context: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "advice": self.advice,
            "question": self.question,
            "context": dict(self.context),
            "confidence": round(self.confidence, 4),
            "mechanisms": [mechanism.to_dict() for mechanism in self.mechanisms],
            "evidence": [mechanism.summary() for mechanism in self.mechanisms],
        }


class TradingBridge:
    """Lets a trading bot ask Harold for guidance and teach Harold what worked."""

    def __init__(self, store, responder: Optional[Callable[[str], str]] = None) -> None:
        self.store = store
        self.responder = responder

    def _store(self, note: str, category: str) -> Optional[dict[str, str]]:
        """Save a note locally and push it to the FTP archive when configured.

        Render's disk is ephemeral, so anything not uploaded to FTP is lost on
        redeploy. Trading knowledge has to reach the shared archive to survive.
        """
        record = self.store.add(note, category=category)
        if record is not None and getattr(self.store, "ftp_configured", False):
            try:
                self.store.upload(record)
            except Exception as exc:
                print(f"⚠️ Trading note FTP upload failed: {exc}")
        return record

    # -- learning -----------------------------------------------------------
    def learn_mechanism(
        self,
        key: str,
        description: str,
        market: str = "",
        timeframe: str = "",
        tags: Optional[list[str]] = None,
    ) -> dict[str, object]:
        """Record a trading mechanism so it can be recalled later."""
        key = _slug(key)
        description = (description or "").strip()
        if not key or not description:
            raise ValueError("A mechanism needs a key and a description.")
        if len(description) > 400:
            description = description[:397] + "..."

        note = f"MECHANISM {key}: {description}"
        note += f" | market={_slug(market) or 'any'}"
        note += f" | timeframe={_slug(timeframe) or 'any'}"
        if tags:
            note += f" | tags={','.join(_slug(tag) for tag in tags if _slug(tag))}"
        note += f" | updated={date.today().isoformat()}"

        record = self._store(note, MECHANISM_CATEGORY)
        if record is None:
            existing = self._mechanism(key)
            if existing is not None:
                return existing.to_dict()
            return {}
        return self._mechanism(key).to_dict() if self._mechanism(key) else {}

    def record_outcome(
        self,
        key: str,
        outcome: str,
        market: str = "",
        timeframe: str = "",
        pnl: float = 0.0,
        notes: str = "",
    ) -> dict[str, object]:
        """Fold a trading result back into memory so Harold learns from it."""
        key = _slug(key)
        outcome_text = (outcome or "").strip()
        if not key or not outcome_text:
            raise ValueError("An outcome needs a mechanism key and a result.")
        if len(outcome_text) > 300:
            outcome_text = outcome_text[:297] + "..."

        won = _is_win(outcome_text)
        note = f"OUTCOME {key}: {outcome_text}"
        note += f" | market={_slug(market) or 'any'}"
        note += f" | timeframe={_slug(timeframe) or 'any'}"
        note += f" | pnl={pnl:.6f}"
        note += f" | result={'win' if won else 'loss'}"
        if notes:
            note += f" | notes={notes.strip()[:200]}"
        note += f" | at={date.today().isoformat()}"

        self._store(note, OUTCOME_CATEGORY)
        return self.mechanism_stats(key)

    def record_lesson(self, key: str, lesson: str, market: str = "", timeframe: str = "") -> dict[str, object]:
        """Store a distilled lesson that applies to a mechanism."""
        key = _slug(key)
        lesson = (lesson or "").strip()
        if not key or not lesson:
            raise ValueError("A lesson needs a mechanism key and text.")
        note = f"LESSON {key}: {lesson[:400]}"
        note += f" | market={_slug(market) or 'any'}"
        note += f" | timeframe={_slug(timeframe) or 'any'}"
        note += f" | at={date.today().isoformat()}"
        self._store(note, LESSON_CATEGORY)
        return self.mechanism_stats(key)

    # -- recall -------------------------------------------------------------
    def recall_mechanisms(
        self,
        query: str = "",
        market: str = "",
        timeframe: str = "",
        limit: int = 6,
    ) -> list[Mechanism]:
        """Return learned mechanisms ranked by relevance to the query/context."""
        mechanisms = self._all_mechanisms()
        if not mechanisms:
            return []

        query_tokens = _tokens(query)
        market_slug = _slug(market)
        timeframe_slug = _slug(timeframe)

        scored: list[tuple[float, str, Mechanism]] = []
        for mechanism in mechanisms:
            score = 0.0
            if market_slug and mechanism.market == market_slug:
                score += 2.0
            if timeframe_slug and mechanism.timeframe == timeframe_slug:
                score += 1.0
            if query_tokens:
                haystack = _tokens(f"{mechanism.key} {mechanism.description} {' '.join(mechanism.tags)}")
                if haystack:
                    overlap = len(query_tokens & haystack) / len(query_tokens | haystack)
                    score += overlap * 3.0
            if score <= 0:
                continue
            scored.append((score, mechanism.key, mechanism))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [mechanism for _, _, mechanism in scored[:limit]]

    def mechanism_stats(self, key: str) -> dict[str, object]:
        """Aggregate one mechanism's measured outcomes."""
        key = _slug(key)
        mechanism = self._mechanism(key)
        if mechanism is None:
            return {"key": key, "observations": 0, "wins": 0, "losses": 0, "win_rate": 0.0}
        return mechanism.to_dict()

    def _all_mechanisms(self) -> list[Mechanism]:
        """Build aggregated mechanisms from every stored mechanism/outcome/lesson."""
        mechanisms: dict[str, Mechanism] = {}

        for record in self._records():
            note = record.get("n", "")
            category = record.get("c", "")
            if category == MECHANISM_CATEGORY:
                match = _MECHANISM_RE.match(note)
                if not match:
                    continue
                key = match.group(1).lower()
                body, fields = _parse_fields(match.group(2))
                mechanism = mechanisms.setdefault(key, Mechanism(key=key))
                mechanism.description = body or mechanism.description
                mechanism.market = fields.get("market", mechanism.market) or ""
                mechanism.timeframe = fields.get("timeframe", mechanism.timeframe) or ""
                mechanism.tags = [t for t in fields.get("tags", "").split(",") if t]
                mechanism.updated = fields.get("updated", mechanism.updated) or ""
            elif category == OUTCOME_CATEGORY:
                match = _OUTCOME_RE.match(note)
                if not match:
                    continue
                key = match.group(1).lower()
                _, fields = _parse_fields(match.group(2))
                mechanism = mechanisms.setdefault(key, Mechanism(key=key))
                if fields.get("result") == "win":
                    mechanism.wins += 1
                else:
                    mechanism.losses += 1
                mechanism.pnl += _to_float(fields.get("pnl", "0"))
                if fields.get("market") and fields["market"] != "any":
                    mechanism.market = fields["market"]
                if fields.get("timeframe") and fields["timeframe"] != "any":
                    mechanism.timeframe = fields["timeframe"]
            elif category == LESSON_CATEGORY:
                match = _LESSON_RE.match(note)
                if not match:
                    continue
                key = match.group(1).lower()
                body, _ = _parse_fields(match.group(2))
                mechanism = mechanisms.setdefault(key, Mechanism(key=key))
                if body:
                    mechanism.lessons.append(body)

        return [mechanism for mechanism in mechanisms.values() if mechanism.description]

    def _mechanism(self, key: str) -> Optional[Mechanism]:
        key = _slug(key)
        for mechanism in self._all_mechanisms():
            if mechanism.key == key:
                return mechanism
        return None

    def _records(self) -> list[dict[str, str]]:
        try:
            return list(self.store.all_records())
        except AttributeError:
            return list(getattr(self.store, "records", []))
        except Exception:
            return list(getattr(self.store, "records", []))

    # -- advising -----------------------------------------------------------
    def advise(self, context: Optional[dict[str, object]] = None, question: str = "") -> Advice:
        """Answer the trading bot's question using learned mechanisms and outcomes."""
        context = dict(context or {})
        question = (question or "").strip()
        market = str(context.get("market", "") or context.get("symbol", ""))
        timeframe = str(context.get("timeframe", "") or context.get("interval", ""))
        query = " ".join(
            part for part in (question, market, timeframe, str(context.get("strategy", ""))) if part
        )

        mechanisms = self.recall_mechanisms(query=query, market=market, timeframe=timeframe, limit=6)
        confidence = self._confidence(mechanisms)

        if not mechanisms:
            advice = (
                "I have not learned any trading mechanism that matches this context yet, "
                "so I would not steer the bot on this. Keep the current logic and report the "
                "outcome so I can learn from it."
            )
        elif self.responder is not None:
            advice = self._synthesize(question, context, mechanisms)
        else:
            advice = self._fallback_advice(mechanisms)

        return Advice(
            advice=advice,
            mechanisms=mechanisms,
            confidence=confidence,
            question=question,
            context=context,
        )

    def _synthesize(self, question: str, context: dict[str, object], mechanisms: list[Mechanism]) -> str:
        evidence = "\n".join(f"- {mechanism.summary()}" for mechanism in mechanisms)
        prompt = (
            "You are advising a trading bot using mechanisms you have already learned and measured.\n"
            f"Market context: {context}\n"
            f"Question: {question or 'What should the bot do in this situation?'}\n"
            "Learned mechanisms and their measured outcomes:\n"
            f"{evidence}\n\n"
            "Give a concrete, actionable recommendation grounded only in the evidence above. "
            "If the evidence is thin, say so and name what should be measured next."
        )
        try:
            answer = self.responder(prompt)
        except Exception as exc:
            print(f"⚠️ Trading advice synthesis failed: {exc}")
            return self._fallback_advice(mechanisms)
        if not answer or not answer.strip():
            return self._fallback_advice(mechanisms)
        return answer.strip()

    @staticmethod
    def _fallback_advice(mechanisms: list[Mechanism]) -> str:
        if not mechanisms:
            return "No learned mechanism matches this context yet."
        best = mechanisms[0]
        lines = [f"Best match is {best.key}: {best.description}"]
        if best.observations:
            lines.append(
                f"Across {best.observations} recorded outcome(s) it won {best.wins} and lost "
                f"{best.losses}, for an average PnL of {best.avg_pnl:.3f}."
            )
        else:
            lines.append("It has no measured outcomes yet, so treat it as a hypothesis.")
        if best.lessons:
            lines.append("Lessons: " + "; ".join(best.lessons[:3]))
        return " ".join(lines)

    @staticmethod
    def _confidence(mechanisms: list[Mechanism]) -> float:
        if not mechanisms:
            return 0.0
        observations = sum(mechanism.observations for mechanism in mechanisms)
        return min(1.0, observations / 10.0)

    # -- reporting ----------------------------------------------------------
    def summary(self) -> dict[str, object]:
        """A snapshot of what the trading bot has taught Harold so far."""
        mechanisms = self._all_mechanisms()
        wins = sum(mechanism.wins for mechanism in mechanisms)
        losses = sum(mechanism.losses for mechanism in mechanisms)
        observations = wins + losses
        return {
            "mechanisms": len(mechanisms),
            "observations": observations,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / observations, 4) if observations else 0.0,
            "top": [mechanism.summary() for mechanism in mechanisms[:5]],
        }


def _slug(value: str) -> str:
    """Normalize a market, timeframe, tag, or mechanism key into a safe token."""
    cleaned = re.sub(r"[^a-z0-9_\-]+", "-", str(value or "").casefold()).strip("-")
    return cleaned[:60]


def _tokens(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall(str(text or "").casefold()) if len(word) > 2}


def _is_win(outcome: str) -> bool:
    """Read a human-written result and decide whether it counts as a win."""
    lowered = outcome.casefold()
    losses = ("loss", "fail", "stopped", "stop-out", "stop out", "slippage", "margin call")
    wins = ("win", "profit", "target hit", "tp hit", "closed +", "closed up")
    if any(marker in lowered for marker in losses):
        return False
    if any(marker in lowered for marker in wins):
        return True
    return lowered.startswith("+")
