#!/usr/bin/env python3
"""Enhanced coding agent with broken English support and improved memory handling."""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
from collections.abc import Callable
import urllib.error
import urllib.request

from memory_store import MemoryStore
from broken_english_handler import BrokenEnglishHandler

# Import the original coding agent components
from coding_agent import CodingWorkspace, SYSTEM_PROMPT, TOOLS, DEFAULT_OLLAMA_URL, DEFAULT_MODEL

class EnhancedCodingWorkspace(CodingWorkspace):
    """Extended coding workspace with broken English support and optimized memory handling."""

    def __init__(
        self,
        root: Path,
        memory_recall: Callable[[str], str] | None = None,
        memory_categories: Callable[[], list[str]] | None = None,
        ftp_sync: bool = False,
        local_memory_only: bool = False,
    ) -> None:
        super().__init__(root, memory_recall, memory_categories)
        self.ftp_sync = ftp_sync
        self.local_memory_only = local_memory_only
        self.broken_english_handler = BrokenEnglishHandler(self.memory_store) if memory_recall else None

    def process_query(self, query: str) -> str:
        """Process a query with broken English support."""
        if self.broken_english_handler:
            # Correct the query first
            corrected_query, corrections = self.broken_english_handler.correct_text(query)
            if corrected_query != query:
                print(f"Query corrected: '{query}' -> '{corrected_query}'")
                # Optionally store the correction for learning
                for original, corrected in corrections:
                    self.broken_english_handler.add_pattern(original, corrected)
        else:
            corrected_query = query

        return corrected_query

    def recall_memory(self, query: str) -> str:
        """Enhanced memory recall with broken English support."""
        # Process the query first
        processed_query = self.process_query(query)

        # Use the original recall method
        return super().recall_memory(processed_query)

    def sync_with_ftp(self) -> None:
        """Sync memory with FTP only if explicitly enabled and not in local-only mode."""
        if self.local_memory_only:
            print("Operating in local memory only mode - skipping FTP sync")
            return

        if not self.ftp_sync:
            print("FTP sync is disabled")
            return

        if self.memory_store.ftp_configured:
            print("Syncing with FTP...")
            success, message = self.memory_store.sync_with_ftp()
            if success:
                print("FTP sync completed successfully")
            else:
                print(f"FTP sync failed: {message}")
        else:
            print("FTP is not configured")

    def save_to_local_memory(self, content: str, category: str = "Code/Notes") -> None:
        """Save content to local memory without FTP dependency."""
        self.memory_store.add(content, category=category)

        # If we're not syncing with FTP, we need to ensure local persistence
        if self.local_memory_only:
            self.memory_store._write_local()

    def find_similar_code(self, code_snippet: str) -> list:
        """Find similar code snippets in memory."""
        if not self.broken_english_handler:
            return []

        # Use the broken English handler to find similar phrases
        similar = self.broken_english_handler.find_similar_phrases(code_snippet)

        # Filter for code-related categories
        results = []
        for phrase, score in similar:
            # Check if this phrase is from a code-related category
            # This is a simplified check - you could make it more sophisticated
            if any(cat in phrase.lower() for cat in ["code", "programming", "python", "function", "class"]):
                results.append((phrase, score))

        return results


def create_enhanced_coding_agent(
    project_root: str,
    memory_store: MemoryStore,
    use_ftp: bool = False,
    local_memory_only: bool = False,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_MODEL,
) -> EnhancedCodingWorkspace:
    """Create an enhanced coding agent with broken English support."""

    # Create the enhanced workspace
    workspace = EnhancedCodingWorkspace(
        root=Path(project_root).resolve(),
        memory_recall=memory_store.recall_details,
        memory_categories=memory_store.categories,
        ftp_sync=use_ftp,
        local_memory_only=local_memory_only,
    )

    # Initialize the memory store if needed
    if local_memory_only:
        memory_store._write_local()

    # Sync with FTP if enabled
    workspace.sync_with_ftp()

    return workspace


# Example usage
if __name__ == "__main__":
    # Example of how to use the enhanced coding agent
    project_root = "."

    # Create memory store with local-only option
    memory_store = MemoryStore(Path(project_root) / "memory.jsonl")

    # Create enhanced coding agent (local memory only)
    agent = create_enhanced_coding_agent(
        project_root=project_root,
        memory_store=memory_store,
        use_ftp=False,
        local_memory_only=True
    )

    # Example of handling broken English
    broken_query = "i need help with my code it isnt working"
    corrected_query = agent.process_query(broken_query)
    print(f"Original: {broken_query}")
    print(f"Corrected: {corrected_query}")

    # Example of finding similar code
    sample_code = "def hello_world():"
    similar_code = agent.find_similar_code(sample_code)
    print(f"Similar code to '{sample_code}':")
    for code, score in similar_code:
        print(f"- {code} (similarity: {score:.2f})")
