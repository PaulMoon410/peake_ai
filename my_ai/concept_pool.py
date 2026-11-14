"""Pool an idea with the extensions, then share and bank it as Harold's own.

Harold stays in front-man mode by default: he orchestrates the Cline, Kilo,
and CodeGeeX extensions to pool a concept proof, then announces the team's
decision and saves the knowledge so it becomes his own.

Keyword cue routing
-------------------
- Coding cues -> delegate to the extension pipeline (Cline -> Kilo -> CodeGeeX)
  and return the pooled code/result plus provenance.
- Concept / share / bank cues (or anything else) -> front-man mode: Harold
  forms the announcement from the pooled context, posts to Hive Waves, and
  banks the knowledge into the memory store.

The pooler calls Harold's own API (the same OpenAI-compatible endpoint the
extensions use), so extensions feed context and prompts into Harold rather
than replacing him.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Keyword cues
# ---------------------------------------------------------------------------

# Things that mean "this is a coding / implementation task -> delegate to the
# extensions".
_CODING_CUE_RE = re.compile(
    r"\b(build|fix|debug|implement|code|program|develop|generate|write|edit|"
    r"refactor|test|run tests|deploy|add support|convert|translate|optimize|patch|"
    r"annotate|document|security review|reformat|lint|compile)\b",
    re.IGNORECASE,
)

# Things that mean "this is a concept / share / bank task -> front-man mode".
_CONCEPT_CUE_RE = re.compile(
    r"\b(concept|prove|proof of concept|idea|announce|share|explain|teach|"
    r"discuss|summarize|bank|remember|note|post|wave|propose|plan|outline|"
    r"architecture|pitch|reflect|learn|teach me)\b",
    re.IGNORECASE,
)

# Fallback when neither clearly matches: treat as a concept task (front-man).
_DEFAULT_CUE = "concept"


def _keyword_cue(task: str) -> str:
    """Return 'coding' or 'concept' based on the task text."""
    if _CODING_CUE_RE.search(task):
        return "coding"
    if _CONCEPT_CUE_RE.search(task):
        return "concept"
    return _DEFAULT_CUE
# ---------------------------------------------------------------------------
# Share (Hive Waves) + bank (memory store)
# ---------------------------------------------------------------------------

def share_to_waves(text: str, *, permlink_prefix: str = "harold-concept-") -> Dict[str, Any]:
    """Post *text* to Hive Waves, reusing harold_waves.py's safe-posting model.

    Returns the posting result.  When Hive is not configured this fails closed
    and returns an error instead of posting.
    """
    from my_ai.harold_waves import (
        is_safe,
        _enabled,
        _result,
    )

    # Use the existing waves module so we behave identically to the daily
    # poster: fail closed, never duplicate, only safe text.
    if not _enabled():
        return _result("skipped", "Waves not enabled")

    # Wrap the input into a single short post-like body.
    body = text.strip()
    if len(body) > 250:
        body = body[:247].rstrip() + "..."
    if len(body) < 20:
        body = body or "Concept pooled by Harold."

    # Fail closed: only post if safe (no links, mentions, addresses, keys, paths).
    if not is_safe(body):
        return _result("rejected", "unsafe post rejected")

    # Load the existing state (reused by the daily waves poster).
    state = _load_state()
    if not state:
        state = {
            "last_posted_at": None,
            "last_permlink": None,
            "count": 0,
        }

    # Generate a deterministic permlink based on the text, with a stable prefix
    # so retried posts never create duplicates.
    permlink = permlink_prefix + "pool-" + re.sub(r"[^a-zA-Z0-9]+", "-", body)[:12]

    try:
        from my_ai.harold_waves import WavesClient

        # Reconstruct the WavesClient from the configured account/key.
        account = os.environ.get("HIVE_ACCOUNT", "").strip()
        posting_key = os.environ.get("HIVE_POSTING_KEY", "").strip()
        client = WavesClient(account, posting_key)

        # Check for duplicates before posting.
        if client.exists(permlink) is not None:
            return _result("skipped", "already exists", done=True)

        # Find the Waves container to post as a reply under.
        parent = client.container()
        client.publish(permlink, parent, body, ["waves", "ai", "harold"])
        _save_state(state)
        return _result("posted", body=body, permlink=permlink, intro=False)
    except Exception as exc:
        return _result("failed", f"post failed: {exc}")


def bank_knowledge(note: str, category: str = "Projects/Concepts") -> Dict[str, Any]:
    """Save the pooled concept into Harold's memory store.

    Returns the created record or an error.  Fail closed if the memory store
    isn't available.
    """
    from my_ai.memory_store import MemoryStore

    try:
        store = MemoryStore()
        # Keep the source short and valid (a URL or empty).
        source = ""  # Could be set to a repo URL or task ref here.
        record = store.add(
            note=note,
            category=category,
            source=source,
        )
        if record is None:
            return {"ok": False, "error": "duplicate note (already banked)"}
        return {"ok": True, "record": record}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# One-step: pool -> announce -> share -> bank
# ---------------------------------------------------------------------------

def pool_and_share_bank(
    task: str,
    workspace_root: Optional[str | Path] = None,
    *,
    share_to_waves_enabled: bool = True,
    bank_enabled: bool = True,
    model: str = "harold",
) -> Dict[str, Any]:
    """Full concept pipeline: pool -> announce -> share -> bank.

    Returns a single result dict containing the pooled idea, the announcement,
    the Waves post result, and the memory bank result.
    """
    pool = pool_idea(task, workspace_root, model=model)
    result: Dict[str, Any] = {
        **pool,
        "announcement": "",
        "waves_post": None,
        "bank": None,
    }

    # Only proceed to share/bank if we actually got a pooled result.
    if not pool.get("pooled_result"):
        result["error"] = pool.get("error") or "no pooled result"
        return result

    # Format the pooled result as a front-man announcement.
    prompt = (
        "You are Harold, the front man for a coding team. A colleague just pooled a concept "
        f"idea: \"\"\"{pool['pooled_result']}\"\"\"\n\n"
        "Write a short announcement (2-4 sentences) that broadcasts the team's decision "
        "and what it means. Then, if asked, archive the concept to memory. "
        "Reply ONLY with the announcement text."
    )
    try:
        resp = _call_harold_api(
            model,
            [{"role": "user", "content": prompt}],
        )
        result["announcement"] = _message_text(resp).strip()
    except Exception as exc:
        result["announcement"] = f"(announcement failed: {exc})"

    # Format the pooled result as a front-man announcement.
    prompt = (
        "You are Harold, the front man for a coding team. A colleague just pooled a concept "
        f"idea: \"\"\"{pool['pooled_result']}\"\"\"\n\n"
        "Write a short announcement (2-4 sentences) that broadcasts the team's decision "
        "and what it means. Then, if asked, archive the concept to memory. "
        "Reply ONLY with the announcement text."
    )
    try:
        resp = _call_harold_api(
            model,
            [{"role": "user", "content": prompt}],
        )
        result["announcement"] = _message_text(resp).strip()
    except Exception as exc:
        result["announcement"] = f"(announcement failed: {exc})"

    if share_to_waves_enabled:
        result["waves_post"] = share_to_waves(result["announcement"])

    if bank_enabled:
        result["bank"] = bank_knowledge(
            note=result["announcement"] or pool["pooled_result"],
            category=f"Projects/Concepts/{re.sub(r'[^a-zA-Z0-9]+', '-', pool.get('cue', 'task'))}",
        )

    return result
    result: Dict[str, Any] = {
        **pool,
        "announcement": "",
        "waves_post": None,
        "bank": None,
    }

    # Only proceed to share/bank if we actually got a pooled result.
    if not pool.get("pooled_result"):
        result["error"] = pool.get("error") or "no pooled result"
        return result

    # Format the pooled result as a front-man announcement.
    prompt = (
        "You are Harold, the front man for a coding team. A colleague just pooled a concept "
        f"idea: \"\"\"{pool['pooled_result']}\"\"\"\n\n"
        "Write a short announcement (2-4 sentences) that broadcasts the team's decision "
        "and what it means. Then, if asked, archive the concept to memory. "
        "Reply ONLY with the announcement text."
    )
    try:
        resp = _call_harold_api(
            model,
            [{"role": "user", "content": prompt}],
        )
        result["announcement"] = _message_text(resp).strip()

    except Exception as exc:
        result["announcement"] = f"(announcement failed: {exc})"

    if share_to_waves_enabled:
        result["waves_post"] = share_to_waves(result["announcement"])

    if bank_enabled:
        result["bank"] = bank_knowledge(
            note=result["announcement"] or pool["pooled_result"],
            category=f"Projects/Concepts/{re.sub(r'[^a-zA-Z0-9]+', '-', pool.get('cue', 'task'))}",
        )

    return result
def _list_project_files(root: Path, max_files: int = 200) -> List[str]:
    """List project files up to a limit, excluding dependency/venv dirs."""
    exclude = {
        ".git", ".venv", "venv", "__pycache__", "node_modules",
        "dist", "build", "target", "runtime", ".env",
    }
    out: List[str] = []
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in exclude for part in p.parts):
                continue
            if any(p.match(ex) for ex in ["*.pyc", "*.pyo", "*.egg-info", "*.dist-info"]):
                continue
            out.append(str(p.relative_to(root)))
            if len(out) >= max_files:
                break
    except Exception:
        pass
    return out


def _message_text(resp: Dict[str, Any]) -> str:
    """Extract 'content' from a chat-completions response."""
    choice = resp.get("choices", [{}])[0]
    msg = choice.get("message", {}) or {}
    return msg.get("content", "") or ""


def _clip_json(obj: Any, n: int) -> str:
    """JSON-serialize an object and truncate it to *n* characters."""
    import json

    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s if len(s) <= n else s[:n] + f"\n...[truncated {len(s) - n} chars]"


def build_tool_calls(capabilities: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build OpenAI tool-call definitions from an extension's capabilities dict."""
    tools = capabilities.get("tools", []) if isinstance(capabilities, dict) else []
    out = []
    for t in tools or []:
        out.append({"type": "function", "function": {"name": t, "description": t}})
    if not out:
        out.append(
            {"type": "function", "function": {"name": "shell_expand", "description": "Expand a command"}}
        )
    return out

