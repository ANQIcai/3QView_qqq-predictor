import logging
import os
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

ALPHAVANTAGE_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")

_QQQ_TOP10 = {"QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "TSLA"}

# Individual holdings queried for Finnhub company-news (QQQ is an ETF — less useful)
_HOLDINGS_FOR_NEWS = ["AAPL", "MSFT", "NVDA", "AMZN", "META"]

# ── Trusted financial sources ──────────────────────────────────────────────────
_TRUSTED_SOURCES = {
    "reuters", "bloomberg", "cnbc", "financial times", "ft.com",
    "wall street journal", "wsj", "marketwatch", "barron", "seeking alpha",
    "yahoo finance", "yahoo", "the economist", "associated press", "ap news",
    "federal reserve", "sec.gov", "sec filing", "investopedia",
    "morningstar", "the motley fool", "business insider",
    # Additional sources commonly returned by Finnhub
    "benzinga", "thestreet", "marketbeat", "forbes", "fortune",
    "axios", "techcrunch", "the verge", "the information",
    "business wire", "pr newswire", "globe newswire",
}

# ── Relevance keyword weights (higher = more QQQ-relevant) ────────────────────
_TOPIC_KEYWORDS: dict[str, float] = {
    # Fed & Rates
    "federal reserve": 1.0, "fomc": 1.0, "rate cut": 1.0, "rate hike": 1.0,
    "interest rate": 1.0, "monetary policy": 1.0, "powell": 0.9,
    "hawkish": 0.9, "dovish": 0.9, "bps": 0.8, "fed funds": 1.0,
    "quantitative tightening": 0.9, "quantitative easing": 0.9,
    "yield curve": 1.0, "treasury yield": 1.0, "10-year yield": 1.0,
    "inflation": 0.9, "cpi": 1.0, "pce": 1.0, "fed": 0.7,
    # Economic data
    "nonfarm payroll": 1.0, "jobs report": 1.0, "unemployment": 0.9,
    "gdp": 1.0, "retail sales": 0.9, "pmi": 0.8, "ism": 0.8,
    "consumer confidence": 0.8, "housing starts": 0.7, "durable goods": 0.7,
    "nfp": 1.0,
    # Mega-cap earnings/guidance
    "earnings": 0.9, "revenue": 0.8, "eps": 0.9, "guidance": 0.9,
    "quarterly results": 0.9, "profit warning": 0.9, "margin": 0.7,
    "nvidia": 1.0, "nvda": 1.0, "microsoft": 0.9, "msft": 0.9,
    "apple": 0.9, "aapl": 0.9, "amazon": 0.9, "amzn": 0.9,
    "meta platforms": 0.9, "meta": 0.8, "google": 0.8, "alphabet": 0.8,
    "googl": 0.9, "broadcom": 0.8, "avgo": 0.9, "tesla": 0.8, "tsla": 0.8,
    # AI / Tech
    "artificial intelligence": 0.9, "ai chip": 1.0, "semiconductor": 0.9,
    "data center": 0.8, "cloud computing": 0.8, "llm": 0.8,
    "antitrust": 0.8, "tech regulation": 0.8, "export control": 0.9,
    # Trade & Geopolitics
    "tariff": 1.0, "trade war": 1.0, "sanctions": 0.8, "china": 0.7,
    "supply chain": 0.7, "trade policy": 0.9,
    # Market structure
    "nasdaq": 0.9, "s&p 500": 0.9, "sp500": 0.9, "circuit breaker": 1.0,
    "vix": 0.9, "put/call": 0.9, "market crash": 1.0, "correction": 0.8,
    "bear market": 0.9, "bull market": 0.9, "selloff": 0.9,
    # Bond/credit
    "treasury": 0.8, "bond market": 0.9, "credit spread": 0.9,
    "debt ceiling": 0.9, "10y yield": 1.0,
}

# ── Category classification ────────────────────────────────────────────────────
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Fed & Rates": [
        "fed", "federal reserve", "fomc", "rate", "bps", "monetary", "powell",
        "hawkish", "dovish", "quantitative", "interest rate",
        "yield curve", "treasury", "inflation", "cpi", "pce",
    ],
    "Earnings": [
        "earnings", "revenue", "eps", "quarterly", "guidance", "profit",
        "beat", "miss", "q1", "q2", "q3", "q4", "results", "outlook",
        "sales", "income", "margin", "nvidia", "apple", "microsoft", "amazon",
        "meta", "google", "alphabet", "broadcom", "tesla",
    ],
    "Trade & Geopolitics": [
        "tariff", "trade war", "china", "geopolit", "sanction", "war",
        "ukraine", "taiwan", "russia", "nato", "export control",
        "supply chain", "trade policy",
    ],
    "Economic Data": [
        "gdp", "jobs report", "unemployment", "payroll", "pce", "ism", "pmi",
        "housing", "retail sales", "consumer", "nonfarm", "cpi", "inflation data",
        "durable goods", "consumer confidence", "nfp",
    ],
    "Tech & AI": [
        "ai", "artificial intelligence", "semiconductor", "chip",
        "llm", "antitrust", "tech regulation", "cloud", "software",
        "data center", "nvidia", "microsoft", "google", "apple", "amazon",
        "meta", "avgo", "broadcom", "export control",
    ],
    "Market Structure": [
        "nasdaq", "s&p 500", "sp500", "rally", "selloff", "correction",
        "bull market", "bear market", "vix", "volatility", "investor sentiment",
        "circuit breaker", "options", "put/call", "short selling",
    ],
}

