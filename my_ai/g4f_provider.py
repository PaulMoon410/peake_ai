#!/usr/bin/env python3
"""
g4f integration for the AI system.
Provides free access to various AI models through the g4f library.
"""

import g4f
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def _ai_chat_g4f(system_prompt: str, user_prompt: str, model: str = None) -> Optional[str]:
    """
    Query the g4f service for AI responses.

    Args:
        system_prompt: System instruction for the AI
        user_prompt: User message/query
        model: Optional specific model to use

    Returns:
        AI response text or None if failed
    """
    try:
        # Combine system and user prompts
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"

        # Try to get a response from g4f
        response = g4f.ChatCompletion.create(
            model=model or "gpt-3.5-turbo",  # Default model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            # Optional parameters
            temperature=0.7,
            top_p=0.9,
            frequency_penalty=0,
            presence_penalty=0,
        )

        logger.info(f"g4f response received using model: {model or 'default'}")
        return str(response).strip()

    except Exception as e:
        logger.error(f"g4f query failed: {str(e)}")
        return None

def _query_g4f_models(system_prompt: str, user_prompt: str) -> Dict[str, str]:
    """
    Query multiple g4f models and return their responses.

    Args:
        system_prompt: System instruction for the AI
        user_prompt: User message/query

    Returns:
        Dictionary mapping model names to responses
    """
    responses = {}

    # List of models to try with g4f
    models_to_try = [
        "gpt-3.5-turbo",
        "gpt-4",
        "gpt-4-turbo",
        "llama",
        "llama-2-7b-chat",
    ]

    for model in models_to_try:
        try:
            response = _ai_chat_g4f(system_prompt, user_prompt, model)
            if response:
                responses[f"g4f-{model}"] = response
                logger.info(f"Received response from g4f model: {model}")
        except Exception as e:
            logger.warning(f"Failed to get response from g4f model {model}: {str(e)}")
            continue

    return responses