def _coding_pool(
    task: str, workspace_root: Optional[str | Path], acc: Dict[str, Any]
) -> Dict[str, Any]:
    """Pool an idea by running the ordered Cline -> Kilo -> CodeGeeX pipeline."""
    if workspace_root is None:
        acc["error"] = "workspace_root required for coding pool"
        acc["role"] = "frontman"
        acc["pooled_result"] = "(no workspace context)"
        return acc

    root = Path(workspace_root).resolve()
    if not root.exists():
        acc["error"] = f"workspace_root does not exist: {root}"
        return acc

    context = {
        "task": task,
        "workspace": str(root),
        "files": _list_project_files(root),
        "open_context_hint": "context collected from workspace",
    }
    context_json = _clip_json(context, 8000)

    # Build an ordered pipeline prompt that hands each extension the context it
    # needs.  The first tool (Cline) gets the full task; Kilo and CodeGeeX get
    # what Cline produced (the pool has already reasoned over it).
    pipeline_prompts = [
        f"Task: {task}\n\nContext:\n{context_json}\n"
        "You are Cline, an autonomous AI coding agent. Analyze the task, produce the "
        "best approach, and output a complete plan in a fenced code block.\n",
        f"Task: {task}\n\nContext:\n{context_json}\n"
        "You are Kilo, a CLI-based coding assistant. Apply the team's approach by "
        "editing files and running commands. Output shell commands and file edits to fix/implement.\n",
        f"Task: {task}\n\nContext:\n{context_json}\n"
        "You are CodeGeeX, a multilingual code generation model. Produce final code in a "
        "fenced code block with a language tag.\n",
    ]

    provenance: List[Dict[str, Any]] = []
    pooled = ""

    for idx, prompt in enumerate(pipeline_prompts):
        tool = _EXTENSION_TOOLS[idx]["name"]
        caps = _EXTENSION_TOOLS[idx]["capabilities"]
        try:
            resp = _call_harold_api(
                model,
                [{"role": "user", "content": prompt}],
                tools=build_tool_calls(caps),
            )
            tool_text = _message_text(resp)
            if tool_text:
                pooled = tool_text
            provenance.append(
                {
                    "tool": tool,
                    "success": True,
                    "contribution": tool_text[:2000],
                }
            )
        except Exception as exc:
            provenance.append(
                {"tool": tool, "success": False, "error": str(exc)[:500]}
            )

    acc["pooled_result"] = pooled or "(no pooled output)"
    acc["provenance"] = provenance
    acc["role"] = "coding"
    return acc