# ── Source priority for deduplication (lower = more prestigious) ──────────────
_SOURCE_PRIORITY: dict[str, int] = {
    "reuters": 1, "bloomberg": 2, "financial times": 3, "ft.com": 3,
    "wall street journal": 4, "wsj": 4, "cnbc": 5, "the economist": 5,
    "associated press": 6, "ap news": 6, "marketwatch": 7, "barron": 7,
    "seeking alpha": 8, "yahoo finance": 9,
}

_AV_SENTIMENT_MAP = {
    "Bullish":          (0.7, "Bullish"),
    "Somewhat-Bullish": (0.3, "Bullish"),
    "Neutral":          (0.0, "Neutral"),
    "Somewhat-Bearish": (-0.3, "Bearish"),
    "Bearish":          (-0.7, "Bearish"),
}

# Module-level digest cache (persists across Streamlit reruns within same process)
_digest_cache: dict = {"digest": None, "sentiment": None, "key_risk": None, "generated_at": None}


@dataclass
class NewsArticle:
    title: str
    summary: str
    source: str
    url: str
    published: datetime
    sentiment: float           # -1.0 to +1.0
    sentiment_label: str       # "Bullish" / "Bearish" / "Neutral"
    tickers: list = field(default_factory=list)
    relevance: float = 0.5     # 0–1 (from API, legacy)
    relevance_score: float = 0.0  # computed strict score
    category: str = "Market Structure"


# ── Relevance scoring ─────────────────────────────────────────────────────────

def _is_trusted_source(source: str) -> bool:
    sl = source.lower()
    return any(ts in sl for ts in _TRUSTED_SOURCES)


def _compute_relevance_score(article: "NewsArticle") -> float:
    """
    Score 0–1 based on keyword relevance, ticker mentions, and source trust.

    Formula:
      raw = kw_score × 0.6 + ticker_bonus × 0.4
      Then apply an additive trust penalty (–0.15) for untrusted sources.
      This keeps untrusted-but-relevant articles scoreable (max ~0.57 vs
      the old multiplicative approach that hard-capped them at 0.288).
    """
    text = (article.title + " " + article.summary).lower()

    # Ticker bonus
    ticker_bonus = 0.3 if any(t.lower() in text for t in _QQQ_TOP10) else 0.0

    # Keyword score (sum of matched weights, normalised to 0–1)
    kw_score = 0.0
    for kw, weight in _TOPIC_KEYWORDS.items():
        if kw in text:
            kw_score += weight
    kw_score = min(kw_score, 2.5) / 2.5  # normalise

    raw = kw_score * 0.6 + ticker_bonus * 0.4

    # Additive source trust penalty — untrusted sources lose 0.15 points,
    # but a highly relevant article from Benzinga can still pass the 0.3 threshold
    if not _is_trusted_source(article.source):
        raw -= 0.15

    return min(max(round(raw, 3), 0.0), 1.0)


