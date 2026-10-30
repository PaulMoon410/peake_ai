#!/usr/bin/env python3
"""Strict schemas for the two learning JSON files the app reads and writes.

``online_learning_buffer.json`` (written by ``peakebot._queue_online_learning``)
and ``learning_queue.json`` (topic queue) are edited by several code paths and
survive across versions. Loading and saving them through these models keeps one
malformed entry from breaking the whole file, and rejects anything that would
later be trained on.

Uses Pydantic when it is installed and falls back to an equivalent stdlib
check when it is not, so the assistant still runs on a bare Python install.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # pragma: no cover - depends on the install
    from pydantic import BaseModel, ConfigDict, Field, field_validator

    PYDANTIC_AVAILABLE = True
except ImportError:  # pragma: no cover
    PYDANTIC_AVAILABLE = False
    BaseModel = object  # type: ignore[assignment,misc]
    ConfigDict = dict  # type: ignore[assignment,misc]
    Field = None  # type: ignore[assignment]

MAX_PROMPT_CHARS = 4000
MAX_RESPONSE_CHARS = 8000
MAX_TOPIC_CHARS = 120


class LearningItem:
    """One scored interaction queued for later model training."""

    __slots__ = ("prompt", "response", "source", "quality", "timestamp")

    def __init__(self, prompt: str, response: str, source: str = "chat",
                 quality: float = 0.0, timestamp: Optional[str] = None):
        if not isinstance(prompt, str) or not isinstance(response, str):
            raise ValueError("prompt and response must be strings")
        self.prompt = prompt
        self.response = response
        self.source = str(source or "chat")
        try:
            self.quality = float(quality)
        except (TypeError, ValueError):
            raise ValueError("quality must be a number")
        self.timestamp = str(timestamp) if timestamp else datetime.now().isoformat()
        if not self.prompt.strip() or not self.response.strip():
            raise ValueError("prompt and response cannot be empty")
        if len(self.prompt) > MAX_PROMPT_CHARS or len(self.response) > MAX_RESPONSE_CHARS:
            raise ValueError("interaction is too long to queue")
        if not 0.0 <= self.quality <= 1.0:
            raise ValueError("quality must be between 0 and 1")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt, "response": self.response, "source": self.source,
            "quality": self.quality, "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "LearningItem":
        if not isinstance(value, dict):
            raise ValueError("item must be a JSON object")
        return cls(
            prompt=value.get("prompt", ""), response=value.get("response", ""),
            source=value.get("source", "chat"), quality=value.get("quality", 0.0),
            timestamp=value.get("timestamp"),
        )


if PYDANTIC_AVAILABLE:

    class LearningItemModel(BaseModel):  # type: ignore[misc]
        """Validated shape of one online_learning_buffer.json item."""

        model_config = ConfigDict(extra="ignore")

        prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
        response: str = Field(min_length=1, max_length=MAX_RESPONSE_CHARS)
        source: str = "chat"
        quality: float = Field(ge=0.0, le=1.0)
        timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

        @field_validator("prompt", "response")
        @classmethod
        def _not_blank(cls, value: str) -> str:
            if not value.strip():
                raise ValueError("must not be blank")
            return value

        @field_validator("timestamp")
        @classmethod
        def _iso_timestamp(cls, value: str) -> str:
            datetime.fromisoformat(value)
            return value

    class LearningBuffer(BaseModel):  # type: ignore[misc]
        model_config = ConfigDict(extra="ignore")

        items: List[LearningItemModel] = Field(default_factory=list)

        @field_validator("items")
        @classmethod
        def _bounded(cls, value: List[LearningItemModel]) -> List[LearningItemModel]:
            return value[-200:]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_topics(path: Path) -> Tuple[List[str], int]:
    """Return (valid topics, dropped count) for learning_queue.json."""
    data = _load_json(path)
    raw = data.get("topics") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return [], 0
    topics: List[str] = []
    dropped = 0
    for entry in raw:
        text = entry.strip() if isinstance(entry, str) else ""
        if not text or len(text) > MAX_TOPIC_CHARS:
            dropped += 1
            continue
        if text.casefold() not in {topic.casefold() for topic in topics}:
            topics.append(text)
    return topics, dropped


def save_topics(path: Path, topics: List[str]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(topics[:200], indent=2), encoding="utf-8")
    temp.replace(target)


def load_learning_buffer(path: Path) -> Tuple[List[LearningItem], int]:
    """Return (valid items, number of dropped items); never raises on bad data."""
    data = _load_json(path)
    if isinstance(data, dict):
        raw = data.get("items")
    elif isinstance(data, list):
        raw = data
    else:
        raw = None
    if not isinstance(raw, list):
        raw = []
    valid: List[LearningItem] = []
    dropped = 0
    for entry in raw:
        try:
            if PYDANTIC_AVAILABLE:
                model = LearningItemModel.model_validate(entry)
                valid.append(LearningItem.from_dict(model.model_dump()))
            else:
                valid.append(LearningItem.from_dict(entry))
        except Exception:
            dropped += 1
    return valid[-200:], dropped


def save_learning_buffer(path: Path, items: List[LearningItem]) -> None:
    """Write the buffer atomically so a crash cannot leave half a JSON file."""
    payload = {"items": [item.to_dict() for item in items[-200:]]}
    if PYDANTIC_AVAILABLE:
        try:
            payload = LearningBuffer.model_validate(payload).model_dump()
        except Exception:
            # Persist whatever still validates instead of losing the whole buffer.
            kept = []
            for entry in payload["items"]:
                try:
                    kept.append(LearningItemModel.model_validate(entry).model_dump())
                except Exception:
                    continue
            payload = {"items": kept}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(target)