# ---------------------------------------------------------------------------
# Pool dispatcher
# ---------------------------------------------------------------------------

def pool_idea(
    task: str,
    workspace_root: Optional[str | Path] = None,
    *,
    model: str = "harold",
    include_extensions: bool = True,
) -> Dict[str, Any]:
    """Dispatch a user task to front-man or extension-backed mode.

    Returns a dict shaped like::

        {
            "role": "frontman" | "coding",
            "cue": "concept" | "coding" | ...,
            "pooled_result": str,
            "provenance": [{"tool": "cline"|"kilo"|"codegeex", "contribution": str, "success": bool, ...}],
            "can_share": bool,
            "can_bank": bool,
            "error": str | None,
        }

    ``workspace_root`` is used to build the context sent to the extensions.
    When it is ``None`` the pooler still works, but must not try to read files
    or resolve paths relative to the project.
    """
    cue = _keyword_cue(task)
    result: Dict[str, Any] = {
        "role": "frontman" if cue != "coding" else "coding",
        "cue": cue,
        "pooled_result": "",
        "provenance": [],
        "can_share": True,
        "can_bank": True,
        "error": None,
        "workspace_root": workspace_root,
        "model": model,
    }

    if cue != "coding" or not include_extensions:
        result = _front_man_pool(task, result)
        return result

    result = _coding_pool(task, workspace_root, result)
    return result


