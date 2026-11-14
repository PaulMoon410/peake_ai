"""A bounded Ollama wire-protocol adapter for Harold's own neural model."""

import hmac
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge


def register_ollama_adapter(app, get_api_key, rate_limit, generation_lock, get_model):
    adapter = Blueprint("ollama_adapter", __name__, url_prefix="/ollama")

    def error(message, status):
        return jsonify({"error": message}), status

    @adapter.errorhandler(RequestEntityTooLarge)
    def too_large(exc):
        return error("request exceeds 1 MiB", 413)

    @adapter.before_request
    def authenticate():
        key = get_api_key()
        header = request.headers.get("Authorization", "")
        incoming = header[7:].strip() if header.startswith("Bearer ") else ""
        if not key or not incoming or not hmac.compare_digest(incoming.encode(), key.encode()):
            return error("invalid api key or adapter not configured", 401)

    def metadata():
        checkpoint = Path(__file__).with_name("language_model.npz")
        try:
            stat = checkpoint.stat()
        except FileNotFoundError:
            return None
        return {
            "name": "harold:latest", "model": "harold:latest",
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "size": stat.st_size, "digest": "",
            "details": {"format": "npz", "family": "harold", "families": ["harold"]},
        }

    @adapter.get("/")
    @adapter.get("/api/version")
    def version():
        return jsonify({"version": "0.0.0", "adapter": "harold", "ollama_runtime": False})

    @adapter.get("/api/tags")
    def tags():
        info = metadata()
        if info is None:
            return error("Harold model checkpoint is unavailable", 503)
        return jsonify({"models": [info]})

    def read_payload():
        if not request.is_json:
            raise ValueError("application/json required")
        if request.content_length is not None and request.content_length > 1024 * 1024:
            raise RequestEntityTooLarge()
        raw = request.stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise RequestEntityTooLarge()
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        if payload.get("model") not in ("harold", "harold:latest"):
            raise ValueError("model must be harold or harold:latest")
        return payload

    @adapter.post("/api/show")
    def show():
        try:
            payload = read_payload()
            if set(payload) - {"model", "verbose"}:
                raise ValueError("unsupported show fields")
        except ValueError as exc:
            return error(str(exc), 400)
        info = metadata()
        if info is None:
            return error("Harold model checkpoint is unavailable", 503)
        return jsonify({
            "details": info["details"], "capabilities": ["completion"],
            "model_info": {"harold.backend": "NeuralLanguageModel"},
        })

    def complete(chat):
        try:
            payload = read_payload()
            allowed = {"model", "stream", "options"}
            allowed |= {"messages"} if chat else {"prompt", "system"}
            if set(payload) - allowed:
                raise ValueError("unsupported fields: " + ", ".join(sorted(set(payload) - allowed)))
            stream = payload.get("stream", True)
            if not isinstance(stream, bool):
                raise ValueError("stream must be a boolean")
            options = payload.get("options", {})
            if not isinstance(options, dict) or set(options) - {"temperature", "num_predict"}:
                raise ValueError("only temperature and num_predict options are supported")
            temperature = options.get("temperature", 0.7)
            length = options.get("num_predict", 50)
            if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
                    or not math.isfinite(temperature) or not 0 < temperature <= 2):
                raise ValueError("temperature must be greater than 0 and at most 2")
            if isinstance(length, bool) or not isinstance(length, int) or not 1 <= length <= 256:
                raise ValueError("num_predict must be an integer from 1 to 256")
            if chat:
                messages = payload.get("messages")
                if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
                    raise ValueError("messages must contain 1 to 32 turns")
                for message in messages:
                    if (not isinstance(message, dict) or set(message) != {"role", "content"}
                            or message["role"] not in ("system", "user", "assistant")
                            or not isinstance(message["content"], str)):
                        raise ValueError("messages must contain only text role and content fields")
                if messages[-1]["role"] != "user" or not messages[-1]["content"].strip():
                    raise ValueError("last turn must be a non-empty user message")
                # The native model takes text, not a chat-template token sequence.
                prompt = "\n".join(f'{m["role"]}: {m["content"]}' for m in messages)
            else:
                prompt = payload.get("prompt")
                system = payload.get("system", "")
                if not isinstance(prompt, str) or not prompt.strip() or not isinstance(system, str):
                    raise ValueError("prompt must be non-empty text and system must be text")
                prompt = f"system: {system}\nuser: {prompt}" if system else prompt
            if len(prompt) > 100000:
                raise ValueError("input exceeds 100,000 characters")
        except RequestEntityTooLarge:
            return error("request exceeds 1 MiB", 413)
        except ValueError as exc:
            return error(str(exc), 400)

        client = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if not rate_limit(client):
            return error("rate limit exceeded", 429)
        if not generation_lock.acquire(timeout=1):
            return error("Harold is busy; try again shortly", 503)
        try:
            text = get_model().generate_response(prompt, max_length=length, temperature=temperature)
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("native model returned no text")
        except (RuntimeError, ValueError, OSError, ArithmeticError) as exc:
            current_app.logger.exception("Harold native Ollama-adapter generation failed")
            return error("native model generation failed", 503)
        finally:
            generation_lock.release()

        base = {"model": "harold:latest", "created_at": datetime.now(timezone.utc).isoformat()}
        field = {"message": {"role": "assistant", "content": text}} if chat else {"response": text}
        result = {**base, **field, "done": True, "done_reason": "stop"}
        if not stream:
            return jsonify(result)
        # Generation is buffered; NDJSON framing is not token-by-token inference.
        empty = {"message": {"role": "assistant", "content": ""}} if chat else {"response": ""}
        chunks = ({**base, **field, "done": False},
                  {**base, **empty, "done": True, "done_reason": "stop"})
        return Response("".join(json.dumps(chunk) + "\n" for chunk in chunks),
                        mimetype="application/x-ndjson")

    @adapter.post("/api/chat")
    def chat():
        return complete(True)

    @adapter.post("/api/generate")
    def generate():
        return complete(False)

    app.register_blueprint(adapter)