def categorize(article: "NewsArticle") -> str:
    text = (article.title + " " + article.summary).lower()
    best_cat, best_count = "Market Structure", 0
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count, best_cat = count, cat
    return best_cat


def _source_rank(source: str) -> int:
    s = source.lower()
    for name, rank in _SOURCE_PRIORITY.items():
        if name in s:
            return rank
    return 10


# ── Fetchers ──────────────────────────────────────────────────────────────────

def fetch_alphavantage_news() -> list:
    if not ALPHAVANTAGE_KEY:
        return []
    url = (
        "https://www.alphavantage.co/query"
        "?function=NEWS_SENTIMENT"
        "&tickers=QQQ,AAPL,MSFT,NVDA,AMZN,META,GOOGL,AVGO"
        "&sort=LATEST&limit=50"
        f"&apikey={ALPHAVANTAGE_KEY}"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return []

    # Detect rate limit or API errors explicitly so they don't silently look like empty data
    if "Information" in data or "Note" in data:
        log.debug("[news] Alpha Vantage rate limit/error: %s", data.get('Information', data.get('Note', ''))[:120])
        return []

    if "feed" not in data:
        log.debug("[news] Alpha Vantage unexpected response keys: %s", list(data.keys())[:5])
        return []

    articles = []
    for item in data["feed"]:
        try:
            published = datetime.strptime(item["time_published"], "%Y%m%dT%H%M%S")
            raw_score = float(item.get("overall_sentiment_score", 0.0))
            raw_label = item.get("overall_sentiment_label", "Neutral")
            _, sentiment_label = _AV_SENTIMENT_MAP.get(raw_label, (0.0, "Neutral"))
            tickers = [
                ts["ticker"] for ts in item.get("ticker_sentiment", [])
                if ts["ticker"] in _QQQ_TOP10
            ]
            relevance_scores = [
                float(ts.get("relevance_score", 0))
                for ts in item.get("ticker_sentiment", [])
                if ts["ticker"] in _QQQ_TOP10
            ]
            relevance = max(relevance_scores) if relevance_scores else 0.1
            a = NewsArticle(
                title=item.get("title", ""),
                summary=item.get("summary", "")[:500],
                source=item.get("source", ""),
                url=item.get("url", ""),
                published=published,
                sentiment=max(-1.0, min(1.0, raw_score)),
                sentiment_label=sentiment_label,
                tickers=tickers,
                relevance=relevance,
            )
            a.relevance_score = _compute_relevance_score(a)
            a.category = categorize(a)
            articles.append(a)
        except Exception:
            continue
    return articles


def _finnhub_items_to_articles(items: list) -> list:
    """Convert raw Finnhub JSON items to NewsArticle list."""
    articles = []
    for item in items:
        try:
            published = datetime.fromtimestamp(item.get("datetime", 0))
            text = (item.get("headline", "") + " " + item.get("summary", "")).upper()
            tickers = [t for t in _QQQ_TOP10 if t in text]
            a = NewsArticle(
                title=item.get("headline", ""),
                summary=item.get("summary", "")[:500],
                source=item.get("source", "Finnhub"),
                url=item.get("url", ""),
                published=published,
                sentiment=0.0,
                sentiment_label="Neutral",
                tickers=tickers,
                relevance=0.5 if tickers else 0.2,
            )
            a.relevance_score = _compute_relevance_score(a)
            a.category = categorize(a)
            articles.append(a)
        except Exception:
            continue
    return articles


def fetch_finnhub_news() -> list:
    """
    Fetch from three Finnhub sources:
      1. General news (category=general) — broad market headlines
      2. Company-news for top 5 QQQ holdings — earnings/guidance/tech news
         (QQQ itself as an ETF returns minimal company-specific coverage)
    Uses a 3-day lookback to avoid weekend/holiday gaps.
    """
    if not FINNHUB_KEY:
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    lookback = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    endpoints = [
        f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_KEY}",
    ]
    # Add company-news for each top holding (not QQQ — it's an ETF with sparse results)
    for sym in _HOLDINGS_FOR_NEWS:
        endpoints.append(
            f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={lookback}&to={today}&token={FINNHUB_KEY}"
        )

    articles = []
    for url in endpoints:
        try:
            resp = requests.get(url, timeout=10)
            items = resp.json()
            if not isinstance(items, list):
                log.debug("[news] Finnhub unexpected response from %s: %s", url[:60], str(items)[:80])
                continue
            # Cap per-endpoint to avoid drowning in one source
            articles.extend(_finnhub_items_to_articles(items[:30]))
        except Exception as exc:
            log.debug("[news] Finnhub fetch error for %s: %s", url[:60], exc)
            continue
    return articles