def _front_man_pool(task: str, acc: Dict[str, Any]) -> Dict[str, Any]:
    """Handle concept/share/bank cues in front-man mode."""
    # Build a context summary the model can work from (workspace + memory).
    context_parts = []
    workspace_root = acc.get("workspace_root")
    if workspace_root:
        root = Path(workspace_root)
        ctx = {
            "task": task,
            "workspace": str(root),
            "workspace_files": _list_project_files(root),
        }
        context_parts.append(_clip_json(ctx, 6000))
    else:
        context_parts.append(_clip_json({"task": task}, 4000))

    # Bring in what Harold already knows about this topic (so the announcement
    # and the bank are grounded in his existing memory).
    if workspace_root:
        from my_ai.harold_coding_integration import harold_tools

        # Recall memory first to see if there is already something on topic.
        try:
            tools = harold_tools(root=Path(workspace_root))
            recall = _call_harold_api(
                model,
                [
                    {
                        "role": "user",
                        "content": "What do you already know about the topic of this task? "
                        "Search your memory and report matching notes concisely.",
                    },
                ],
                tools=tools,
            )
            text = _message_text(recall)
            if text and len(text.strip()) > 10:
                context_parts.append(_clip_json({"existing_memory": text}, 4000))
        except Exception as exc:
            context_parts.append(_clip_json({"memory_recall_error": str(exc)[:300]}, 2000))

    prompt = (
        "You are Harold, the front man for a coding team. A colleague gave you this task: "
        f"\"\"\"{task}\"\"\"\n\n"
        "Aggregate whatever context you have (the task, the workspace, and your existing "
        "memory). Then decide the team's decision, write it as a short announcement to the "
        "team, and be ready to share it. Do not write code yet; this is the concept/pool step. "
        "Reply with the announcement text only."
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        resp = _call_harold_api(model, messages)
        content = _message_text(resp)
        if content:
            acc["pooled_result"] = content.strip()
    except Exception as exc:
        acc["pooled_result"] = f"(could not pool: {exc})"
    acc["provenance"].append({"tool": "frontman", "contribution": "concept pool"})
    return acc

# ---------------------------------------------------------------------------
# Harold's own API client (OpenAI-compatible)
# ---------------------------------------------------------------------------

def _harold_base_url() -> str:
    # Same default as KILO_CONFIG / agent_bridge.py: the local server.
    return os.getenv("OPENAI_BASE_URL", "http://192.168.1.158:10000/v1")


def _harold_api_key() -> str:
    # CHAT_API_KEY is the shared secret for the /v1/chat/completions endpoint.
    return os.getenv("CHAT_API_KEY", "")


def _call_harold_api(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """POST a chat-completions request to Harold's own API.

    Returns the parsed JSON response so the pooler can read the assistant's
    text and any tool calls it made.
    """
    import json
    import urllib.error
    import urllib.request

    url = _harold_base_url().rstrip("/") + "/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_harold_api_key()}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Harold API {exc.code}: {text[:1000]}"
        ) from exc

# Extension catalog (reused from kilo_cline_geex.py)
# ---------------------------------------------------------------------------

# KILO_CONFIG is kept identical to the original (it already points at
# Harold's own API on the Lubuntu server).  We only import what we need so the
# module stays a pure catalog of the extensions' capabilities.
from my_ai.extensions.kilo_cline_geex import (
    KILO_CONFIG,
    CLINE_CAPABILITIES,
    CODEGEX_CAPABILITIES,
)  # noqa: E402

# Tool order mirrors SelfRepairManager in self_repair.py:
# Cline (1) -> Kilo (2) -> CodeGeeX (3).
_EXTENSION_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "cline",
        "capabilities": CLINE_CAPABILITIES,
        "config": None,  # Filled in by caller with the actual API endpoint.
    },
    {
        "name": "kilo",
        "capabilities": KILO_CONFIG,
        "config": None,
    },
    {
        "name": "codegeex",
        "capabilities": CODEGEX_CAPABILITIES,
        "config": None,
    },
]

