import json
import os
import time
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
VERIFICATION_STOPWORDS = {
    "about", "after", "again", "also", "and", "been", "being", "from", "have",
    "into", "more", "most", "only", "that", "their", "there", "these", "they",
    "this", "those", "very", "what", "when", "where", "with", "would", "your",
    "while", "which", "could", "should", "will", "just", "than", "then"
}


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
    """Generate response using language model, memory, and web search"""
    # Check if user is asking for web search or included a URL/domain
    pl = prompt.lower()
    web_trigger = any(phrase in pl for phrase in ["search", "look up", "find out", "what is", "who is", "when did", "how do"]) or bool(_extract_url_candidate(pl))
    
    # Build context from memory
    memory_snippets = fetch_all_ftp_memory()
    
    # PRIORITY 1: Check for exact/similar past responses (trained knowledge retention)
    exact_match = None
    for m in reversed(memory_snippets):
        if m["prompt"].lower().strip() == pl.strip():
            exact_match = m["response"]
            break
    
    if exact_match:
        print(f"💾 Retrieved from memory: exact match found")
        remember(prompt, exact_match)
        return exact_match
    
    # PRIORITY 2: Find similar prompts for context
    relevant = [m for m in memory_snippets if any(w in prompt.lower() for w in m["prompt"].lower().split() if len(w) > 3)]
    memory_context = "\n".join([f"- {m['prompt']} → {m['response']}" for m in relevant[-5:]])
    
    # PRIORITY 3: Multi-source search if triggered
    web_info = ""
    web_context = ""
    if web_trigger:
        verified = search_web_verified(prompt)
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
    
    # Build rich context for the model
    full_context = "SYSTEM: You are PeakeBot, a helpful and friendly AI assistant. You are knowledgeable about Hive, cryptocurrency, and many topics. Be conversational, warm, and remember what you've learned. Keep responses concise but informative.\n\n"
    
    if memory_context:
        full_context += "📚 PAST INTERACTIONS:\n" + memory_context + "\n\n"
    if web_context:
        full_context += "🌐 RECENT GATHERED KNOWLEDGE:\n" + web_context + "\n"
        full_context += "Use only [verified] entries for confident claims. For [unverified] entries, clearly mark uncertainty and invite verification.\n\n"
    
    full_context += f"USER: {prompt}\nPeakeBot:"
    
    # Generate a conversational response using the language model
    try:
        response = model.generate_response(full_context, max_length=200)
        if not response or response.strip() == "" or response == "PeakeBot:":
            response = "I'm processing that... let me think about it for a moment."
            # Queue this topic for autonomous learning
            keywords = re.findall(r"\b[a-z]{4,}\b", prompt.lower())
            if keywords:
                add_to_learning_queue(keywords[0])
    except Exception as e:
        print(f"⚠️ Model error: {str(e)}")
        response = "I encountered an issue generating a response, but I'm learning!"
    
    # Clean up response if it contains system artifacts
    response = response.replace("PeakeBot:", "").replace("SYSTEM:", "").strip()
    if not response:
        response = "I'm still learning about that topic!"
    
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
    print("Commands: 'train' to teach new responses, 'learn' to process learning queue, 'queue [topic]' to add topic, 'save' to save learning, 'exit' to quit\n")
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
