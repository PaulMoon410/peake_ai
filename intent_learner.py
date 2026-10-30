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

Semantic Router changed its API between the 0.0.x and 1.x lines (the router
class moved and ``similarity_score`` became ``confidence``). ``_load_api``
below detects the installed flavour once; anything unexpected degrades to the
token-overlap scorer instead of raising.
"""

import threading
from typing import Dict, List, Optional, Tuple

# Imported lazily inside the class so importing this module never starts the
# (fairly large) peakebot module while peakebot itself is still initialising.
_MIN_MATCH_SCORE = 0.4
_MAX_EXAMPLES_PER_TYPE = 24

# How long a failed router build is trusted before another attempt is made
# (e.g. the encoder model finished downloading during a later turn).
_RETRY_AFTER_SECONDS = 900.0

_encoder_lock = threading.Lock()


def _load_api():
    """Return ``(router_class, encoder_factory)`` or ``None`` when unavailable.

    Only standard, cheap imports happen here so an installed-but-unsupported
    version is reported as "unavailable", never as an exception.
    """
    try:
        from semantic_router.encoders import FastEmbedEncoder, HuggingFaceEncoder
    except Exception:
        return None
    try:  # semantic-router 0.0.x / 0.1.x-0.3.x
        from semantic_router import SemanticRouter as router_cls
    except Exception:
        try:  # semantic-router >= 1.0
            from semantic_router.routers import IndexedRouter as router_cls
        except Exception:
            return None

    def _make_encoder():
        # HuggingFace sentence-transformers first, then FastEmbed (no torch).
        for encoder_cls in (HuggingFaceEncoder, FastEmbedEncoder):
            try:
                return encoder_cls()
            except ImportError:
                continue  # optional extra not installed: expected, not an error
            except Exception as exc:
                print(f"⚠️ Semantic Router encoder unavailable ({encoder_cls.__name__}): {str(exc)[:160]}")
        # No encoder can ever be built here; say so once, clearly.
        print("⚠️ Semantic Router has no usable local encoder; using token overlap. "
              "Install one with: pip install semantic-router[fastembed]")
        return None

    return router_cls, _make_encoder


def _build_route(Route, name: str, examples: List[str], threshold: float):
    """Create a ``Route`` whichever threshold argument the installed version takes.

    Both versions ignore unknown keyword arguments, so a wrong name does not
    raise -- the value is checked afterwards and the other name is tried.
    """
    for field_name in ("score_threshold", "confidence_threshold"):
        try:
            route = Route(name=name, utterances=list(examples), **{field_name: threshold})
        except Exception:
            continue
        if getattr(route, field_name, None) == threshold:
            return route
    return Route(name=name, utterances=list(examples))


def _build_router(router_cls, encoder, routes):
    """Create a router whichever encoder argument the installed version takes."""
    for kwargs in ({"auto_sync": "local"}, {}):
        try:
            return router_cls(encoder=encoder, routes=routes, **kwargs)
        except TypeError:
            continue
    return router_cls(encoder=encoder, routes=routes)


def _choice_result(choice) -> Tuple[str, float]:
    """Normalise a route choice: 0.0.x uses ``similarity_score``, 1.x ``confidence``."""
    name = getattr(choice, "name", "") or ""
    score = getattr(choice, "similarity_score", None)
    if score is None:
        score = getattr(choice, "confidence", 0.0)
    try:
        return name, float(score or 0.0)
    except (TypeError, ValueError):
        return name, 0.0


class SemanticRouterEngine:
    """Thin wrapper that keeps one local encoder alive and routes to intents.

    ``route`` never raises: a missing package, an unusable encoder or a bad
    model output all return ``None`` so the caller can use its lexical
    fallback. Failures are retried after ``_RETRY_AFTER_SECONDS`` so a model
    that finished downloading later is picked up without a restart.
    """

    def __init__(self, threshold: float = _MIN_MATCH_SCORE) -> None:
        self.threshold = threshold
        self._api = _load_api()
        # Declared before anything that can fail, so callers can always read it.
        self.engine = "semantic-router" if self._api else "token-overlap"
        self._encoder = None
        self._router = None
        self._signature: Optional[tuple] = None
        self._failed_at: Optional[float] = None

    def invalidate(self) -> None:
        """Force the next ``route`` call to rebuild the router (e.g. new intents)."""
        self._router = None
        self._signature = None

    @property
    def available(self) -> bool:
        return self._api is not None

    def _failed(self, exc: Exception | None = None) -> None:
        """Park the router after a failure; retried later, never retried per turn."""
        if exc is not None:
            print(f"⚠️ Semantic Router unavailable, using token overlap: {type(exc).__name__}: {str(exc)[:160]}")
        self._encoder = None
        self._router = None
        self._signature = None
        self._failed_at = _now()

    def _make_router(self, intents: Dict[str, List[str]]):
        router_cls, make_encoder = self._api  # type: ignore[misc]
        signature = self._current_signature(intents)
        if not signature:
            return None, signature
        from semantic_router import Route  # noqa: F401 - required by both versions

        with _encoder_lock:
            if self._encoder is None:
                self._encoder = make_encoder()
            if self._encoder is None:
                self._failed()
                return None, signature
            routes = [
                _build_route(Route, name, list(examples), self.threshold)
                for name, examples in signature
            ]
            return _build_router(router_cls, self._encoder, routes), signature

    def route(self, phrase: str, intents: Dict[str, List[str]]) -> Optional[Tuple[str, float]]:
        """Return ``(intent_type, similarity)`` above threshold, else ``None``."""
        if not self.available or not phrase.strip() or not intents:
            return None
        if self._failed_at is not None and _now() - self._failed_at < _RETRY_AFTER_SECONDS:
            return None
        try:
            if self._router is None or self._signature != self._current_signature(intents):
                self._router, self._signature = self._make_router(intents)
                if self._router is not None:
                    self.engine = "semantic-router"  # only true once it is built
            if self._router is None:
                return None
            name, similarity = _choice_result(self._router(phrase))
        except Exception as exc:
            self._failed(exc)
            return None
        if not name or name not in intents or similarity < self.threshold:
            return None
        return name, similarity

    @staticmethod
    def _current_signature(intents: Dict[str, List[str]]) -> tuple:
        return tuple(
            (intent_type, tuple(examples[-_MAX_EXAMPLES_PER_TYPE:]))
            for intent_type, examples in sorted(intents.items())
            if examples
        )


def _now() -> float:
    import time

    return time.monotonic()


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
        # Two keywords is the floor for a lexical match; it is also the floor for
        # asking the embeddings, which match any short fragment too eagerly.
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
        self.router_engine = self.router.engine
        if semantic is not None and semantic[1] > best_score:
            # Vector matches catch paraphrases token overlap misses, but only
            # replace a lexical match when strictly more confident.
            return semantic
        if best_type is not None and best_score >= _MIN_INTENT_MATCH_SCORE:
            return best_type, best_score
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
