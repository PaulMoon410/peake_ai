import json
import os
import time
import threading
import queue as queue_mod
from datetime import datetime
from ftplib import FTP
import re
import requests
from language_model import NeuralLanguageModel
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urlparse
import tempfile

try:
    from nectar import Hive as NectarHive
except Exception:
    NectarHive = None

try:
    from beem import Hive as BeemHive
    from beem.account import Account as BeemAccount
    from beem.nodelist import NodeList as BeemNodeList
except Exception:
    BeemHive = None
    BeemAccount = None
    BeemNodeList = None

HISTORY_FILE = "peakebot_memory.json"
KEY_FILE = "hive_keys.json"
FTP_HOST = "<REDACTED_FTP_HOST>"
FTP_USER = "<REDACTED_FTP_USER>"
FTP_PASS = "<REDACTED_FTP_PASS>"
FTP_BASE_DIR = "<REDACTED_FTP_BASE_DIR>"
LEARNING_QUEUE_FILE = "learning_queue.json"
LEARNED_TOPICS_FILE = "learned_topics.json"
KNOWLEDGE_GROUP_PREFIX = "knowledge"
KNOWLEDGE_GROUP_MAX_BYTES = 100 * 1024 * 1024  # 100MB
WORKING_MEMORY_MAX_ENTRIES = 500
VERIFICATION_MIN_SHARED_TOKENS = 4
MIN_HIVE_AUTHOR_REPUTATION = 50.0
MIN_LEARNING_CONFIDENCE = 0.6
HIVE_BACKEND = "nectar" if NectarHive is not None else ("beem" if BeemHive is not None else "none")
FETCHAI_ENABLED = os.getenv("FETCHAI_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
FETCHAI_API_URL = os.getenv("FETCHAI_API_URL", "").strip()
FETCHAI_API_KEY = os.getenv("FETCHAI_API_KEY", "").strip()
FETCHAI_TIMEOUT_SECONDS = int(os.getenv("FETCHAI_TIMEOUT_SECONDS", "20"))
FETCHAI_SELF_IMPROVE_TOPICS = int(os.getenv("FETCHAI_SELF_IMPROVE_TOPICS", "5"))
BACKGROUND_RESEARCH_ENABLED = os.getenv("BACKGROUND_RESEARCH_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
BACKGROUND_RESEARCH_MAX_QUEUE = int(os.getenv("BACKGROUND_RESEARCH_MAX_QUEUE", "100"))
VERIFICATION_STOPWORDS = {
    "about", "after", "again", "also", "and", "been", "being", "from", "have",
    "into", "more", "most", "only", "that", "their", "there", "these", "they",
    "this", "those", "very", "what", "when", "where", "with", "would", "your",
    "while", "which", "could", "should", "will", "just", "than", "then"
}

# Basic interaction intents and response templates.
BASIC_INTERACTIONS = [
    {
        "name": "help_affirm",
        "patterns": ["can i ask", "can you help", "are you there", "are you working", "do you work"],
        "responses": ["Yes, absolutely!", "Of course!", "Definitely!", "You bet!", "Totally!"],
    },
    {
        "name": "understanding",
        "patterns": ["do you understand", "do you get it", "are you listening", "hear me"],
        "response": "Yes, I understand you. Please continue.",
    },
    {
        "name": "awareness",
        "patterns": ["are you aware", "you aware", "are you conscious", "are you self aware"],
        "response": "I am aware of this conversation and your messages in real time. I can understand context and respond helpfully.",
    },
    {
        "name": "conversation",
        "patterns": ["can we hold a conversation", "can we talk", "can we have a conversation"],
        "response": "Absolutely. We can have a real back-and-forth conversation. Ask me anything.",
    },
    {
        "name": "not_answering",
        "patterns": ["why arent you", "why aren't you", "why dont you", "why don't you", "not answering", "not responding"],
        "response": "I apologize for the confusion. I am here and ready to help. What would you like to know?",
    },
    {
        "name": "identity",
        "patterns": ["what are you", "who are you", "your name", "call you"],
        "response": "I am PeakeBot, an AI assistant. I can chat, learn from interactions, and search when you explicitly ask.",
    },
    {
        "name": "greeting",
        "patterns": ["hello", "hi", "hey", "greetings"],
        "response": "Hello! Welcome to PeakeBot. How can I help you today?",
    },
    {
        "name": "thanks",
        "patterns": ["thanks", "thank you", "appreciate"],
        "response": "You are welcome. Happy to help.",
    },
    {
        "name": "status",
        "patterns": ["how are you", "how do you feel", "you okay"],
        "response": "I am doing well and ready to assist.",
    },
    {
        "name": "time",
        "patterns": ["what time", "what is the time", "time", "current time", "whats the time"],
        "response": None,  # Special handler will compute the time
    },
    {
        "name": "learning_capability",
        "patterns": ["saving", "you learning", "are you learning", "can you learn", "remember", "saved", "remember me"],
        "response": "Yes, I learn from our conversations and save them to persistent memory. I can remember interactions, recognize patterns, and improve my responses over time through autonomous research and domain-specific learning.",
    },
    {
        "name": "casual_acknowledgment",
        "patterns": ["weird", "cool", "interesting", "okay", "ok", "i see", "right", "sure", "got it", "makes sense"],
        "responses": ["I understand.", "Got it.", "Interesting observation.", "Thanks for the feedback.", "I agree."],
    },
]

COMMON_TEXT_NORMALIZATIONS = {
    "u": "you",
    "ur": "your",
    "r": "are",
    "pls": "please",
    "plz": "please",
    "im": "i am",
    "cant": "cannot",
    "wont": "will not",
    "dont": "do not",
    "idk": "i do not know",
    "wanna": "want to",
    "gonna": "going to",
    "teh": "the",
    "whats": "what is",
    "thats": "that is",
    "heres": "here is",
    "ive": "i have",
    "youve": "you have",
    "havent": "have not",
    "isnt": "is not",
    "arent": "are not",
    "shouldnt": "should not",
    "couldnt": "could not",
    "wouldnt": "would not",
}

ENGLISH_HINT_WORDS = {
    "the", "is", "are", "you", "what", "when", "where", "why", "how", "can", "do", "and",
    "please", "help", "question", "search", "about", "this", "that", "it"
}

SHORT_ENGLISH_ALLOWED = {
    "hi", "hello", "hey", "thanks", "thank", "yes", "no", "ok", "okay", "help",
    "time", "date", "now", "when", "what", "who", "where", "why", "how"
}

LEARNING_DOMAIN_KEYWORDS = {
    "complex_math": ["math", "algebra", "calculus", "geometry", "equation", "proof", "statistics", "probability"],
    "computer_coding": ["code", "coding", "python", "javascript", "java", "bug", "debug", "algorithm", "api", "database"],
    "human_psychology": ["psychology", "behavior", "emotion", "mind", "cognitive", "trauma", "anxiety", "motivation"],
    "pattern_recognition": ["pattern", "signal", "trend", "recognize", "classification", "anomaly", "cluster"],
    "problem_solving": ["problem", "solve", "strategy", "optimize", "decision", "reasoning", "logic"],
}

CLARIFICATION_TEMPLATE = (
    "I want to avoid giving you a wrong answer. "
    "Can you clarify your goal and desired level of detail? "
    "If you want live sources, say: 'search web: <topic>'."
)

_BACKGROUND_RESEARCH_QUEUE = queue_mod.Queue(maxsize=BACKGROUND_RESEARCH_MAX_QUEUE)
_BACKGROUND_RESEARCH_PENDING = set()
_BACKGROUND_RESEARCH_LOCK = threading.Lock()
_BACKGROUND_RESEARCH_STARTED = False


def _initialize_language_model() -> NeuralLanguageModel:
    model = NeuralLanguageModel()
    if model.load_model("language_model.pkl"):
        return model

    # Render deploys may not include a pre-trained pickle. Bootstrap a small usable model.
    try:
        bootstrap_texts = [
            "Hello, how can I help you today?",
            "I am PeakeBot, a helpful AI assistant.",
            "I can search for information and summarize what I find.",
            "Please ask me a question and I will do my best to help.",
            "I am still learning and may need to verify uncertain information.",
        ]
        model.build_vocabulary(bootstrap_texts)
        model.train_on_text(bootstrap_texts, epochs=1)
        print("⚠️ language_model.pkl not found; bootstrapped a minimal model for startup")
    except Exception as e:
        print(f"⚠️ Failed to bootstrap fallback language model: {str(e)}")
    return model


# Load the language model
model = _initialize_language_model()


def _tmp_path(filename: str) -> str:
    return os.path.join(tempfile.gettempdir(), filename)


def _entry_key(entry: dict) -> str:
    return "|".join([
        str(entry.get("timestamp", "")),
        str(entry.get("prompt", "")),
        str(entry.get("response", "")),
    ])


def _dedupe_entries(entries: list) -> list:
    seen = set()
    unique = []
    for entry in entries:
        key = _entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _knowledge_file_sort_key(filename: str):
    m = re.match(r"^knowledge_(\d{8})_part(\d+)\.json$", filename)
    if not m:
        return ("", 0)
    return (m.group(1), int(m.group(2)))


def _find_daily_knowledge_parts(files: list, day_str: str) -> list:
    pattern = re.compile(rf"^{KNOWLEDGE_GROUP_PREFIX}_{day_str}_part(\d+)\.json$")
    parts = []
    for name in files:
        m = pattern.match(name)
        if m:
            parts.append((int(m.group(1)), name))
    parts.sort(key=lambda x: x[0])
    return parts


def _serialize_json_bytes(data) -> bytes:
    return json.dumps(data, indent=2).encode("utf-8")


def _tokenize_for_verification(text: str) -> set:
    tokens = re.findall(r"\b[a-z0-9]{4,}\b", text.lower())
    return {t for t in tokens if t not in VERIFICATION_STOPWORDS}


def _source_reliability_weight(source: str) -> float:
    source_weights = {
        "wikipedia": 0.85,      # High credibility for factual content
        "news": 0.75,           # News sources trusted but may have bias
        "bing": 0.70,           # Major search engine
        "duckduckgo": 0.70,     # Privacy-focused alternative
        "hive": 0.65,           # Blockchain posts (community-driven)
        "domain": 0.70,         # Direct website
        "url": 0.70,            # Direct URL fetch
    }
    return source_weights.get(source, 0.6)


def _normalize_user_text(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"[^a-z0-9\s\?\!\.]", " ", cleaned)
    tokens = cleaned.split()
    normalized_tokens = [COMMON_TEXT_NORMALIZATIONS.get(tok, tok) for tok in tokens]
    normalized = " ".join(normalized_tokens)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _is_probably_english(text: str) -> bool:
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    if not tokens:
        return False
    ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(1, len(text))
    hint_hits = sum(1 for t in tokens if t in ENGLISH_HINT_WORDS)
    if ascii_ratio < 0.85:
        return False
    if hint_hits >= 1:
        return True
    # Permit only short common-English chats when there are no hint-word matches.
    if len(tokens) <= 3 and any(t in SHORT_ENGLISH_ALLOWED for t in tokens):
        return True
    # Check if tokens after normalization contain English hint words
    normalized = _normalize_user_text(text)
    normalized_tokens = set(re.findall(r"[a-zA-Z]+", normalized.lower()))
    if any(t in ENGLISH_HINT_WORDS for t in normalized_tokens):
        return True
    return False


def _is_explicit_search_request(original_text: str, normalized_text: str) -> bool:
    if _extract_url_candidate(original_text):
        return True
    explicit_phrases = [
        "search ", "search for", "look up", "find out", "google", "duckduckgo", "bing",
        "web search", "search web", "search online", "find on web"
    ]
    return any(p in normalized_text for p in explicit_phrases)


def _is_question(normalized_text: str, original_text: str) -> bool:
    if original_text.strip().endswith("?"):
        return True
    starters = ("what", "when", "where", "why", "how", "who", "can", "do", "does", "is", "are", "should", "could", "would")
    return normalized_text.startswith(starters)


def _match_basic_interaction(normalized_text: str) -> str:
    tokens = set(re.findall(r"[a-z0-9]+", normalized_text))

    def pattern_matches(pattern: str) -> bool:
        p = pattern.strip().lower()
        if not p:
            return False
        # Multi-word patterns are matched as phrases; single words by token boundary.
        if " " in p:
            return p in normalized_text
        return p in tokens

    for interaction in BASIC_INTERACTIONS:
        if any(pattern_matches(pattern) for pattern in interaction.get("patterns", [])):
            # Special case: time handler computes current time
            if interaction.get("name") == "time":
                current_time = datetime.now().strftime("%I:%M %p")
                return f"The current time is {current_time}."
            
            responses = interaction.get("responses")
            if responses:
                return responses[hash(normalized_text) % len(responses)]
            return interaction.get("response", "")
    return ""


def _extract_learning_domains(normalized_text: str) -> list:
    domains = []
    for domain, keywords in LEARNING_DOMAIN_KEYWORDS.items():
        if any(k in normalized_text for k in keywords):
            domains.append(domain)
    return domains


def _queue_domain_learning_topics(normalized_text: str):
    domains = _extract_learning_domains(normalized_text)
    for d in domains:
        add_to_learning_queue(d)


def _response_seems_low_confidence(response: str) -> bool:
    text = (response or "").strip().lower()
    if not text:
        return True
    if len(text.split()) < 4:
        return True
    uncertain_markers = [
        "i'm still learning",
        "i encountered an issue",
        "i'm processing",
        "am help am",
        "can help am",
    ]
    if any(m in text for m in uncertain_markers):
        return True
    # Repetitive token pattern can indicate low-quality generation.
    words = re.findall(r"[a-z]+", text)
    if len(words) >= 6:
        repeats = len(words) - len(set(words))
        if repeats >= max(3, len(words) // 2):
            return True
    return False


def _background_research_query(prompt: str) -> str:
    text = _normalize_user_text(prompt)
    # Remove explicit command words when forming autonomous research query.
    text = re.sub(r"\b(search|look\s+up|find\s+out|search\s+web|search\s+online)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or prompt.strip()


def _start_background_research_worker():
    global _BACKGROUND_RESEARCH_STARTED
    if not BACKGROUND_RESEARCH_ENABLED:
        return
    with _BACKGROUND_RESEARCH_LOCK:
        if _BACKGROUND_RESEARCH_STARTED:
            return
        worker = threading.Thread(target=_background_research_worker, name="peakebot-bg-research", daemon=True)
        worker.start()
        _BACKGROUND_RESEARCH_STARTED = True
        print("🤖 Background research worker started")


def _enqueue_background_research(prompt: str, reason: str = ""):
    if not BACKGROUND_RESEARCH_ENABLED:
        return
    query = _background_research_query(prompt)
    if len(query) < 4:
        return
    with _BACKGROUND_RESEARCH_LOCK:
        if query in _BACKGROUND_RESEARCH_PENDING:
            return
        _BACKGROUND_RESEARCH_PENDING.add(query)
    try:
        _BACKGROUND_RESEARCH_QUEUE.put_nowait((query, reason))
        _start_background_research_worker()
    except Exception:
        with _BACKGROUND_RESEARCH_LOCK:
            _BACKGROUND_RESEARCH_PENDING.discard(query)
        print("⚠️ Background research queue is full; skipping task")


def _background_research_worker():
    while True:
        query, reason = _BACKGROUND_RESEARCH_QUEUE.get()
        try:
            _run_background_research(query, reason)
        except Exception as e:
            print(f"⚠️ Background research failed for '{query}': {str(e)}")
        finally:
            with _BACKGROUND_RESEARCH_LOCK:
                _BACKGROUND_RESEARCH_PENDING.discard(query)
            _BACKGROUND_RESEARCH_QUEUE.task_done()


def _run_background_research(query: str, reason: str = ""):
    verified = search_web_verified(query)
    hits = verified.get("hits", [])
    snippet_texts = [
        h.get("snippet", "")
        for h in hits
        if h.get("verification_status") == "supported"
        and h.get("confidence", 0) >= MIN_LEARNING_CONFIDENCE
        and h.get("snippet")
    ]
    if snippet_texts:
        try:
            model.train_on_text(snippet_texts, epochs=1)
            print(f"🤖 Background research learned {len(snippet_texts)} snippet(s) for '{query}' ({reason or 'auto'})")
        except Exception as e:
            print(f"⚠️ Background learning failed for '{query}': {str(e)}")


def _fetchai_generate_response(prompt: str, memory_context: str = "", web_context: str = "") -> str:
    """Optional Fetch.ai HTTP integration. Returns empty string on any failure."""
    if not FETCHAI_ENABLED or not FETCHAI_API_URL:
        return ""

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if FETCHAI_API_KEY:
        headers["Authorization"] = f"Bearer {FETCHAI_API_KEY}"

    payload = {
        "prompt": prompt,
        "context": {
            "memory": memory_context,
            "web": web_context,
        },
    }

    try:
        res = requests.post(
            FETCHAI_API_URL,
            headers=headers,
            json=payload,
            timeout=FETCHAI_TIMEOUT_SECONDS,
        )
        if res.status_code < 200 or res.status_code >= 300:
            print(f"⚠️ Fetch.ai request failed with status {res.status_code}")
            return ""

        content_type = (res.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            data = res.json()
            if isinstance(data, dict):
                for key in ["response", "answer", "output", "message", "text"]:
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                return ""
            return str(data).strip()

        # Plain text fallback
        return (res.text or "").strip()
    except Exception as e:
        print(f"⚠️ Fetch.ai call failed: {str(e)}")
        return ""


def _extract_topics_from_fetchai(text: str, max_topics: int = 5) -> list:
    """Parse a robust topic list from Fetch.ai text or JSON-like output."""
    if not text:
        return []

    candidates = []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            candidates.extend([str(x).strip() for x in data if str(x).strip()])
        elif isinstance(data, dict):
            items = data.get("topics") or data.get("suggestions") or data.get("items") or []
            if isinstance(items, list):
                candidates.extend([str(x).strip() for x in items if str(x).strip()])
    except Exception:
        pass

    # Fallback: parse lines or numbered/bulleted output.
    if not candidates:
        for line in text.splitlines():
            cleaned = re.sub(r"^\s*(?:[-*]|\d+[\.)])\s*", "", line).strip()
            if cleaned and len(cleaned) >= 4:
                candidates.append(cleaned)

    seen = set()
    topics = []
    for c in candidates:
        normalized = re.sub(r"\s+", " ", c).strip(" .")
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        topics.append(normalized)
        if len(topics) >= max_topics:
            break
    return topics


def _fetchai_suggest_learning_topics(memory_snippets: list, max_topics: int = FETCHAI_SELF_IMPROVE_TOPICS) -> list:
    """Ask Fetch.ai what PeakeBot should learn next from recent interactions."""
    if not FETCHAI_ENABLED:
        return []

    recent = memory_snippets[-12:] if memory_snippets else []
    recent_text = "\n".join(
        f"- user: {m.get('prompt', '')}\n  bot: {m.get('response', '')}"
        for m in recent
    )

    prompt = (
        "You are helping an autonomous AI improve itself. "
        f"From these recent interactions, suggest exactly {max_topics} concise learning topics "
        "that will most improve future answers. Return ONLY a JSON object: "
        '{"topics": ["topic 1", "topic 2"]}.\n\n'
        f"Recent interactions:\n{recent_text}"
    )

    response_text = _fetchai_generate_response(prompt, memory_context=recent_text)
    return _extract_topics_from_fetchai(response_text, max_topics=max_topics)


def _hive_reputation_to_score(raw_reputation) -> float:
    """Convert Hive raw reputation into familiar score range (approx. 0-80)."""
    try:
        rep = int(raw_reputation or 0)
    except Exception:
        return 0.0
    if rep == 0:
        return 0.0
    sign = -1.0 if rep < 0 else 1.0
    rep_abs = abs(rep)
    magnitude = len(str(rep_abs)) - 1
    leading = rep_abs / (10 ** magnitude) if magnitude >= 0 else 0
    score = (max(0.0, magnitude + (leading - 1.0)) - 9.0) * 9.0 + 25.0
    if sign < 0:
        score = 50.0 - (score - 50.0)
    return round(score, 2)


def _is_reputable_hive_author(raw_reputation, min_score: float = MIN_HIVE_AUTHOR_REPUTATION) -> bool:
    return _hive_reputation_to_score(raw_reputation) >= min_score


def _cross_verify_hits(hits: list) -> list:
    """Mark hits as supported or unverified using overlap across independent sources."""
    analyzed = []
    for hit in hits:
        source = hit.get("source", "unknown")
        analyzed.append({
            **hit,
            "verification_status": "unverified",
            "supporting_sources": 0,
            "confidence": _source_reliability_weight(source) * 0.5,
            "verification_note": "Only one source found; treat as unverified."
        })

    token_sets = [_tokenize_for_verification((h.get("title", "") + " " + h.get("snippet", "")).strip()) for h in analyzed]

    for i, hit in enumerate(analyzed):
        support = 0
        for j, other in enumerate(analyzed):
            if i == j:
                continue
            # Prefer corroboration from independent sources.
            if hit.get("source") and other.get("source") and hit.get("source") == other.get("source"):
                continue
            if hit.get("author") and other.get("author") and hit.get("author") == other.get("author"):
                continue
            if len(token_sets[i].intersection(token_sets[j])) >= VERIFICATION_MIN_SHARED_TOKENS:
                support += 1

        hit["supporting_sources"] = support
        base = _source_reliability_weight(hit.get("source", "unknown"))
        if support >= 1:
            hit["verification_status"] = "supported"
            hit["confidence"] = min(0.97, base + (0.12 * support))
            hit["verification_note"] = f"Cross-checked with {support} additional source(s)."
        else:
            hit["verification_status"] = "unverified"
            hit["confidence"] = max(0.25, base * 0.5)
            hit["verification_note"] = "No corroboration found across independent sources."

    return analyzed


def search_web_verified(query: str) -> dict:
    """Multi-source search with cross-verification and confidence scoring from multiple search engines."""
    hits = []

    # 1. Hive blockchain posts
    hive_hits = _search_hive(query)
    for h in hive_hits:
        hits.append({
            **h,
            "source": "hive"
        })

    # 2. Google News
    for n in _search_news(query, max_items=5):
        title = n.get("title", "")
        link = n.get("link", "")
        source_name = "news"
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            if len(parts) == 2 and parts[1].strip():
                source_name = parts[1].strip()
        hits.append({
            "title": title[:200],
            "url": link,
            "author": source_name,
            "created": n.get("date", ""),
            "snippet": title[:240],
            "source": "news"
        })

    # 3. DuckDuckGo (privacy-focused web search)
    for d in _search_duckduckgo(query, max_items=5):
        hits.append({
            "title": d.get("title", "")[:200],
            "url": d.get("link", ""),
            "author": "DuckDuckGo",
            "created": d.get("date", ""),
            "snippet": d.get("snippet", "")[:300],
            "source": "duckduckgo"
        })

    # 4. Wikipedia (fact verification resource)
    for w in _search_wikipedia(query, max_items=3):
        hits.append({
            "title": w.get("title", "")[:200],
            "url": w.get("link", ""),
            "author": "Wikipedia",
            "created": w.get("date", ""),
            "snippet": w.get("snippet", "")[:300],
            "source": "wikipedia"
        })

    # 5. Bing News (additional cross-check)
    for b in _search_bing(query, max_items=4):
        hits.append({
            "title": b.get("title", "")[:200],
            "url": b.get("link", ""),
            "author": "Bing",
            "created": b.get("date", ""),
            "snippet": b.get("snippet", "")[:300],
            "source": "bing"
        })

    # 6. Direct URL if provided
    url_candidate = _extract_url_candidate(query)
    if url_candidate:
        summary = _fetch_and_summarize_url(url_candidate)
        if summary:
            hits.append({
                "title": f"Direct source summary: {url_candidate}",
                "url": url_candidate,
                "author": "direct_url",
                "created": datetime.now().isoformat(),
                "snippet": summary[:300],
                "source": "url"
            })

    if not hits:
        return {"hits": [], "text": None}

    verified_hits = _cross_verify_hits(hits)
    supported_count = sum(1 for h in verified_hits if h["verification_status"] == "supported")

    lines = [
        f"🔍 Verification summary: {supported_count}/{len(verified_hits)} items corroborated by independent sources.",
        f"📊 Sources consulted: {len(set(h.get('source') for h in verified_hits))} different search engines/sources.",
        "Use unverified items cautiously and phrase them as tentative."
    ]
    for r in verified_hits:
        status = "✅ verified" if r["verification_status"] == "supported" else "⚠️ unverified"
        lines.append(
            f"- [{status}] ({r.get('source', 'unknown')}) {r['title']} (@{r['author']})"
        )
        if r.get("snippet"):
            lines.append(f"  📝 {r['snippet']}")
        lines.append(f"  💯 confidence: {r.get('confidence', 0):.2f} | 🔗 {r['url']}")
        lines.append(f"  💭 {r['verification_note']}")

    return {"hits": verified_hits, "text": "Gathered results:\n" + "\n".join(lines)}

# Initialize Hive with posting key
def init_hive():
    if not os.path.exists(KEY_FILE):
        raise Exception("Missing hive_keys.json with posting key.")
    with open(KEY_FILE) as f:
        keys = json.load(f)
    posting_key = keys.get("posting_key")
    if not posting_key:
        raise Exception("Missing posting_key in hive_keys.json.")

    if NectarHive is not None:
        # nectar accepts kwargs and can consume keys for signing operations.
        return NectarHive(keys=[posting_key])
    if BeemHive is not None:
        return BeemHive(keys=[posting_key])
    raise Exception("No Hive client available. Install hive-nectar or beem.")

# Create a safe category directory path
def categorize_prompt(prompt):
    keywords = re.findall(r"\b\w+\b", prompt.lower())
    important = keywords[:3] if keywords else ["general"]
    return "_".join(important)

# Fetch all previous entries from GeoCities FTP
def fetch_all_ftp_memory():
    try:
        ftp = FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        ftp.cwd(FTP_BASE_DIR)
        
        all_entries = []
        files = []
        try:
            files = ftp.nlst()
        except Exception:
            files = []

        # Preferred storage: daily grouped knowledge files with part rollover.
        grouped_files = sorted(
            [f for f in files if re.match(r"^knowledge_\d{8}_part\d+\.json$", f)],
            key=_knowledge_file_sort_key,
        )
        for grouped_file in grouped_files:
            try:
                local_path = _tmp_path(grouped_file)
                with open(local_path, "wb") as f:
                    ftp.retrbinary(f"RETR {grouped_file}", f.write)
                with open(local_path, "r", encoding="utf-8") as f:
                    batch_data = json.load(f)
                    all_entries.extend(batch_data)
            except Exception:
                continue
        
        # Backward compatibility: legacy archive files.
        try:
            batch_files = sorted([f for f in files if f.startswith("memory_batch_") and f.endswith(".json")])
            
            for batch_file in batch_files:
                try:
                    local_path = _tmp_path(batch_file)
                    with open(local_path, "wb") as f:
                        ftp.retrbinary(f"RETR {batch_file}", f.write)
                    with open(local_path, "r", encoding="utf-8") as f:
                        batch_data = json.load(f)
                        all_entries.extend(batch_data)
                except:
                    continue
        except:
            pass
        
        # Current working memory cache
        try:
            local_path = _tmp_path("memory.json")
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR memory.json", f.write)
            with open(local_path, "r", encoding="utf-8") as f:
                current_memory = json.load(f)
                all_entries.extend(current_memory)
        except:
            pass
        
        ftp.quit()
        return _dedupe_entries(all_entries)
    except Exception as e:
        print("❌ Could not fetch memory from GeoCities:", str(e))
        return []

# Ensure memory file exists
if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "w") as f:
        json.dump([], f)

# Ensure learning queue exists
if not os.path.exists(LEARNING_QUEUE_FILE):
    with open(LEARNING_QUEUE_FILE, "w") as f:
        json.dump([], f)

# Ensure learned topics tracker exists
if not os.path.exists(LEARNED_TOPICS_FILE):
    with open(LEARNED_TOPICS_FILE, "w") as f:
        json.dump({"topics": [], "last_learning_session": None}, f)

def load_memory(n=5):
    ftp_memory = fetch_all_ftp_memory()
    return ftp_memory[-n:]

def search_memory(query):
    matches = []
    for entry in fetch_all_ftp_memory():
        if query.lower() in entry["prompt"].lower() or query.lower() in entry["response"].lower():
            matches.append(entry)
    return matches

def add_to_learning_queue(topic: str):
    """Add a topic to the learning queue for autonomous exploration."""
    try:
        with open(LEARNING_QUEUE_FILE, "r") as f:
            queue = json.load(f)
        
        # Avoid duplicates
        topic_lower = topic.lower().strip()
        if topic_lower not in [t.lower() for t in queue]:
            queue.append(topic)
            with open(LEARNING_QUEUE_FILE, "w") as f:
                json.dump(queue[-100:], f, indent=2)  # Keep last 100
            print(f"📝 Queued for learning: {topic}")
    except Exception as e:
        print(f"⚠️ Failed to queue topic: {str(e)}")

def process_learning_queue(max_topics: int = 3):
    """Autonomously research topics from the learning queue."""
    try:
        with open(LEARNING_QUEUE_FILE, "r") as f:
            queue = json.load(f)
        
        with open(LEARNED_TOPICS_FILE, "r") as f:
            learned_data = json.load(f)

        # Let Fetch.ai suggest next learning targets from recent history.
        memory_snippets = fetch_all_ftp_memory()
        suggested_topics = _fetchai_suggest_learning_topics(memory_snippets, max_topics=FETCHAI_SELF_IMPROVE_TOPICS)
        if suggested_topics:
            learned_topic_names = {
                str(t.get("topic", "")).lower().strip()
                for t in learned_data.get("topics", [])
                if isinstance(t, dict)
            }
            queue_lower = {str(t).lower().strip() for t in queue}
            added = 0
            for topic in suggested_topics:
                tk = topic.lower().strip()
                if tk and tk not in learned_topic_names and tk not in queue_lower:
                    queue.append(topic)
                    queue_lower.add(tk)
                    added += 1
            if added:
                print(f"🤖 Fetch.ai added {added} self-improvement topic(s) to the learning queue")
        
        if not queue:
            print("💤 Learning queue empty")
            return
        
        print(f"🔬 Starting autonomous learning session ({len(queue)} topics queued)...")
        
        processed = 0
        for topic in queue[:max_topics]:
            print(f"\n🧠 Researching: {topic}")
            
            # Search gathered sources for this topic
            results = search_web_verified(f"search {topic}")
            
            if results.get("text"):
                # Learn only from cross-verified snippets.
                snippet_texts = [
                    h.get("snippet", "")
                    for h in results.get("hits", [])
                    if h.get("verification_status") == "supported"
                    and h.get("confidence", 0) >= MIN_LEARNING_CONFIDENCE
                    and h.get("snippet")
                ]
                
                if snippet_texts:
                    try:
                        model.train_on_text(snippet_texts, epochs=1)
                        learned_data["topics"].append({
                            "topic": topic,
                            "timestamp": datetime.now().isoformat(),
                            "snippets_learned": len(snippet_texts),
                            "verification": "cross-verified"
                        })
                        print(f"✅ Learned from {len(snippet_texts)} sources")
                    except Exception as e:
                        print(f"⚠️ Learning failed: {str(e)}")
                else:
                    print("⚠️ Sources found, but none were independently corroborated")
            else:
                print(f"⚠️ No corroborated content found for '{topic}'")
            
            processed += 1
            time.sleep(2)  # Respectful delay
        
        # Update queue and learned topics
        with open(LEARNING_QUEUE_FILE, "w") as f:
            json.dump(queue[processed:], f, indent=2)
        
        learned_data["last_learning_session"] = datetime.now().isoformat()
        with open(LEARNED_TOPICS_FILE, "w") as f:
            json.dump(learned_data, f, indent=2)
        
        # Save model after learning
        model.save_model("language_model.pkl")
        print(f"\n🎓 Learning session complete! Processed {processed} topics")
        
    except Exception as e:
        print(f"⚠️ Learning session failed: {str(e)}")

def _is_url(text: str) -> bool:
    """Conservative URL/domain presence check anywhere in text."""
    if text.startswith(("http://", "https://")):
        return True
    # any domain-like token in the text
    return re.search(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", text) is not None

def _extract_url_candidate(text: str) -> str:
    """Extract a concrete URL or domain from free-form text like 'search ecency.com'."""
    # 1) explicit URL
    m = re.search(r"https?://[^\s]+", text)
    if m:
        return m.group(0)
    # 2) last domain-like token
    matches = list(re.finditer(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", text))
    if matches:
        return matches[-1].group(0)
    return ""

def _strip_html(html: str) -> str:
    """Strip HTML tags, markdown links, and clean whitespace."""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Remove markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Remove plain URLs
    text = re.sub(r"https?://[^\s]+", "", text)
    # Clean excessive whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _fetch_and_summarize_url(url: str) -> str:
    try:
        if not url.startswith("http"):
            url = "https://" + url
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code != 200:
            return ""
        text = _strip_html(res.text)
        return text[:600]
    except Exception as e:
        print(f"⚠️ URL fetch failed: {str(e)}")
        return ""

def _search_news(query: str, max_items: int = 5) -> list:
    try:
        rss_url = (
            "https://news.google.com/rss/search?q=" + quote_plus(query) +
            "&hl=en-US&gl=US&ceid=US:en"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(rss_url, headers=headers, timeout=8)
        if res.status_code != 200:
            return []
        root = ET.fromstring(res.content)
        items = []
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            pub = item.findtext("pubDate") or ""
            items.append({"title": title, "link": link, "date": pub})
        return items
    except Exception as e:
        print(f"⚠️ News search failed: {str(e)}")
        return []

def _search_duckduckgo(query: str, max_items: int = 5) -> list:
    """Search DuckDuckGo for results (privacy-focused alternative to Google)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        url = f"https://duckduckgo.com/?q={quote_plus(query)}&format=json"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code != 200:
            return []
        data = res.json()
        results = []
        
        # Extract results from RelatedTopics
        for item in data.get("RelatedTopics", [])[:max_items]:
            if "Result" in item:
                results.append({
                    "title": _strip_html(item.get("Result", ""))[:200],
                    "link": item.get("FirstURL", ""),
                    "date": datetime.now().isoformat(),
                    "snippet": item.get("Text", "")[:300]
                })
        
        return results
    except Exception as e:
        print(f"⚠️ DuckDuckGo search failed: {str(e)}")
        return []

def _search_wikipedia(query: str, max_items: int = 3) -> list:
    """Search Wikipedia for factual verification (great for definitions, concepts)."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        # Use Wikipedia API for more accurate results
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srmax": max_items,
        }
        res = requests.get(url, params=params, headers=headers, timeout=8)
        if res.status_code != 200:
            return []
        
        data = res.json()
        results = []
        
        for item in data.get("query", {}).get("search", []):
            title = item.get("title", "")
            snippet = _strip_html(item.get("snippet", ""))
            wiki_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            
            results.append({
                "title": title[:200],
                "link": wiki_url,
                "date": datetime.now().isoformat(),
                "snippet": snippet[:300]
            })
        
        return results
    except Exception as e:
        print(f"⚠️ Wikipedia search failed: {str(e)}")
        return []

def _search_bing(query: str, max_items: int = 5) -> list:
    """Search Bing for additional cross-verification results."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        # Using Bing search RSS feed
        url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code != 200:
            return []
        
        root = ET.fromstring(res.content)
        results = []
        
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            pub = item.findtext("pubDate") or ""
            description = _strip_html(item.findtext("description") or "")
            
            results.append({
                "title": title[:200],
                "link": link,
                "date": pub,
                "snippet": description[:300]
            })
        
        return results
    except Exception as e:
        print(f"⚠️ Bing search failed: {str(e)}")
        return []

def _summarize_domain(domain: str) -> str:
    """Try sitemap first, then common pages to build a quick domain overview."""
    headers = {"User-Agent": "Mozilla/5.0"}
    base = domain if domain.startswith("http") else f"https://{domain}"

    # 1) Try sitemap.xml
    try:
        sm = requests.get(base.rstrip("/") + "/sitemap.xml", headers=headers, timeout=6)
        if sm.status_code == 200:
            root = ET.fromstring(sm.content)
            urls = [loc.text for loc in root.findall(".//{*}loc")][:5]
            summaries = []
            for u in urls:
                s = _fetch_and_summarize_url(u)
                if s:
                    summaries.append(f"- {u}: {s[:200]}")
            if summaries:
                return "Domain overview (sitemap):\n" + "\n".join(summaries)
    except Exception:
        pass

    # 2) Fallback to common pages
    candidates = [
        base,
        base.rstrip("/") + "/about",
        base.rstrip("/") + "/explore",
        base.rstrip("/") + "/faq",
        base.rstrip("/") + "/blog",
    ]
    summaries = []
    for u in candidates:
        s = _fetch_and_summarize_url(u)
        if s:
            summaries.append(f"- {u}: {s[:200]}")
    return ("Domain overview:\n" + "\n".join(summaries)) if summaries else ""

def _search_hive(query: str, limit_per_tag: int = 20, min_author_reputation: float = MIN_HIVE_AUTHOR_REPUTATION) -> list:
    """Heuristic Hive search with author reputation filtering and clean snippets."""
    try:
        tokens = re.findall(r"\w+", query.lower())
        tags = [t for t in tokens if len(t) >= 3][:3] or ["hive"]
        results = []
        seen = set()

        if NectarHive is not None:
            hive = NectarHive()
            for tag in tags:
                try:
                    rows = hive.rpc.rpcexec({
                        "jsonrpc": "2.0",
                        "method": "bridge.get_ranked_posts",
                        "params": {
                            "sort": "created",
                            "tag": tag,
                            "observer": "",
                            "limit": limit_per_tag,
                            "start_author": None,
                            "start_permlink": None,
                        },
                        "id": 1,
                    })
                except Exception:
                    continue

                for p in rows or []:
                    title = p.get("title", "")
                    body = p.get("body", "")
                    hay = (title + "\n" + body).lower()
                    if any(tok in hay for tok in tokens):
                        url = f"https://ecency.com/@{p.get('author')}/{p.get('permlink')}"
                        if url in seen:
                            continue
                        author_rep_raw = p.get("author_reputation", 0)
                        author_rep_score = _hive_reputation_to_score(author_rep_raw)
                        if not _is_reputable_hive_author(author_rep_raw, min_score=min_author_reputation):
                            continue
                        seen.add(url)
                        clean_snippet = _strip_html(body)[:300]
                        results.append({
                            "title": title[:200],
                            "url": url,
                            "author": p.get("author"),
                            "created": p.get("created", ""),
                            "snippet": clean_snippet,
                            "author_reputation": author_rep_score,
                        })
        elif BeemHive is not None and BeemNodeList is not None:
            nodelist = BeemNodeList()
            try:
                nodelist.update_nodes()
            except Exception:
                pass
            hive = BeemHive(node=nodelist.get_nodes())
            for tag in tags:
                try:
                    rows = hive.rpc.get_discussions_by_created({"tag": tag, "limit": limit_per_tag})
                except Exception:
                    continue
                for p in rows or []:
                    title = p.get("title", "")
                    body = p.get("body", "")
                    hay = (title + "\n" + body).lower()
                    if any(tok in hay for tok in tokens):
                        url = f"https://ecency.com/@{p.get('author')}/{p.get('permlink')}"
                        if url in seen:
                            continue
                        author_rep_raw = p.get("author_reputation", 0)
                        author_rep_score = _hive_reputation_to_score(author_rep_raw)
                        if not _is_reputable_hive_author(author_rep_raw, min_score=min_author_reputation):
                            continue
                        seen.add(url)
                        clean_snippet = _strip_html(body)[:300]
                        results.append({
                            "title": title[:200],
                            "url": url,
                            "author": p.get("author"),
                            "created": p.get("created", ""),
                            "snippet": clean_snippet,
                            "author_reputation": author_rep_score,
                        })
        else:
            return []

        return results[:5]
    except Exception as e:
        print(f"⚠️ Hive search failed: {str(e)}")
        return []

def search_web(query):
    """Multi-source search: return clean, readable summaries with verification."""
    verified = search_web_verified(query)
    return verified.get("text")

def remember(prompt, response):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "prompt": prompt,
        "response": response
    }
    with open(HISTORY_FILE, "r") as f:
        memory = json.load(f)
    memory.append(entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(memory[-50:], f, indent=2)
    save_to_geocities(entry)
    generate_webpage(memory[-50:])

def generate_response(prompt):
    """Generate response using basic intent handling, memory, and explicit web search."""
    raw_prompt = prompt.strip()
    pl = _normalize_user_text(raw_prompt)

    if not raw_prompt:
        return "Please type a message, and I will help."

    if not _is_probably_english(pl):
        return "I work best in English right now. Please rephrase your message in English, even if grammar is imperfect."

    # Basic interaction layer (greetings, awareness, thanks, etc.).
    basic_reply = _match_basic_interaction(pl)
    if basic_reply:
        return basic_reply

    # Proactively queue learning for strategic domains.
    detected_domains = _extract_learning_domains(pl)
    _queue_domain_learning_topics(pl)

    # Web search must be explicitly requested by the user.
    web_trigger = _is_explicit_search_request(raw_prompt, pl)

    # For key learning domains, prefer clarification over uncertain local generation.
    if detected_domains and not web_trigger:
        domain_label = ", ".join(detected_domains)
        clarification = (
            f"I detected this is about {domain_label.replace('_', ' ')}. "
            "To avoid giving a wrong answer, can you clarify your exact goal, current level, and desired output format? "
            "If you want live references, say: 'search web: <topic>'."
        )
        _enqueue_background_research(raw_prompt, reason="domain_clarification")
        remember(prompt, clarification)
        return clarification
    
    # Build context from memory
    memory_snippets = fetch_all_ftp_memory()
    
    # PRIORITY 1: Check for exact/similar past responses (trained knowledge retention)
    exact_match = None
    for m in reversed(memory_snippets):
        if _normalize_user_text(m["prompt"]) == pl:
            exact_match = m["response"]
            break
    
    if exact_match:
        print(f"💾 Retrieved from memory: exact match found")
        remember(prompt, exact_match)
        return exact_match
    
    # PRIORITY 2: Find similar prompts for context
    relevant = [m for m in memory_snippets if any(w in prompt.lower() for w in m["prompt"].lower().split() if len(w) > 3)]
    memory_context = "\n".join([f"- {m['prompt']} → {m['response']}" for m in relevant[-5:]])

    # If intent is a question and not explicit search, ask for clarification before searching.
    if _is_question(pl, raw_prompt) and not web_trigger:
        clarification = CLARIFICATION_TEMPLATE
        _enqueue_background_research(raw_prompt, reason="question_clarification")
        remember(prompt, clarification)
        return clarification
    
    # PRIORITY 3: Multi-source search if triggered
    web_info = ""
    web_context = ""
    if web_trigger:
        verified = search_web_verified(raw_prompt)
        web_info = verified.get("text")
        if web_info:
            print(f"🌐 Gathered and verified external sources...")
            # Train only on cross-verified snippets.
            try:
                snippet_texts = [
                    h.get("snippet", "")
                    for h in verified.get("hits", [])
                    if h.get("verification_status") == "supported"
                    and h.get("confidence", 0) >= MIN_LEARNING_CONFIDENCE
                    and h.get("snippet")
                ]
                if snippet_texts:
                    model.train_on_text(snippet_texts, epochs=1)
            except Exception as e:
                print(f"⚠️ Learning from gathered sources failed: {str(e)}")
            
            # Use gathered info as context for conversation
            web_context = web_info
            # Return web results if available (they're already formatted with verification)
            if web_context:
                remember(prompt, web_context)
                return web_context
    
    # PRIORITY 4: Optional Fetch.ai provider (if configured)
    fetchai_reply = _fetchai_generate_response(prompt, memory_context=memory_context, web_context=web_context)
    if fetchai_reply:
        remember(prompt, fetchai_reply)
        return fetchai_reply
    
    # Generate a conversational response using the language model
    try:
        # Pass direct user input to avoid false intent triggers from injected context text.
        response = model.generate_response(prompt, max_length=200)
        if not response or response.strip() == "" or response == "PeakeBot:":
            # Fallback for open-ended questions
            response = f"That's an interesting question about '{prompt}'. I'm learning more about that topic. Feel free to tell me more or ask something else!"
            # Queue this topic for autonomous learning
            keywords = re.findall(r"\b[a-z]{4,}\b", prompt.lower())
            if keywords:
                add_to_learning_queue(keywords[0])
        elif _response_seems_low_confidence(response):
            _enqueue_background_research(raw_prompt, reason="low_confidence_response")
            response = CLARIFICATION_TEMPLATE
    except Exception as e:
        print(f"⚠️ Model error: {str(e)}")
        _enqueue_background_research(raw_prompt, reason="model_exception")
        response = CLARIFICATION_TEMPLATE
    
    # Clean up response if it contains system artifacts
    response = response.replace("PeakeBot:", "").replace("SYSTEM:", "").strip()
    if not response:
        response = "I'm learning about that. Tell me more?"
    
    # Remember this interaction
    remember(prompt, response)
    return response

def post_to_hive(title, body):
    hive = init_hive()
    tags = ["peakecoin", "ai", "bot"]
    permlink = "peakebot-" + datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        if NectarHive is not None:
            hive.post(title, body, author="peake.matic", permlink=permlink, tags=tags)
        elif BeemAccount is not None:
            account = BeemAccount("peake.matic", blockchain_instance=hive)
            account.post(title, body, author="peake.matic", permlink=permlink, tags=tags)
        else:
            raise Exception("No Hive posting client available. Install hive-nectar or beem.")
        print(f"✅ Posted to Hive as {permlink}")
    except Exception as e:
        print("❌ Failed to post to Hive:", str(e))

def save_to_geocities(entry):
    """Save entry to GeoCities as daily JSON groups with 100MB max-part rollover."""
    try:
        ftp = FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        ftp.cwd(FTP_BASE_DIR)

        files = []
        try:
            files = ftp.nlst()
        except Exception:
            files = []

        day_str = datetime.now().strftime("%Y%m%d")
        day_parts = _find_daily_knowledge_parts(files, day_str)

        # Load latest daily part if present, otherwise start part 1.
        if day_parts:
            current_part_num, current_filename = day_parts[-1]
            local_group_path = _tmp_path(current_filename)
            try:
                with open(local_group_path, "wb") as f:
                    ftp.retrbinary(f"RETR {current_filename}", f.write)
                with open(local_group_path, "r", encoding="utf-8") as f:
                    group_entries = json.load(f)
            except Exception:
                group_entries = []
        else:
            current_part_num = 1
            current_filename = f"{KNOWLEDGE_GROUP_PREFIX}_{day_str}_part{current_part_num}.json"
            local_group_path = _tmp_path(current_filename)
            group_entries = []

        candidate_entries = list(group_entries)
        candidate_entries.append(entry)
        candidate_bytes = _serialize_json_bytes(candidate_entries)

        # Rollover to next part when current daily part exceeds max size.
        if len(candidate_bytes) > KNOWLEDGE_GROUP_MAX_BYTES and group_entries:
            current_part_num += 1
            current_filename = f"{KNOWLEDGE_GROUP_PREFIX}_{day_str}_part{current_part_num}.json"
            local_group_path = _tmp_path(current_filename)
            group_entries = [entry]
            candidate_bytes = _serialize_json_bytes(group_entries)

        with open(local_group_path, "wb") as f:
            f.write(candidate_bytes)

        with open(local_group_path, "rb") as file:
            ftp.storbinary(f"STOR {current_filename}", file)

        print(f"📦 Saved to {current_filename} ({len(candidate_bytes) / (1024 * 1024):.2f} MB)")
        
        # Update rolling working-memory cache for fast reads and webpage output.
        memory = []
        try:
            local_path = _tmp_path("memory.json")
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR memory.json", f.write)
            with open(local_path, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except:
            memory = []
        
        memory.append(entry)
        memory = _dedupe_entries(memory)[-WORKING_MEMORY_MAX_ENTRIES:]
        
        local_path = _tmp_path("memory.json")
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2)
        
        with open(local_path, "rb") as file:
            ftp.storbinary("STOR memory.json", file)
        
        ftp.quit()
        print(f"📁 Memory saved to GeoCities (working memory: {len(memory)} entries)")
    except Exception as e:
        print("❌ FTP Upload failed:", str(e))

def generate_webpage(entries):
    html_content = """
    <html>
    <head><title>PeakeBot Journal</title></head>
    <body>
    <h1>🧠 PeakeBot Public Journal</h1>
    <p>AI entries generated by PeakeBot running on Raspberry Pi and published to GeoCities</p>
    <hr>
    """
    for entry in reversed(entries):
        html_content += f"<div><h3>{entry['timestamp']}</h3><p><b>You:</b> {entry['prompt']}<br><b>PeakeBot:</b> {entry['response']}</p><hr></div>"
    html_content += "</body></html>"

    local_path = _tmp_path("index.html")
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    try:
        ftp = FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        ftp.cwd(FTP_BASE_DIR)
        with open(local_path, "rb") as file:
            ftp.storbinary("STOR index.html", file)
        ftp.quit()
        print("🌍 Updated PeakeBot journal webpage on GeoCities.")
    except Exception as e:
        print("❌ FTP Upload (HTML) failed:", str(e))

def interactive_loop():
    print("🧠 PeakeBot ready. Type your message below:")
    print("Commands: 'train' to teach new responses, 'learn' to process learning queue (and Fetch.ai self-suggestions if enabled), 'queue [topic]' to add topic, 'save' to save learning, 'exit' to quit\n")
    training_mode = False
    
    while True:
        prompt = input("You: ").strip()
        
        if not prompt:
            continue
            
        if prompt.lower() == "exit" or prompt.lower() == "quit":
            print("👋 Goodbye!")
            break
        
        if prompt.lower() == "learn":
            process_learning_queue(max_topics=3)
            continue
        
        if prompt.lower().startswith("queue "):
            topic = prompt[6:].strip()
            if topic:
                add_to_learning_queue(topic)
            continue
        
        if prompt.lower() == "train":
            training_mode = not training_mode
            if training_mode:
                print("📚 Training mode ON. Enter pairs of [input] [response] separated by | (e.g., 'hello there | hi, how are you?')")
                print("Type 'done' when finished.\n")
            else:
                print("📚 Training mode OFF\n")
            continue
        
        if prompt.lower() == "save":
            model.save_model("language_model.pkl")
            print("💾 Model saved!\n")
            continue
        
        if training_mode:
            if prompt.lower() == "done":
                training_mode = False
                print("📚 Training complete. Responses will improve over time!\n")
                continue
            
            # Parse training data
            if "|" in prompt:
                parts = prompt.split("|")
                if len(parts) == 2:
                    user_input = parts[0].strip()
                    desired_response = parts[1].strip()
                    # Train model with this example
                    model.train_on_text([user_input + " " + desired_response], epochs=1)
                    print(f"✅ Learned: '{user_input}' -> '{desired_response}'\n")
                    continue
            
            print("❌ Format: input | response\n")
            continue
        
        # Normal conversation mode
        response = generate_response(prompt)
        print("PeakeBot:", response)
        print()

        if "post this" in prompt.lower():
            post_to_hive("🧠 PeakeBot Insight", response)

if __name__ == "__main__":
    interactive_loop()
