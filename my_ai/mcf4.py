#!/usr/bin/env python3
"""MCF4 — Memory Compact Format version 4.

A compact, AI-friendly, pipe-delimited record format for memory storage.

Record layout (7 fixed fields, pipe-separated):
    id|date|category|keywords|note|source|lineage

Escaping:
    \\|   -> literal pipe in a field
    \\\\  -> literal backslash

Empty fields are written as ``||`` (nothing between pipes).  Keywords are
space-separated inside the keywords field (same vocabulary as MCF3).

Example line:
    abc123def456|2026-10-27|Knowledge|python coding script|write a hello world script|https://example.com|

A shard file may optionally be zlib-compressed (transparent on read/write).
"""

from __future__ import annotations

import io
import zlib
from typing import Any

__version__ = "1"

_HEADER = f"MCF4 v{__version__}\n"
_FIELD_COUNT = 7


def _escape(value: str) -> str:
    """Escape backslash and pipe for safe pipe-delimited transport."""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def _unescape(value: str) -> str:
    """Reverse ``_escape``."""
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt == "|":
                out.append("|")
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(ch)
                out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def encode_record(record: dict[str, str]) -> str:
    """Encode one memory record as a single MCF4 line.

    Field order: id, date, category, keywords, note, source, lineage.
    Missing/empty fields become empty strings between pipes.
    """
    fields = [
        record.get("i", ""),
        record.get("d", ""),
        record.get("c", "Knowledge"),
        record.get("k", ""),
        record.get("n", ""),
        record.get("s", ""),
        record.get("l", ""),
    ]
    return "|".join(_escape(f) for f in fields) + "\n"


def decode_record(line: str) -> dict[str, str] | None:
    """Decode one MCF4 line into a memory record dict.

    Returns ``None`` when the line is blank, a comment, or malformed.
    """
    line = line.rstrip("\n").rstrip("\r")
    if not line or line.startswith("#"):
        return None
    if line.startswith("MCF4 "):
        return None  # version header, not a record

    parts = _split_unescaped(line)
    if len(parts) < _FIELD_COUNT:
        return None

    # Unescape each field (\\| -> |, \\\\ -> \).
    parts = [_unescape(p) for p in parts]

    return {
        "i": parts[0],
        "d": parts[1],
        "c": parts[2],
        "k": parts[3],
        "n": parts[4],
        "s": parts[5],
        "l": parts[6] if len(parts) > 6 else "",
    }


def _split_unescaped(line: str) -> list[str]:
    """Split on unescaped pipes, honoring \\| and \\\\ escapes."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            current.append(line[i])
            current.append(line[i + 1])
            i += 2
        elif ch == "|":
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(ch)
            i += 1
    parts.append("".join(current))
    return parts


def encode_shard(records: list[dict[str, str]], compress: bool = False) -> bytes:
    """Encode a list of records into a shard byte blob.

    When ``compress`` is true the payload is zlib-compressed (level 6).
    """
    lines = [_HEADER] + [encode_record(r) for r in records]
    payload = "".join(lines).encode("utf-8")
    if compress:
        payload = zlib.compress(payload, level=6)
    return payload


def decode_shard(data: bytes, compress: bool = False) -> list[dict[str, str]]:
    """Decode a shard byte blob into a list of record dicts."""
    if compress:
        data = zlib.decompress(data)
    text = data.decode("utf-8")
    records: list[dict[str, str]] = []
    for line in text.splitlines():
        record = decode_record(line)
        if record is not None:
            records.append(record)
    return records


def shard_magic(compress: bool = False) -> str:
    """Return the file extension hint for a shard."""
    return ".mc4.z" if compress else ".mc4"
