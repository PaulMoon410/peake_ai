"""Independent server API contributors; never simulate extension execution."""

from concurrent.futures import ThreadPoolExecutor

import peakebot


def collect_server_api_pool(prompt):
    providers = [
        ("google", peakebot.GOOGLE_API_KEY, peakebot._ai_chat_google),
        ("groq", peakebot.GROQ_API_KEY, peakebot._ai_chat_groq),
        ("openrouter", peakebot.OPENROUTER_API_KEY, peakebot._ai_chat_openrouter),
    ]
    configured = [(name, query) for name, key, query in providers if key]
    if len(configured) < 2:
        raise RuntimeError("Configure at least two independent non-Harold server API providers")
    system = (
        "You are an independent assistant answering the user's question. "
        "Give concise reasoning and state uncertainty. Do not run tools or claim file changes. "
        "Do not pretend to be Cline, Kilo, CodeGeeX or Harold."
    )

    def query_provider(provider):
        name, query = provider
        base = {"name": name, "source": "server-api"}
        try:
            answer = query(system, prompt)
        except (RuntimeError, ValueError, OSError, peakebot.requests.RequestException) as exc:
            return {**base, "error": f"Provider request failed: {type(exc).__name__}"}
        if not isinstance(answer, str) or not answer.strip():
            return {**base, "error": "Provider returned no usable answer; inspect server provider logs"}
        if len(answer) > 4000:
            return {**base, "error": "Provider answer exceeds 4,000 characters; nothing was truncated"}
        return {**base, "answer": answer}

    # Existing provider adapters retain their configured HTTP/model timeouts.
    with ThreadPoolExecutor(max_workers=len(configured)) as executor:
        return list(executor.map(query_provider, configured))
