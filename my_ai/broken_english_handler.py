#!/usr/bin/env python3
"""Handler for understanding and correcting broken English in the AI system."""

from __future__ import annotations

import re
import difflib
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
import json
from pathlib import Path

class BrokenEnglishHandler:
    """Handles broken English patterns, corrections, and fuzzy matching."""

    def __init__(self, memory_store):
        """Initialize with a reference to the memory store for persistence."""
        self.memory_store = memory_store
        self.patterns = self._load_patterns()
        self.corrections = self._load_corrections()

    def _load_patterns(self) -> Dict[str, List[str]]:
        """Load common broken English patterns from memory store or defaults."""
        # Try to load from memory store first
        try:
            categories = self.memory_store.categories()
            if "Language/Learning" in categories:
                pattern_records = self.memory_store.recall("broken English patterns", category="Language/Learning")
                patterns = defaultdict(list)
                for record in pattern_records:
                    # Parse pattern and correction from note
                    # Format: "pattern -> correction"
                    if " -> " in record["n"]:
                        pattern, correction = record["n"].split(" -> ", 1)
                        patterns[pattern.strip()].append(correction.strip())
                return dict(patterns)
        except:
            pass

        # Default patterns if nothing in memory store
        return {
            "i is": ["I am"],
            "he is": ["he's"],
            "she is": ["she's"],
            "it is": ["it's"],
            "we is": ["we are"],
            "they is": ["they are"],
            "you is": ["you are"],
            "me am": ["I am"],
            "him is": ["he is"],
            "her is": ["she is"],
            "us am": ["we are"],
            "them is": ["they are"],
            "your": ["you're"],
            "youre": ["you're"],
            "there": ["their", "they're"],
            "thier": ["their"],
            "recieve": ["receive"],
            "recieving": ["receiving"],
            "begining": ["beginning"],
            "writting": ["writing"],
            "readed": ["read"],
            "goes to": ["goes to", "went to"],
            "have": ["has", "had"],
        }

    def _load_corrections(self) -> Dict[str, str]:
        """Load direct corrections from memory store or defaults."""
        # Try to load from memory store first
        try:
            categories = self.memory_store.categories()
            if "Language/Corrections" in categories:
                correction_records = self.memory_store.recall("corrections", category="Language/Corrections")
                corrections = {}
                for record in correction_records:
                    # Parse correction from note
                    # Format: "incorrect -> correct"
                    if " -> " in record["n"]:
                        incorrect, correct = record["n"].split(" -> ", 1)
                        corrections[incorrect.strip()] = correct.strip()
                return corrections
        except:
            pass

        # Default corrections if nothing in memory store
        return {
            "dont": "don't",
            "cant": "can't",
            "wont": "won't",
            "isnt": "isn't",
            "arent": "aren't",
            "wasnt": "wasn't",
            "werent": "weren't",
            "hasnt": "hasn't",
            "havent": "haven't",
            "hadnt": "hadn't",
            "doesnt": "doesn't",
            "didnt": "didn't",
            "couldnt": "couldn't",
            "shouldnt": "shouldn't",
            "wouldnt": "wouldn't",
            "mustnt": "mustn't",
            "mightnt": "mightn't",
            "neednt": "needn't",
            "shant": "shan't",
            "lets": "let's",
            "im": "I'm",
            " youre": " you're",
            "hes": "he's",
            "shes": "she's",
            "its": "it's",
            "thats": "that's",
            "whats": "what's",
            "wheres": "where's",
            "whens": "when's",
            "whys": "why's",
            "hows": "how's",
            "yours": "you're",
            "u": "you",
            "ur": "you're",
            "r": "are",
            "btw": "by the way",
            "lol": "laughing out loud",
            "idk": "I don't know",
            "ikr": "I know, right?",
            "imo": "in my opinion",
            "imho": "in my humble opinion",
        }

    def add_pattern(self, broken: str, correct: str, category: str = "Language/Learning") -> None:
        """Add a new broken English pattern and correction to the memory store."""
        pattern_note = f"{broken} -> {correct}"
        self.memory_store.add(pattern_note, category=category)
        # Update local cache
        if broken not in self.patterns:
            self.patterns[broken] = []
        if correct not in self.patterns[broken]:
            self.patterns[broken].append(correct)

    def add_correction(self, broken: str, correct: str, category: str = "Language/Corrections") -> None:
        """Add a direct correction to the memory store."""
        correction_note = f"{broken} -> {correct}"
        self.memory_store.add(correction_note, category=category)
        # Update local cache
        self.corrections[broken] = correct

    def correct_text(self, text: str) -> Tuple[str, List[Tuple[str, str]]]:
        """Correct broken English in the given text.

        Returns:
            Tuple of (corrected_text, list_of_corrections_made)
        """
        original = text
        corrections_made = []

        # Apply direct corrections first
        for broken, correct in self.corrections.items():
            if broken in text:
                # Use word boundaries to avoid partial matches
                pattern = r'\b' + re.escape(broken) + r'\b'
                corrected = re.sub(pattern, correct, text)
                if corrected != text:
                    corrections_made.append((broken, correct))
                    text = corrected

        # Apply pattern-based corrections
        for broken, correct_options in self.patterns.items():
            if broken in text:
                # For patterns, use the first correction option
                correct = correct_options[0]
                # Use word boundaries to avoid partial matches
                pattern = r'\b' + re.escape(broken) + r'\b'
                corrected = re.sub(pattern, correct, text)
                if corrected != text:
                    corrections_made.append((broken, correct))
                    text = corrected

        return text, corrections_made

    def find_similar_phrases(self, phrase: str, threshold: float = 0.8) -> List[Tuple[str, float]]:
        """Find similar phrases in the memory store using fuzzy matching."""
        similar = []

        # Get all records from memory store
        all_records = self.memory_store.records

        # Compare against each record's note text
        for record in all_records:
            similarity = difflib.SequenceMatcher(None, phrase.lower(), record["n"].lower()).ratio()
            if similarity >= threshold:
                similar.append((record["n"], similarity))

        # Sort by similarity score (highest first)
        similar.sort(key=lambda x: x[1], reverse=True)
        return similar

    def learn_from_interaction(self, user_input: str, corrected: str) -> None:
        """Learn from user interactions to improve correction capabilities."""
        # Analyze the differences and add new patterns/corrections if appropriate
        # This is a simplified version - you could make this much more sophisticated

        # Split into words to compare
        user_words = user_input.lower().split()
        corrected_words = corrected.lower().split()

        # Find the first differing word pair
        for uw, cw in zip(user_words, corrected_words):
            if uw != cw:
                # Add as a direct correction
                self.add_correction(uw, cw)
                break
