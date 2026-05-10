import requests

LOCAL_LLAMA_URL = "http://127.0.0.1:8080/v1/chat/completions"
DEFAULT_SYSTEM_PROMPT = "You are PeakeBot, a helpful AI assistant for the PeakeCoin project."


def ask_local_llama(prompt, system_prompt=None, max_tokens=250):
    """Send a chat completion request to a local llama.cpp-compatible API."""
    user_prompt = (prompt or "").strip()
    if not user_prompt:
        raise ValueError("Prompt cannot be empty.")

    system_text = (system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    payload = {
        "model": "qwen-light",
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": int(max_tokens),
    }

    try:
        response = requests.post(LOCAL_LLAMA_URL, json=payload, timeout=30)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Local llama request failed: {str(exc)}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        body_preview = (response.text or "").strip()
        if len(body_preview) > 300:
            body_preview = body_preview[:300] + "..."
        raise RuntimeError(
            f"Local llama returned HTTP {response.status_code}: {body_preview or 'no response body'}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Local llama returned invalid JSON.") from exc

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError("Local llama response is missing choices[0].message.content.") from exc
