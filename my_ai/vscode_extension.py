#!/usr/bin/env python3
"""
Visual Studio Code extension for the enhanced AI coding agent.
This demonstrates how to integrate your AI with VS Code.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# Import our enhanced coding agent
from enhanced_coding_agent import create_enhanced_coding_agent, EnhancedCodingWorkspace
from memory_store import MemoryStore

class VSCodeAICodingAgent:
    """Interface between VS Code and the enhanced AI coding agent."""

    def __init__(self, workspace_path: str):
        """Initialize the agent with the specified workspace path."""
        self.workspace_path = Path(workspace_path).resolve()
        self.memory_store = None
        self.agent = None
        self.initialize_agent()

    def initialize_agent(self):
        """Initialize the coding agent with the workspace."""
        try:
            # Create memory store
            memory_path = self.workspace_path / "ai_memory.jsonl"
            self.memory_store = MemoryStore(memory_path)

            # Create enhanced coding agent
            self.agent = create_enhanced_coding_agent(
                project_root=str(self.workspace_path),
                memory_store=self.memory_store,
                use_ftp=False,  # Set to True if FTP sync is needed
                local_memory_only=True  # Prioritize local storage
            )

            # Add some initial knowledge about the workspace
            self._initialize_workspace_memory()

        except Exception as e:
            print(f"Error initializing AI agent: {e}")
            self.agent = None

    def _initialize_workspace_memory(self):
        """Add initial knowledge about the workspace to memory."""
        if not self.agent:
            return

        # Detect project type and add relevant information
        project_type = self._detect_project_type()

        if project_type == "python":
            self.agent.save_to_local_memory(
                "This is a Python project. Use Python coding conventions and best practices.",
                category="Project/Info"
            )
            self.agent.save_to_local_memory(
                "Python code should follow PEP 8 style guide with proper indentation and naming conventions.",
                category="Python/BestPractices"
            )
        elif project_type == "web":
            self.agent.save_to_local_memory(
                "This is a web development project. Consider HTML, CSS, JavaScript, and related frameworks.",
                category="Project/Info"
            )

    def _detect_project_type(self) -> str:
        """Detect the type of project based on file structure."""
        # Check for common project indicators
        if (self.workspace_path / "requirements.txt").exists() or            (self.workspace_path / "setup.py").exists() or            (self.workspace_path / "pyproject.toml").exists():
            return "python"

        if (self.workspace_path / "package.json").exists() or            (self.workspace_path / "index.html").exists():
            return "web"

        if (self.workspace_path / "Cargo.toml").exists():
            return "rust"

        return "unknown"

    def get_memory_categories(self) -> List[str]:
        """Get available memory categories."""
        if self.agent:
            return self.agent.memory_categories()
        return []

    def query_memory(self, query: str) -> str:
        """Query the AI's memory with broken English support."""
        if not self.agent:
            return "AI agent is not initialized."

        return self.agent.recall_memory(query)

    def save_note(self, note: str, category: str = "Notes") -> bool:
        """Save a note to the AI's memory."""
        if not self.agent:
            return False

        try:
            self.agent.save_to_local_memory(note, category)
            return True
        except Exception as e:
            print(f"Error saving note: {e}")
            return False

    def find_similar_code(self, code: str) -> List[Dict[str, Any]]:
        """Find similar code in the AI's memory."""
        if not self.agent:
            return []

        similar = self.agent.find_similar_code(code)
        return [{"code": c, "similarity": s} for c, s in similar]

    def get_code_suggestions(self, context: str, current_code: str) -> List[str]:
        """Get code suggestions based on context and current code."""
        if not self.agent:
            return []

        # Query memory for relevant information
        relevant_info = self.query_memory(context)

        # In a real implementation, you would use the AI model to generate suggestions
        # For this example, we'll return a simple placeholder
        suggestions = [
            f"# AI Suggestion for {context}",
            "# Based on relevant information from memory:",
            f"# {relevant_info[:100]}...",
            "",
            "# Add your implementation here"
        ]

        return suggestions

    def process_broken_english(self, text: str) -> Dict[str, str]:
        """Process text with broken English and return corrected version."""
        if not self.agent or not self.agent.broken_english_handler:
            return {"original": text, "corrected": text, "corrections": []}

        corrected, corrections = self.agent.broken_english_handler.correct_text(text)
        return {
            "original": text,
            "corrected": corrected,
            "corrections": corrections
        }


