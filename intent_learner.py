"""Dynamic intent routing for PeakeBot.

Maps free-form user input onto a known action (``math``, ``search``, …) with
ultra-fast local embeddings from Semantic Router
(https://github.com/aurelio-labs/semantic-router), and learns new
phrase→intent mappings from successful turns.

Drop-in upgrade over the old token-overlap class: the constructor, the
``intents`` dict, ``learn_intent``/``match_intent`` and the legacy
``add_intent``/``get_intent`` helpers all keep their signatures, and the
token-overlap scorer remains the fallback whenever Semantic Router (or its
encoder) is not installed, so a bare Python install still routes correctly.
"""

import threading
from typing import Dict, List, Optional, Tuple

# Imported lazily inside the class so importing this module never starts the
# (fairly large) peakebot module while peakebot itself is still initialising.
_MIN_MATCH_SCORE = 0.4
_MAX_EXAMPLES_PER_TYPE = 24

_encoder_lock = threading.Lock()


def _router_modules():
    """Return ``(Route, SemanticRouter, encoder_factory)`` or ``None``."""
    try:
        from semantic_router import Route, SemanticRouter
        from semantic_router.encoders import FastEmbedEncoder, HuggingFaceEncoder
    except Exception:
        return None

    def _make_encoder():
        # HuggingFace sentence-transformers first, then FastEmbed (no torch).
        for encoder_cls in (HuggingFaceEncoder, FastEmbedEncoder):
            try:
                return encoder_cls()
            except Exception as exc:
                print(f"⚠️ Semantic Router encoder unavailable ({encoder_cls.__name__}): {str(exc)[:160]}")
        return None

    return Route, SemanticRouter, _make_encoder


