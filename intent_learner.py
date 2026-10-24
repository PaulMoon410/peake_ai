
from typing import Dict, List, Optional, Any

# Constants imported from peakebot

class IntentLearner:
    """Learns phrase-to-action mappings from conversation, applied linguistically.

    Harold watches which user wordings lead to successful actions (math, memory,
    search, and website reading) and stores those phrase→intent mappings in
    MCF3 memory. Later, free-form input that semantically matches a learned phrase
    triggers the same action without requiring an exact command.
    """

    def __init__(self) -> None:
        from peakebot import _get_mcf_memory_store
        self.store = _get_mcf_memory_store()
        self.intents: Dict[str, List[str]] = {}
        self._load_intents()

    def _load_intents(self) -> None:
        """Load existing intents from memory store."""
        try:
            from peakebot import _get_mcf_memory_store, _INTENT_CATEGORY, _ALLOWED_INTENT_TYPES, _MAX_INTENT_EXAMPLES_PER_TYPE
            store = _get_mcf_memory_store()
            intents = store.get(_INTENT_CATEGORY, {})
            for intent_type, examples in intents.items():
                if intent_type in _ALLOWED_INTENT_TYPES:
                    self.intents[intent_type] = examples[:_MAX_INTENT_EXAMPLES_PER_TYPE]
        except Exception as e:
            print(f"⚠️ Failed to load intents: {e}")

    def add_intent(self, intent_type: str, phrase: str) -> bool:
        """Add a phrase-to-intent mapping if valid."""
        if intent_type not in _ALLOWED_INTENT_TYPES:
            return False

        # Initialize if new type
        if intent_type not in self.intents:
            self.intents[intent_type] = []

        # Add if not already present
        if phrase not in self.intents[intent_type]:
            self.intents[intent_type].append(phrase)

            # Save to memory store
            try:
                from peakebot import _get_mcf_memory_store, _INTENT_CATEGORY
                store = _get_mcf_memory_store()
                store.set(_INTENT_CATEGORY, self.intents)
                return True
            except Exception as e:
                print(f"⚠️ Failed to save intent: {e}")
                return False

        return False

    def get_intent(self, phrase: str) -> Optional[str]:
        """Get the intent type that best matches the phrase."""
        if not self.intents:
            return None

        # Simple matching - in a real system, this would use NLP
        best_match = None
        best_score = 0

        for intent_type, examples in self.intents.items():
            for example in examples:
                # Calculate match score
                score = self._calculate_similarity(phrase, example)
                if score > best_score and score >= 0.4:
                    best_score = score
                    best_match = intent_type

        return best_match

    def _calculate_similarity(self, phrase1: str, phrase2: str) -> float:
        """Calculate similarity between two phrases."""
        # Simple word overlap - in a real system, this would use embeddings
        words1 = set(phrase1.lower().split())
        words2 = set(phrase2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

# Import constants from peakebot
from peakebot import (
    _INTENT_CATEGORY,
    _ALLOWED_INTENT_TYPES,
    _MAX_INTENT_EXAMPLES_PER_TYPE,
    _MIN_INTENT_MATCH_SCORE
)