# VS Code Extension API Mock
class VSCodeExtension:
    """Mock VS Code extension API for demonstration."""

    def __init__(self):
        self.agent = None

    def activate(self, context):
        """Activate the extension."""
        workspace_path = context.workspace_path
        self.agent = VSCodeAICodingAgent(workspace_path)

        # Register commands
        self.register_commands()

        print("AI Coding Agent extension activated")

    def register_commands(self):
        """Register VS Code commands."""
        commands = [
            {
                "command": "aiCodingAgent.queryMemory",
                "callback": self.query_memory
            },
            {
                "command": "aiCodingAgent.saveNote",
                "callback": self.save_note
            },
            {
                "command": "aiCodingAgent.findSimilarCode",
                "callback": self.find_similar_code
            },
            {
                "command": "aiCodingAgent.getSuggestions",
                "callback": self.get_suggestions
            },
            {
                "command": "aiCodingAgent.correctEnglish",
                "callback": self.correct_english
            }
        ]

        for cmd in commands:
            print(f"Registered command: {cmd['command']}")

    def query_memory(self):
        """Handle memory query command."""
        # In a real extension, this would get input from the user
        query = "How do I handle errors in Python?"

        if self.agent:
            result = self.agent.query_memory(query)
            print(f"Memory query result for '{query}':")
            print(result)
        else:
            print("AI agent not initialized")

    def save_note(self):
        """Handle save note command."""
        # In a real extension, this would get input from the user
        note = "Remember to use try-except blocks for error handling"
        category = "Python/BestPractices"

        if self.agent:
            success = self.agent.save_note(note, category)
            if success:
                print(f"Note saved: {note}")
            else:
                print("Failed to save note")
        else:
            print("AI agent not initialized")

    def find_similar_code(self):
        """Handle find similar code command."""
        # In a real extension, this would get input from the user
        code = "def handle_error"

        if self.agent:
            similar = self.agent.find_similar_code(code)
            print(f"Similar code to '{code}':")
            for item in similar:
                print(f"- {item['code']} (similarity: {item['similarity']:.2f})")
        else:
            print("AI agent not initialized")

    def get_suggestions(self):
        """Handle get suggestions command."""
        # In a real extension, this would get context from the editor
        context = "error handling"
        current_code = "def process_data(data):"

        if self.agent:
            suggestions = self.agent.get_code_suggestions(context, current_code)
            print(f"Code suggestions for {context}:")
            for suggestion in suggestions:
                print(suggestion)
        else:
            print("AI agent not initialized")

    def correct_english(self):
        """Handle broken English correction command."""
        # In a real extension, this would get text from the user
        text = "i need help with my code it isnt working"

        if self.agent:
            result = self.agent.process_broken_english(text)
            print(f"Original: {result['original']}")
            print(f"Corrected: {result['corrected']}")
            if result['corrections']:
                print("Corrections made:")
                for original, corrected in result['corrections']:
                    print(f"- {original} -> {corrected}")
        else:
            print("AI agent not initialized")


# Example usage
if __name__ == "__main__":
    # Create a mock VS Code extension
    extension = VSCodeExtension()

    # Activate with a workspace path
    class MockContext:
        def __init__(self, path):
            self.workspace_path = path

    # Use current directory as workspace
    workspace_path = Path.cwd()
    extension.activate(MockContext(str(workspace_path)))

    # Test the commands
    extension.query_memory()
    extension.save_note()
    extension.find_similar_code()
    extension.get_suggestions()
    extension.correct_english()
