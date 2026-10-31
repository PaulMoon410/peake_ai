import logging
#!/usr/bin/env python3
"""
g4f integration for the AI system.
Provides free access to various AI models through the g4f library.
"""

import logging
from typing import Dict, Any, Optional

try:
    from g4f.client import Client
    G4F_AVAILABLE = True
except ImportError:
    G4F_AVAILABLE = False
    logging.warning("g4f package not installed. Install with: pip install -U g4f[all]")

logger = logging.getLogger(__name__)

def _ai_chat_g4f(system_prompt: str, user_prompt: str, model: str = None) -> Optional[str]:
    """
    Query the g4f service for AI responses using the standardized client.

    Args:
        system_prompt: System instruction for the AI
        user_prompt: User message/query
        model: Optional specific model to use (e.g., "gpt-4o", "deepseek-v3", "gemini-pro")

    Returns:
        AI response text or None if failed
    """
    if not G4F_AVAILABLE:
        logger.error("g4f package not available")
        return None

    try:
        # Initialize the standardized G4F client
        client = Client()

        # Create a chat completion request
        response = client.chat.completions.create(
            model=model or "gpt-3.5-turbo",  # Default model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            # Optional parameters
            temperature=0.7,
            top_p=0.9,
            stream=False,  # Set to True for streaming if needed
        )

        # Extract the response content
        content = response.choices[0].message.content
        logger.info(f"g4f response received using model: {model or 'default'}")
        return str(content).strip() if content else None

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
        "gpt-4o",  # Default high-quality model
        "gpt-3.5-turbo",  # Fast model
        "deepseek-v3",  # Alternative model
        "gemini-pro",  # Google model
        "llama",  # Meta model
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