class SemanticRouterEngine:
    """Thin wrapper that keeps one local encoder alive and routes to intents.

    ``identify`` never raises: any encoder download/run failure degrades to
    ``None`` so the caller can use its lexical fallback.
    """

    def __init__(self, threshold: float = _MIN_MATCH_SCORE) -> None:
        self.threshold = threshold
        self._modules = _router_modules()
        # Declared up front so ``self.router.engine`` always exists for callers;
        # it only drops to "token-overlap" when the encoder really fails.
        self.engine = "semantic-router"
        self._encoder = None
        self._router = None
        self._signature: Optional[tuple] = None

    def invalidate(self) -> None:
        """Force the next ``route`` call to rebuild the router (e.g. new intents)."""
        self._router = None
        self._signature = None

    @property
    def available(self) -> bool:
        return self.engine == "semantic-router" and self._modules is not None

    def _failed(self, exc: Exception | None = None) -> None:
        """Permanently downgrade to token overlap for this learner."""
        if exc is not None:
            print(f"⚠️ Semantic Router unavailable, using token overlap: {type(exc).__name__}: {str(exc)[:160]}")
        # Drop the handles so a half-built engine can never be reused.
        self._modules = None
        self._encoder = None
        self._router = None
        self.engine = "token-overlap"

    def _build_router(self, intents: Dict[str, List[str]]):
        Route, SemanticRouter, make_encoder = self._modules  # type: ignore[misc]
        signature = tuple(
            (intent_type, tuple(examples[-_MAX_EXAMPLES_PER_TYPE:]))
            for intent_type, examples in sorted(intents.items())
            if examples
        )
        if not signature:
            return None, signature
        with _encoder_lock:
            if self._encoder is None:
                self._encoder = make_encoder()
            if self._encoder is None:
                self._failed()  # stop retrying a broken install
                return None, signature
            try:
                routes = [
                    Route(name=name, utterances=list(examples), score_threshold=self.threshold)
                    for name, examples in signature
                ]
                return SemanticRouter(
                    encoder=self._encoder, routes=routes, auto_sync="local",
                ), signature
            except Exception as exc:
                self._failed(exc)
                return None, signature

    def route(self, phrase: str, intents: Dict[str, List[str]]) -> Optional[Tuple[str, float]]:
        """Return ``(intent_type, similarity)`` above threshold, else ``None``."""
        if not self.available or not phrase.strip() or not intents:
            return None
        try:
            if self._router is None or self._signature != self._current_signature(intents):
                router, signature = self._build_router(intents)
                self._router, self._signature = router, signature
            if self._router is None:
                return None
            choice = self._router(phrase)
        except Exception as exc:
            self._failed(exc)
            return None
        name = getattr(choice, "name", "") or ""
        try:
            similarity = float(getattr(choice, "similarity_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            similarity = 0.0
        if not name or similarity < self.threshold:
            return None
        return name, similarity

    @staticmethod
    def _current_signature(intents: Dict[str, List[str]]) -> tuple:
        return tuple(
            (intent_type, tuple(examples[-_MAX_EXAMPLES_PER_TYPE:]))
            for intent_type, examples in sorted(intents.items())
            if examples
        )


class IntentLearner:
    """Learns phrase-to-action mappings from conversation, applied linguistically.

    Harold watches which user wordings lead to successful actions (math, memory,
    search, and website reading) and stores those phrase→intent mappings in
    MCF3 memory. Later, free-form input that semantically matches a learned phrase
    triggers the same action without requiring an exact command.
    """

    def __init__(self, store) -> None:
        self.store = store
        self.intents: Dict[str, List[str]] = {}
        self.router = SemanticRouterEngine()
        self.router_engine = self.router.engine
        self._load_intents()

    # -- persistence -----------------------------------------------------
    def _load_intents(self) -> None:
        from peakebot import _ALLOWED_INTENT_TYPES, _INTENT_CATEGORY, _MAX_INTENT_EXAMPLES_PER_TYPE

        try:
            query = f"cat:{_INTENT_CATEGORY} INTENT"
            if getattr(self.store, "ftp_configured", False):
                notes = self.store.relevant_remote(query, limit=100, max_chars=24000)
            else:
                notes = self.store.relevant(query, limit=100, max_chars=24000)
        except Exception:
            try:
                notes = self.store.relevant(f"cat:{_INTENT_CATEGORY} INTENT", limit=100, max_chars=24000)
            except Exception:
                notes = ""
        if not notes:
            return
        for line in notes.splitlines():
            if not line.startswith("- ["):
                continue
            payload = line.split("] ", 1)[-1] if "] " in line else line
            marker = "INTENT:"
            if marker not in payload:
                continue
            body = payload[payload.index(marker) + len(marker):].strip()
            parts = [p.strip() for p in body.split("||")]
            if len(parts) < 2:
                continue
            action_type = parts[0]
            examples = [p for p in parts[1:] if p]
            if action_type in _ALLOWED_INTENT_TYPES and examples:
                known = self.intents.setdefault(action_type, [])
                for example in examples:
                    if example not in known and len(known) < _MAX_INTENT_EXAMPLES_PER_TYPE:
                        known.append(example)

    def learn_intent(self, phrase: str, action_type: str) -> None:
        """Record that `phrase` reliably maps to `action_type`."""
        from peakebot import (
            _ALLOWED_INTENT_TYPES,
            _INTENT_CATEGORY,
            _MAX_INTENT_EXAMPLES_PER_TYPE,
            _SENSITIVE_MEMORY_RE,
        )

        phrase = phrase.strip()
        if (action_type not in _ALLOWED_INTENT_TYPES or len(phrase) < 4 or len(phrase) > 200
            or "||" in phrase
                or _SENSITIVE_MEMORY_RE.search(phrase)):
            return
        examples = self.intents.setdefault(action_type, [])
        if phrase in examples or len(examples) >= _MAX_INTENT_EXAMPLES_PER_TYPE:
            return
        examples.append(phrase)
        try:
            note = f"INTENT:{action_type} || {phrase}"
            record = self.store.add(note, category=_INTENT_CATEGORY)
            if record and getattr(self.store, "ftp_configured", False):
                try:
                    self.store.upload(record)
                except Exception as exc:
                    print(f"⚠️ Intent FTP upload failed: {type(exc).__name__}: {str(exc)[:160]}")
        except Exception as exc:
            print(f"⚠️ Intent persistence failed: {exc}")

    # -- routing ---------------------------------------------------------
    def match_intent(self, phrase: str) -> Optional[Tuple[str, float]]:
        """Return (intent_type, confidence) for the best matching learned intent."""
        from peakebot import (
            _ALLOWED_INTENT_TYPES,
            _MIN_INTENT_MATCH_SCORE,
            _tokens,
        )

        if not self.intents:
            return None
        query_tokens = _tokens(phrase)
        best_type: Optional[str] = None
        best_score = 0.0
        if len(query_tokens) >= 2:
            for action_type, examples in self.intents.items():
                for example in examples:
                    example_tokens = _tokens(example)
                    if not example_tokens:
                        continue
                    overlap = len(query_tokens & example_tokens)
                    union = len(query_tokens | example_tokens)
                    score = overlap / union if union else 0.0
                    if overlap >= 2 and score > best_score:
                        best_score = score
                        best_type = action_type

        semantic = None
        if len(query_tokens) >= 2:
            semantic = self.router.route(
                phrase,
                {k: v for k, v in self.intents.items() if k in _ALLOWED_INTENT_TYPES},
            )
        if semantic is not None and semantic[1] > best_score:
            # Vector matches catch paraphrases token overlap misses, but only
            # replace a lexical match when strictly more confident.
            return semantic
        if best_type is not None and best_score >= _MIN_INTENT_MATCH_SCORE:
            return best_type, best_score
        self.router_engine = self.router.engine
        return semantic

    # -- legacy compatibility -------------------------------------------
    def add_intent(self, intent_type: str, phrase: str) -> bool:
        """Add a phrase→intent mapping; ``True`` when a new phrase was stored."""
        from peakebot import _ALLOWED_INTENT_TYPES, _INTENT_CATEGORY

        if intent_type not in _ALLOWED_INTENT_TYPES:
            return False
        phrase = str(phrase or "").strip()
        if not phrase:
            return False
        if phrase in self.intents.get(intent_type, []):
            return False
        self.learn_intent(phrase, intent_type)
        stored = phrase in self.intents.get(intent_type, [])
        if stored:
            try:
                self.store.set(_INTENT_CATEGORY, self.intents)
            except Exception as exc:
                print(f"⚠️ Failed to save intents: {exc}")
        return stored

    def get_intent(self, phrase: str) -> Optional[str]:
        """Return just the intent type for ``phrase`` (legacy API)."""
        match = self.match_intent(phrase)
        return match[0] if match else None

    def _calculate_similarity(self, phrase1: str, phrase2: str) -> float:
        """Token-overlap (Jaccard) similarity, kept for backwards compatibility."""
        words1 = set(str(phrase1).lower().split())
        words2 = set(str(phrase2).lower().split())
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)