# ── Deduplication ─────────────────────────────────────────────────────────────

def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _deduplicate(articles: list) -> list:
    """Deduplicate by title similarity >80%; keep higher source-priority version."""
    unique = []
    for article in articles:
        dup_idx = next(
            (i for i, u in enumerate(unique) if _similar(article.title, u.title) > 0.8),
            None,
        )
        if dup_idx is None:
            unique.append(article)
        elif _source_rank(article.source) < _source_rank(unique[dup_idx].source):
            unique[dup_idx] = article
    return unique


_RELEVANCE_THRESHOLD = 0.3       # primary filter (lowered from 0.6)
_FALLBACK_MIN_ARTICLES = 3       # if fewer pass, use fallback unfiltered pool
_FALLBACK_POOL_SIZE = 8          # how many fallback articles to show


def fetch_all_news() -> list:
    """
    Fetch both sources, deduplicate, filter by relevance, sort newest first.

    Filter pipeline:
      1. Freshness: published within last 72h (widened from 24h to survive weekends
         and AV rate-limit gaps)
      2. Relevance: score >= 0.3 (lowered from 0.6 — the original 0.6 threshold
         was unreachable for most Finnhub sources due to source_mult=0.4 penalty)
      3. Fallback: if <3 articles pass, include top articles by score from the
         72h pool, tagged with relevance_score=-1.0 to signal "unfiltered" in UI
    """
    av = fetch_alphavantage_news()
    fh = fetch_finnhub_news()
    merged = _deduplicate(av + fh)
    log.debug("[news] raw: %d AV + %d FH = %d after dedup", len(av), len(fh), len(merged))

    cutoff = datetime.now() - timedelta(hours=72)
    fresh = [a for a in merged if a.published >= cutoff]
    log.debug("[news] fresh (72h): %d", len(fresh))

    filtered = [a for a in fresh if a.relevance_score >= _RELEVANCE_THRESHOLD]
    filtered.sort(key=lambda a: a.published, reverse=True)
    log.debug("[news] after relevance filter (>=%s): %d", _RELEVANCE_THRESHOLD, len(filtered))

    if len(filtered) < _FALLBACK_MIN_ARTICLES:
        # Fallback: top articles by score from 72h pool, regardless of threshold
        fallback_pool = sorted(
            [a for a in fresh if a not in filtered],
            key=lambda a: a.relevance_score,
            reverse=True,
        )[:_FALLBACK_POOL_SIZE]
        for a in fallback_pool:
            a.relevance_score = -1.0  # flag as unfiltered for optional UI badge
        filtered = filtered + fallback_pool
        filtered.sort(key=lambda a: a.published, reverse=True)
        log.debug("[news] fallback added %d articles, total=%d", len(fallback_pool), len(filtered))

    return filtered


# ── AI Market Digest ──────────────────────────────────────────────────────────

