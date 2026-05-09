# Multi-Engine Smart Search & Cross-Verification

## Overview

PeakeBot now integrates **5 independent search engines + Hive + direct URLs** for powerful cross-verification of information. This makes the bot "smarter" by comparing data across diverse sources and assigning confidence scores based on how many sources corroborate each finding.

## Search Engines Integrated

### 1. **Google News** (news source)
- **Reliability Weight**: 0.75
- **Purpose**: Real-time news and recent articles
- **Use Case**: Breaking news, current events, trending topics
- **API**: Google News RSS feed (no key required)

### 2. **DuckDuckGo** (privacy-focused web search)
- **Reliability Weight**: 0.70
- **Purpose**: General web search results from privacy-respecting search
- **Use Case**: Finding alternative perspectives, avoiding Google's tracking
- **API**: DuckDuckGo public JSON endpoint (no key required)

### 3. **Wikipedia** (factual knowledge base)
- **Reliability Weight**: 0.85 ⭐ (highest)
- **Purpose**: Factual definitions, concepts, historical information
- **Use Case**: Verifying facts, understanding terminology, context
- **API**: Wikipedia public API (MediaWiki)

### 4. **Bing News** (Microsoft's news aggregator)
- **Reliability Weight**: 0.70
- **Purpose**: News stories and articles from Bing's index
- **Use Case**: Cross-checking news from another major engine
- **API**: Bing News RSS feed (no key required)

### 5. **Hive Blockchain** (community posts)
- **Reliability Weight**: 0.65
- **Purpose**: Community-generated content, cryptocurrency/web3 discussion
- **Use Case**: Community insights, blockchain-specific info
- **Filter**: Author reputation minimum (default 50.0 score)

### 6. **Direct URLs** (source websites)
- **Reliability Weight**: 0.70
- **Purpose**: Original source material, whitepapers, documentation
- **Use Case**: Verified from the source itself

## How Cross-Verification Works

### Confidence Scoring Algorithm

Each result gets a **confidence score (0.0 — 0.97)** based on:

1. **Source Reliability Weight**
   - Wikipedia highest (0.85)
   - News sources (0.75)
   - Search engines, direct URLs (0.70)
   - Hive posts (0.65)

2. **Cross-Source Corroboration**
   - If found in **1+ independent sources**: `status = "supported"` ✅
   - Confidence boosted: `0.12 per additional supporting source`
   - If **no corroboration**: status = "unverified" ⚠️
   - Confidence reduced to 50% base

3. **Token Overlap Verification**
   - Minimum 4 shared keywords required to mark "supporting"
   - Stops words (and, the, for, etc.) excluded
   - Compares title + snippet across all sources

### Example Verification Flow

```
Query: "What is blockchain?"

Results gathered:
- Wikipedia: "Blockchain is a distributed ledger..." (weight: 0.85)
- Hive posts: "Blockchain enables web3..." (weight: 0.65)
- DuckDuckGo: "Blockchain technology underpins..." (weight: 0.70)

Token overlap check:
- Wikipedia ↔ Hive: 6 shared tokens → MATCH ✅
- Wikipedia ↔ DuckDuckGo: 5 shared tokens → MATCH ✅

Final scores:
- Wikipedia: 0.97 confidence (0.85 + 0.12 for 2 supporting sources)
- Hive: 0.89 confidence (0.65 + 0.24 for 2 supporting sources)
- DuckDuckGo: 0.94 confidence (0.70 + 0.24 for 2 supporting sources)

Output: ✅ 3/3 items verified across independent sources!
```

## Using the Multi-Engine Search

### In Terminal Mode

```python
from peakebot import search_web_verified

# Automatic search across all engines
results = search_web_verified("cryptocurrency regulation 2026")

# Returns dict with:
# - hits: list of verified results with confidence scores
# - text: formatted summary with verification status
```

### In Web App (Flask/Browser)

```bash
POST /api/chat
{
  "prompt": "What is happening with Bitcoin?"
}

# Response includes cross-verified results from all 6+ sources
```

### Example Output

```
🔍 Verification summary: 5/8 items corroborated by independent sources.
📊 Sources consulted: 6 different search engines/sources.

- [✅ verified] (wikipedia) Cryptocurrency is digital money...
  📝 Blockchain enables peer-to-peer transactions...
  💯 confidence: 0.95 | 🔗 https://...
  💭 Cross-checked with 3 additional source(s).

- [⚠️ unverified] (hive) Latest token speculation post...
  📝 Discussing upcoming altcoin...
  💯 confidence: 0.38 | 🔗 https://...
  💭 No corroboration found across independent sources.
```

## Benefits Over Single-Source Search

| Metric | Old (1 source) | New (6+ sources) |
|--------|---|---|
| **Data Sources** | Google News only | 5 search engines + Hive + URLs |
| **Fact Verification** | No cross-check | Token overlap verification |
| **Confidence Score** | N/A | 0.0–0.97 with supporting evidence |
| **Bias Mitigation** | Single algorithm bias | Different crawlers & indexes |
| **Coverage** | News-centric | News + Facts + Web + Community |
| **Privacy** | Tracked by Google | Option for DuckDuckGo + others |

## Configuration

### Adjust Verification Sensitivity

Edit constants in `peakebot.py`:

```python
VERIFICATION_MIN_SHARED_TOKENS = 4  # Require minimum 4 tokens to match
MIN_LEARNING_CONFIDENCE = 0.6       # Only learn from 60%+ confidence
MIN_HIVE_AUTHOR_REPUTATION = 50.0   # Filter Hive posts by reputation
```

### Adjust Source Weights

Modify `_source_reliability_weight()` to change how much each source contributes:

```python
def _source_reliability_weight(source: str) -> float:
    source_weights = {
        "wikipedia": 0.85,      # Increase if you trust Wiki more
        "news": 0.75,
        "bing": 0.70,
        "duckduckgo": 0.70,
        "hive": 0.65,           # Decrease if Hive posts less reliable
        "domain": 0.70,
        "url": 0.70,
    }
    return source_weights.get(source, 0.6)
```

## No New Dependencies Required ✅

All search engines use:
- **`requests`** - Already installed
- **`xml.etree.ElementTree`** - Built-in Python
- **`urllib.parse`** - Built-in Python

**No API keys needed!** All APIs are public endpoints.

## Performance Notes

- **Total search time**: ~3–5 seconds (parallel where possible)
- **Rate limiting**: 15 requests/60sec per IP (in web_app.py)
- **Fallback**: If one engine fails, others continue working
- **Graceful degradation**: Missing engine doesn't break results

## Future Enhancements

Potential additions:
- [ ] Perplexity AI search integration
- [ ] ArXiv for academic papers
- [ ] Reddit discussions for community perspectives
- [ ] Twitter/X sentiment analysis
- [ ] Custom source weighting per query type
- [ ] Machine learning to auto-rank source reliability

## Testing

Quick test to verify all engines working:

```bash
# Terminal
python
>>> from peakebot import search_web_verified
>>> result = search_web_verified("Python programming")
>>> print(result['text'])
```

Expected: Results from Wikipedia, Google News, DuckDuckGo, Bing, direct URLs

---

**Questions?** Check individual search function signatures in `peakebot.py` — each has detailed try/except logging.
