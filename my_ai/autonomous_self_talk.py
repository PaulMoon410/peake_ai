"""Continuous, persistent self-talk between the AI's own roles.

The loop keeps one conversation going instead of restarting it every cycle:

* both roles see the full dialogue so far, so it builds up rather than repeats;
* every answer is produced by asking the AI providers and comparing them, with
  the strongest corroborated answer winning (the *answer* is checked, not the
  question);
* the dialogue is checkpointed to ``self_talk_dialogue.json`` so a restart, a
  Render spin-down or a redeploy resumes where it stopped;
* the web chat can tail the same log, so the conversation is visible.

Providers are reached through ``peakebot._query_ai_providers_for_self_talk`` so
API keys and ordering stay in one place; nothing here needs its own keys.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

DIALOGUE_FILE = os.getenv("SELF_TALK_DIALOGUE_FILE", "self_talk_dialogue.json")
MAX_TURNS_KEPT = int(os.getenv("SELF_TALK_MAX_TURNS", "120"))
MAX_TURNS_PER_CALL = int(os.getenv("SELF_TALK_MAX_TURNS_PER_CALL", "40"))
CYCLE_SECONDS = float(os.getenv("SELF_TALK_CYCLE_SECONDS", "45"))
# How many providers must agree before an answer is called corroborated.
MIN_AGREEMENT = int(os.getenv("SELF_TALK_MIN_AGREEMENT", "2"))

_DISCIPLINES = [
    "programming", "mathematics", "science", "history", "philosophy",
    "technology", "health", "economics", "literature", "problem solving",
]

INSTRUCTOR_SYSTEM = (
    "You are Harold's Instructor role in an ongoing self-study dialogue. You teach one "
    "precise point per turn, build on everything said before, and ask the Learner one "
    "concrete question that tests understanding. Keep replies under 120 words. "
    "Do not repeat earlier turns; advance the lesson."
)
LEARNER_SYSTEM = (
    "You are Harold's Learner role in an ongoing self-study dialogue. Answer the "
    "Instructor from what you already know, state clearly when you are unsure, and end "
    "with one short question back. Keep replies under 120 words. Build on earlier turns."
)
CRITIC_SYSTEM = (
    "You are Harold's Critic role. Compare the candidate answers to the Instructor's "
    "question. State which one is most likely correct and why in one or two sentences. "
    "Prefer the answer that other models corroborate; flag anything that looks invented."
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", _norm(text)) if len(w) > 2}


def _similar(a: str, b: str) -> float:
    """Jaccard overlap of content words: cheap proxy for "says the same thing"."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class SelfTalkDialogue:
    """Append-only conversation log, checkpointed to disk after every turn."""

    def __init__(self, path: str | os.PathLike = DIALOGUE_FILE) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.turns: List[Dict[str, Any]] = self._load()
        self.current_learning_objective = self._get_current_learning_objective()
        
    def _get_current_learning_objective(self) -> str:
        """Get the current learning objective or generate a new one."""
        # Check if we have a stored objective in the last few turns
        for turn in reversed(self.recent(10)):
            if turn.get("learning_objective"):
                return str(turn["learning_objective"])
        
        # If no stored objective, pick a new one
        index = sum(1 for t in self.recent(MAX_TURNS_KEPT) if t.get("role") == "instructor")
        disciplines = [
            "English grammar", "writing skills", "reading comprehension", 
            "vocabulary building", "sentence structure", "communication",
            "literary analysis", "language mechanics", "rhetoric", "composition"
        ]
        return disciplines[index % len(disciplines)]
        
    def _update_learning_objective(self) -> None:
        """Update the learning objective periodically."""
        # Change learning objective every 3 turns
        instructor_turns = [t for t in self.recent(MAX_TURNS_KEPT) if t.get("role") == "instructor"]
        if len(instructor_turns) % 3 == 0:
            index = sum(1 for t in self.recent(MAX_TURNS_KEPT) if t.get("role") == "instructor")
            disciplines = [
                "English grammar", "writing skills", "reading comprehension", 
                "vocabulary building", "sentence structure", "communication",
                "literary analysis", "language mechanics", "rhetoric", "composition"
            ]
            self.current_learning_objective = disciplines[index % len(disciplines)]

    # -- persistence -----------------------------------------------------
    def _load(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        turns = data.get("turns") if isinstance(data, dict) else data
        return [t for t in turns if isinstance(t, dict)] if isinstance(turns, list) else []

    def _save(self) -> None:
        payload = {
            "updated": datetime.now().isoformat(),
            "turns": self.turns[-MAX_TURNS_KEPT:],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(self.path)

    # -- access ----------------------------------------------------------
    def add(self, role: str, text: str, *, topic: str = "", provider: str = "",
            agreement: int = 0, models: Optional[Dict[str, str]] = None,
            learning_objective: str = "") -> Dict[str, Any]:
        turn = {
            "role": role,
            "text": text,
            "topic": topic,
            "provider": provider,
            "agreement": agreement,
            "models": models or {},
            "learning_objective": learning_objective,
            "timestamp": datetime.now().isoformat(),
        }
        with self._lock:
            self.turns.append(turn)
            del self.turns[:-MAX_TURNS_KEPT]
            self._save()
        return turn

    def since(self, index: int, limit: int = MAX_TURNS_PER_CALL) -> Tuple[List[Dict[str, Any]], int]:
        """Return ``(turns after index, next index)`` for the polling web chat."""
        with self._lock:
            start = max(0, int(index or 0))
            chunk = self.turns[start:start + limit]
            return list(chunk), min(len(self.turns), start + limit)

    def recent(self, count: int = 8) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.turns[-count:])

    def clear(self) -> None:
        with self._lock:
            self.turns = []
            self._save()

    # -- prompt building -------------------------------------------------
    def transcript(self, count: int = 12, max_chars: int = 6000) -> str:
        history = self.recent(count)
        lines = []
        for turn in history:
            label = {"instructor": "Instructor", "learner": "Learner", "critic": "Critic"}.get(
                str(turn.get("role")), str(turn.get("role", "?"))
            )
            lines.append(f"{label}: {str(turn.get('text', ''))[:1200]}")
        return "\n".join(lines)[-max_chars:]

    def set_topic(self, topic: str) -> None:
        """Record the topic to continue with, without inventing a dialogue turn."""
        text = f"Focus topic: {topic}"
        with self._lock:
            if self.turns and self.turns[-1].get("role") == "system" and self.turns[-1].get("text") == text:
                return  # already the active seed
            self.turns.append({
                "role": "system", "text": text, "topic": topic, "provider": "",
                "agreement": 0, "models": {}, "timestamp": datetime.now().isoformat(),
            })
            del self.turns[:-MAX_TURNS_KEPT]
            self._save()

    def current_topic(self) -> str:
        for turn in reversed(self.recent(MAX_TURNS_KEPT)):
            if turn.get("topic"):
                return str(turn["topic"])
        return ""


class PeakeSelfTalkEngine:
    """Drives the Instructor ⇄ Learner dialogue, with a Critic that checks answers."""

    def __init__(self, buffer_path: str = "online_learning_buffer.json",
                 dialogue_path: str = DIALOGUE_FILE,
                 ask: Optional[Callable[[List[Tuple[str, str]], str], Any]] = None) -> None:
        self.buffer_path = buffer_path
        self.dialogue = SelfTalkDialogue(dialogue_path)
        self.instructor_system = INSTRUCTOR_SYSTEM
        self.learner_system = LEARNER_SYSTEM
        self.critic_system = CRITIC_SYSTEM
        # ``ask(messages, purpose)`` runs one chat completion for a given role.
        self._ask = ask or self._default_ask

    # -- provider plumbing -----------------------------------------------
    @staticmethod
    def _default_ask(messages: List[Tuple[str, str]], purpose: str = "single") -> Dict[str, Any]:
        import peakebot

        return peakebot._query_ai_providers_for_self_talk(messages, purpose=purpose)

    def _consult(self, messages: List[Tuple[str, str]]) -> Dict[str, Any]:
        """Ask every configured provider; return answers, the winner and agreement."""
        result = self._ask(messages, "consensus") or {}
        answers: Dict[str, str] = {
            str(k): str(v).strip() for k, v in (result.get("answers") or {}).items()
            if v and str(v).strip()
        }
        
        # Log provider successes and failures
        if result.get("failures"):
            print(f"Provider failures: {result['failures']}")
        
        if answers:
            print(f"Provider successes: {list(answers.keys())}")
        
        if not answers:
            print("All providers failed to return valid answers")
            return {"text": "", "provider": "", "agreement": 0, "answers": {}, "failures": result.get("failures", {})}

        order = result.get("order") or list(answers)
        best, best_support = order[0], -1
        for candidate in order:
            if candidate not in answers:
                continue
            support = 1 + sum(
                1 for other, text in answers.items()
                if other != candidate and _similar(answers[candidate], text) >= 0.45
            )
            if support > best_support:
                best, best_support = candidate, support
        
        print(f"Selected answer from {best} with corroboration level {best_support}")
        return {
            "text": answers.get(best, ""),
            "provider": best,
            "agreement": max(best_support, 0),
            "answers": answers,
            "failures": result.get("failures", {}) or {},
        }

    def _critique(self, topic: str, learning_objective: str, answers: Dict[str, str]) -> str:
        if len(answers) < 2:
            print("Skipping critique - not enough candidate answers to compare")
            return ""
            
        print(f"Starting critique for learning objective: {learning_objective}")
        listing = "\n".join(f"{name}: {text[:800]}" for name, text in answers.items())
        messages = [
            ("system", self.critic_system),
            ("user", f"Topic: {topic}\n\nLearning Objective: {learning_objective}\n\nCandidate answers:\n{listing}"),
        ]
        result = self._ask(messages, "single") or {}
        
        if result and result.get("answer"):
            print("Critique successfully generated")
            return str(result.get("answer") or "").strip()
        else:
            print("Failed to generate critique")
            return ""

    # -- the loop --------------------------------------------------------
    def _pick_topic(self) -> str:
        """Continue the current topic, or move on after a good run of turns."""
        topic = self.dialogue.current_topic()
        # A seeded/explicit topic is only abandoned once it has had a full lesson.
        on_topic = sum(
            1 for t in self.dialogue.recent(MAX_TURNS_KEPT)
            if t.get("topic") == topic and t.get("role") in {"instructor", "learner"}
        )
        if topic and on_topic < 5:
            return topic
        index = sum(1 for t in self.dialogue.recent(MAX_TURNS_KEPT) if t.get("role") == "instructor")
        return _DISCIPLINES[index % len(_DISCIPLINES)]

    def next_turn(self) -> Dict[str, Any]:
        """Advance the dialogue by one turn (instructor sets the question, then the learner answers)."""
        print("Starting new conversation turn")
        topic = self._pick_topic()
        transcript = self.dialogue.transcript()
        
        # Get the current learning objective
        learning_objective = self.dialogue.current_learning_objective
        print(f"Current topic: {topic}, Learning objective: {learning_objective}")
        
        # Determine which bot is speaking (alternate between turns)
        is_bot1_turn = len([t for t in self.dialogue.recent(MAX_TURNS_KEPT) if t.get("role") == "instructor"]) % 2 == 0
        speaker = "Instructor (Expert)" if is_bot1_turn else "Learner"
        print(f"Current speaker: {speaker}")
        
        if is_bot1_turn:
            # Bot 1 (Expert) speaks
            print("Instructor preparing question...")
            instructor_messages = [("system", self.instructor_system)]
            if transcript:
                prompt = f"Topic: {topic}\n\nLearning Objective: {learning_objective}\n\nDialogue so far:\n{transcript}\n\nContinue the lesson."
            else:
                prompt = f"Topic: {topic}\n\nLearning Objective: {learning_objective}\n\nBegin the lesson."
            instructor_messages.append(("user", prompt))
        else:
            # Bot 2 (Learner) speaks
            print("Learner preparing answer...")
            learner_messages = [("system", self.learner_system)]
            prompt = f"Topic: {topic}\n\nLearning Objective: {learning_objective}\n\nDialogue so far:\n{self.dialogue.transcript()}\n\nAnswer the Instructor."
            learner_messages.append(("user", prompt))
            
            # Get the learner's answer
            answer_turn = self._consult(learner_messages)
            answer = answer_turn["text"]
            print(f"Learner response length: {len(answer) if answer else 0} characters")
            
            self.dialogue.add(
                "learner", answer, topic=topic, provider=answer_turn["provider"],
                agreement=answer_turn["agreement"], models=answer_turn["answers"],
                learning_objective=learning_objective
            )
            # Check the answer *after* it is recorded, so the log reads in order.
            critique = self._critique(topic, learning_objective, answer_turn["answers"]) if answer else ""
            if critique:
                self.dialogue.add("critic", critique, topic=topic, provider="critic")
            if answer:
                self.log_learned_fact(
                    f"{topic}: {answer[:280]}",
                    corroboration=answer_turn["agreement"],
                    provider=answer_turn["provider"],
                )
            
            # Update learning objective periodically
            if len([t for t in self.dialogue.recent(MAX_TURNS_KEPT) if t.get("role") == "instructor"]) % 3 == 0:
                print("Updating learning objective...")
                self.dialogue._update_learning_objective()
            
            return {"topic": topic, "question": learning_objective, "answer": answer, "critique": critique}
            
        # Get the instructor's question
        question_turn = self._consult(instructor_messages)
        question = question_turn["text"] or f"What do we already know about {topic}?"
        print(f"Instructor question length: {len(question)} characters")
        
        self.dialogue.add(
            "instructor", question, topic=topic, provider=question_turn["provider"],
            agreement=question_turn["agreement"], models=question_turn["answers"],
            learning_objective=learning_objective
        )
        
        return {"topic": topic, "question": question, "answer": "", "critique": ""}

    # Kept so existing callers (``/selftalk`` command, CLI) keep working.
    def execute_self_talk_command(self, cycles: int, curriculum_topic: str = "") -> List[Dict[str, Any]]:
        print(f"Self-talk: {cycles} turn(s)" + (f" on {curriculum_topic}" if curriculum_topic else ""))
        if curriculum_topic:
            # A seed only matters when the checkpoint has nothing to continue.
            if not self.dialogue.current_topic():
                self.dialogue.add("system", f"Focus topic: {curriculum_topic}", topic=curriculum_topic)
            else:
                print(f"Continuing the saved conversation on '{self.dialogue.current_topic()}'.")
        results = []
        for _ in range(max(1, int(cycles))):
            turn = self.next_turn()
            print(f"[{turn['topic']}] Instructor: {turn['question'][:160]}")
            print(f"[{turn['topic']}] Learner: {turn['answer'][:160]}")
            if turn.get("critique"):
                print(f"[{turn['topic']}] Critic: {turn['critique'][:160]}")
            results.append(turn)
        return results

    # -- learning queue --------------------------------------------------
    def log_learned_fact(self, fact_text: str, corroboration: int = 0, provider: str = "self_talk") -> None:
        """Queue a corroborated fact for training, through the validated schema."""
        try:
            from my_ai.learning_schemas import LearningItem, load_learning_buffer, save_learning_buffer

            items, _ = load_learning_buffer(Path(self.buffer_path))
            # Quality rises with corroboration, capped so self-talk never
            # outranks a directly scored interaction.
            quality = min(0.9, 0.5 + 0.15 * max(0, corroboration))
            items.append(LearningItem(
                prompt=f"Self-study ({provider}) explain: {fact_text[:200]}",
                response=fact_text,
                source="self_talk_continuous",
                quality=quality,
            ))
            save_learning_buffer(Path(self.buffer_path), items)
        except Exception as exc:
            print(f"⚠️ Self-talk fact not queued: {type(exc).__name__}: {exc}")


class SelfTalkRunner:
    """Owns the background thread that keeps the conversation going.

    ``start`` is idempotent, ``stop`` is cooperative, and state survives because
    the dialogue itself lives on disk. Usage is metered per day so a 24h loop
    cannot quietly run up provider bills.
    """

    def __init__(self, engine_factory: Callable[[], PeakeSelfTalkEngine] = PeakeSelfTalkEngine,
                 cycle_seconds: float = CYCLE_SECONDS,
                 seconds_per_day: float = float(os.getenv("SELF_TALK_HOURS", "24")) * 3600,
                 max_turns_per_day: int = int(os.getenv("SELF_TALK_MAX_TURNS_PER_DAY", "400"))) -> None:
        self._engine_factory = engine_factory
        self._cycle_seconds = cycle_seconds
        self._seconds_per_day = seconds_per_day
        self._max_turns_per_day = max_turns_per_day
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._topic = ""
        self.turns_done = 0
        self.last_error = ""
        self.started_at: Optional[float] = None
        self.stopped_reason = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def status(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "topic": self._topic,
            "turns": self.turns_done,
            "cycle_seconds": self._cycle_seconds,
            "started_at": datetime.fromtimestamp(self.started_at).isoformat() if self.started_at else None,
            "last_error": self.last_error,
            "stopped_reason": self.stopped_reason,
        }

    def start(self, topic: str = "") -> bool:
        """Start the loop; ``False`` if it was already running."""
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self._topic = topic.strip()
            self.turns_done = 0
            self.last_error = ""
            self.stopped_reason = ""
            self.started_at = time.time()
            self._thread = threading.Thread(target=self._run, name="selftalk-continuous", daemon=True)
            self._thread.start()
            return True

    def stop(self, reason: str = "stopped") -> None:
        self.stopped_reason = reason
        self._stop.set()

    def _run(self) -> None:
        engine = self._engine_factory()
        if self._topic:
            # Persist the seed so the conversation continues it, even after a restart.
            engine.dialogue.set_topic(self._topic)
        else:
            self._topic = engine.dialogue.current_topic()
        deadline = time.time() + self._seconds_per_day
        while not self._stop.is_set():
            if time.time() >= deadline:
                self.stopped_reason = "daily budget reached"
                break
            if self.turns_done >= self._max_turns_per_day:
                self.stopped_reason = "daily turn limit reached"
                break
            try:
                turn = engine.next_turn()
                self.turns_done += 1
                self._topic = turn.get("topic", self._topic)
                self.last_error = ""
            except Exception as exc:  # a provider outage must not kill the loop
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(f"[selftalk] {self.last_error}", flush=True)
            self._stop.wait(self._cycle_seconds)
        self._thread = None


# One runner per process so repeated /api/selftalk calls don't spawn duplicates.
_runner_lock = threading.Lock()
_runner: Optional[SelfTalkRunner] = None


def get_runner() -> SelfTalkRunner:
    global _runner
    with _runner_lock:
        if _runner is None:
            _runner = SelfTalkRunner()
        return _runner


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Harold's continuous self-talk.")
    parser.add_argument("--turns", type=int, default=3, help="turns to run in the foreground")
    parser.add_argument("--topic", default="", help="focus topic (continues from checkpoint if omitted)")
    parser.add_argument("--forever", action="store_true", help="run the continuous loop until stopped")
    args = parser.parse_args()

    if args.forever:
        runner = get_runner()
        runner.start(args.topic)
        try:
            while runner.running:
                time.sleep(5)
        except KeyboardInterrupt:
            runner.stop("interrupted")
    else:
        engine = PeakeSelfTalkEngine()
        engine.execute_self_talk_command(cycles=args.turns, curriculum_topic=args.topic)
