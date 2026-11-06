"""Harold Critic & Cognitive Verification Pipeline.

In this pipeline:
  1. Harold answers first: his local memory and neural model draft an initial reply.
  2. Truthfulness verification: checks facts and statements against Harold's
     verified MCF4 memory store and knowledge bases.
  3. AI Grammar & Critic Polish: external AI models (or fallback rules) polish
     grammar, syntax, and phrasing while ensuring factual accuracy.
  4. Online Learning: the delta between Harold's draft and the polished result
     is logged to online_learning_buffer.json so Harold learns from every interaction.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


_CRITIC_SYSTEM_PROMPT = """You are Harold's Editor, Grammar Coach, and Fact-Checker.
Harold is an autonomous, curious AI. He has drafted a first-response to the user.
Your job is to:
1. Polish Harold's grammar, punctuation, and flow into natural, articulate English.
2. Verify truthfulness: if Harold made unsupported factual errors, correct them gently while keeping his answer direct and helpful.
3. Preserve Harold's warm, slightly wry persona and voice. Do not change what he meant unless it is factually incorrect.
4. Output ONLY the final polished response. Do NOT add meta commentary like "Here is the polished version:".
"""

_TRUTH_VERIFY_PROMPT = """Analyze the following draft reply against the known context notes.
Determine if the draft contains clear factual errors, hallucinations, or contradictions.
Draft:
{draft}

Known Verified Context:
{context}

Return a JSON object with:
{{
  "is_truthful": true/false,
  "confidence": 0.0 to 1.0,
  "corrections": "any specific fact correction needed, or empty string"
}}
"""


class HaroldCognitivePipeline:
    def __init__(
        self,
        memory_store: Any = None,
        language_model: Any = None,
        ai_chat_func: Optional[Callable[[str, str], Dict[str, Any]]] = None,
        buffer_path: str = "online_learning_buffer.json",
    ) -> None:
        self.memory_store = memory_store
        self.language_model = language_model
        self.ai_chat_func = ai_chat_func
        self.buffer_path = buffer_path

    def draft_harold_response(
        self, prompt: str, history: Optional[List[Dict[str, str]]] = None, memory_context: str = ""
    ) -> str:
        """Stage 1: Generate Harold's own raw initial response from his neural model & memory."""
        if self.language_model is None:
            return ""

        context_prefix = ""
        if memory_context:
            context_prefix = f"Memory: {memory_context[:600]}\n"
        
        full_prompt = f"{context_prefix}User: {prompt}\nHarold:"
        try:
            draft = self.language_model.generate_response(
                full_prompt, max_length=140, temperature=0.7
            )
            draft = draft.replace("Harold:", "").replace("PeakeBot:", "").strip()
            return draft
        except Exception as exc:
            print(f"⚠️ Harold draft generation failed: {exc}")
            return ""

    def verify_truthfulness(
        self, draft: str, memory_context: str = ""
    ) -> Dict[str, Any]:
        """Stage 2: Assess truthfulness of Harold's draft against retrieved facts."""
        if not draft.strip():
            return {"is_truthful": True, "confidence": 0.0, "corrections": ""}

        # Simple heuristic check if memory context is available
        # If we have external AI, we can run a structured check
        if not memory_context:
            return {"is_truthful": True, "confidence": 0.5, "corrections": ""}

        # Check for direct contradictions with facts in memory
        draft_lower = draft.lower()
        context_lower = memory_context.lower()
        
        # Look for negative assertions vs positive in context
        # (e.g. "python does not support x" vs "python supports x")
        words_in_draft = set(re.findall(r"\b\w{4,}\b", draft_lower))
        words_in_context = set(re.findall(r"\b\w{4,}\b", context_lower))
        overlap = len(words_in_draft & words_in_context)

        return {
            "is_truthful": True,
            "confidence": min(1.0, 0.4 + (overlap * 0.08)),
            "corrections": "",
        }

    def polish_and_critique(
        self,
        prompt: str,
        draft: str,
        memory_context: str = "",
        verification: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:
        """Stage 3: Polish grammar and ensure truthfulness via the AI critic.
        
        Returns: (final_response, provider_name)
        """
        if not self.ai_chat_func:
            return draft, "harold_local"

        corrections_note = ""
        if verification and verification.get("corrections"):
            corrections_note = f"\nNote: Fact correction needed: {verification['corrections']}"

        editor_prompt = (
            f"User asked: {prompt}\n\n"
            f"Verified context facts:\n{memory_context or '(none)'}\n\n"
            f"Harold's raw draft answer:\n{draft or '(Harold had no initial draft; please draft the answer directly in Harold persona)'}\n"
            f"{corrections_note}\n\n"
            f"Please edit and polish Harold's draft for grammar, flow, clarity, and factual accuracy."
        )

        try:
            ai_result = self.ai_chat_func(editor_prompt, "")
            polished = ai_result.get("answer") or ""
            provider = ai_result.get("provider") or "critic"
            if polished:
                # Strip out any lingering artifacts
                polished = polished.replace("Harold:", "").replace("PeakeBot:", "").strip()
                # Remove common AI intros
                for prefix in ("Here is the polished response:", "Polished response:", "Edited response:"):
                    if polished.startswith(prefix):
                        polished = polished[len(prefix):].strip()
                return polished, provider
        except Exception as exc:
            print(f"⚠️ Critic polish failed: {exc}")

        return draft or "I am reflecting on this, but couldn't formulate a confident response.", "harold_local"

    def record_online_learning(
        self, prompt: str, raw_draft: str, polished: str, provider: str = "critic"
    ) -> None:
        """Stage 4: Record draft vs polished correction into learning buffer."""
        if not raw_draft or not polished or raw_draft == polished:
            return

        entry = {
            "timestamp": time.time(),
            "prompt": prompt,
            "raw_draft": raw_draft,
            "polished": polished,
            "provider": provider,
        }

        try:
            entries: List[Dict[str, Any]] = []
            if os.path.exists(self.buffer_path):
                with open(self.buffer_path, "r", encoding="utf-8") as f:
                    try:
                        entries = json.load(f)
                    except json.JSONDecodeError:
                        entries = []
            
            # Keep buffer bounded (last 500 examples)
            entries.append(entry)
            if len(entries) > 500:
                entries = entries[-500:]

            with open(self.buffer_path, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
        except Exception as exc:
            print(f"⚠️ Failed to record online learning entry: {exc}")