def generate_market_digest(articles: list) -> dict:
    """
    Call Claude Haiku with top 10 headlines to produce a 3-sentence market
    digest. Internally cached for 10 minutes; returns cached result if fresh.
    """
    if (
        _digest_cache["generated_at"] is not None
        and (datetime.now() - _digest_cache["generated_at"]).total_seconds() < 600
        and _digest_cache["digest"] is not None
    ):
        return dict(_digest_cache)

    if not articles:
        result = {"digest": "No market-relevant news available.", "sentiment": "Neutral",
                  "key_risk": "Insufficient data", "generated_at": datetime.now()}
        _digest_cache.update(result)
        return result

    import anthropic
    client = anthropic.Anthropic()

    headlines = "\n".join([
        f"- [{a.category}] [{a.sentiment_label}] {a.title} ({a.source})"
        for a in articles[:10]
    ])
    prompt = (
        "You are a senior market analyst. Based on these headlines, write a 3-sentence "
        "market digest summarising what matters for QQQ today. Be specific — reference "
        "the actual news.\n\n"
        f"Headlines:\n{headlines}\n\n"
        "Format your response exactly as:\n"
        "[DIGEST] <3 sentences>\n"
        "[SENTIMENT: Bullish/Bearish/Neutral]\n"
        "[KEY RISK: one sentence]"
    )

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text
        digest, sentiment, key_risk = "", "Neutral", ""
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("[DIGEST]"):
                digest = line[len("[DIGEST]"):].strip()
            elif line.startswith("[SENTIMENT:"):
                sentiment = line.replace("[SENTIMENT:", "").replace("]", "").strip()
            elif line.startswith("[KEY RISK:"):
                key_risk = line.replace("[KEY RISK:", "").replace("]", "").strip()
        if not digest:
            digest = text[:400]
        result = {"digest": digest, "sentiment": sentiment,
                  "key_risk": key_risk, "generated_at": datetime.now()}
    except Exception as e:
        result = {"digest": f"Digest unavailable ({str(e)[:60]})", "sentiment": "Neutral",
                  "key_risk": "N/A", "generated_at": datetime.now()}

    _digest_cache.update(result)
    return dict(_digest_cache)


# ── Scenario builder ──────────────────────────────────────────────────────────

def build_scenario_from_news(digest: dict, articles: list, regime: str) -> str:
    """Auto-build the simulation scenario from the AI digest + top headlines."""
    digest_text = digest.get("digest", "")
    if not digest_text and articles:
        digest_text = "; ".join(a.title for a in articles[:3])
    top_tickers = list({t for a in articles[:5] for t in a.tickers})[:4]
    tickers_str = f" Key movers: {', '.join(top_tickers)}." if top_tickers else ""
    return f"{digest_text}{tickers_str} Market regime: {regime}."


# ── Agent formatting ──────────────────────────────────────────────────────────

def get_news_briefing(articles: list, n: int = 10, categories: list = None) -> str:
    """
    Return latest n FILTERED articles as a structured text block for agent prompts.
    Optionally filter by category list (e.g. ["Fed & Rates", "Economic Data"]).
    """
    if not articles:
        return ""
    if categories:
        prioritised = [a for a in articles if a.category in categories]
        rest = [a for a in articles if a.category not in categories]
        pool = (prioritised + rest)[:n]
    else:
        pool = articles[:n]

    lines = ["## Current News Briefing (Latest Headlines — reference these in your reasoning)"]
    for i, a in enumerate(pool, 1):
        ago = time_ago(a.published)
        tickers_str = f" [{', '.join(a.tickers)}]" if a.tickers else ""
        lines.append(
            f"{i}. [{a.category}] [{a.sentiment_label}] {a.title}{tickers_str} — {a.source} ({ago})\n"
            f"   {a.summary[:220]}"
        )
    return "\n".join(lines)


def format_for_agents(articles: list, n: int = 10) -> str:
    """Format top-n articles as a structured briefing for agent prompts."""
    return get_news_briefing(articles, n)


def time_ago(dt: datetime) -> str:
    delta = datetime.now() - dt
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{delta.days}d ago"
