"""
api.py — FastAPI backend for OracleQQQ React frontend.

Data flow:
  React (localhost:3000)
      │  HTTP fetch
      ▼
  FastAPI (localhost:8000)
      ├── GET /api/market  → data + indicators + regime
      ├── GET /api/news    → articles + digest
      ├── GET /api/calendar → key dates / events
      ├── GET /api/consensus → top-holdings analyst consensus
      ├── GET /api/analogues → historical analogues (uses 5y OHLCV)
      └── POST /api/predict  → full 3-round, 5-agent simulation (~60-120s)
                                ↓
                            Anthropic API (15 Claude calls)

Notes:
- @st.cache_data in data.py works outside Streamlit via MemoryCacheStorageManager.
  It caches correctly in-process; startup emits harmless WARNING logs.
- /api/predict is intentionally blocking (~90s). React must use a 180s AbortController.
- Do NOT import history or aggregate_forecasts_institutional — unused here.
"""

import os
import logging
import datetime as _dt_module

# Suppress Streamlit's "No runtime found" warnings at FastAPI startup
logging.getLogger("streamlit").setLevel(logging.ERROR)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import data as data_mod
import indicators as ind_mod
import analogues as ana_mod
import news as news_mod
import live_data as ld_mod
from agents import run_simulation

app = FastAPI(title="OracleQQQ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_date_label(date_str: str) -> str:
    """Format YYYY-MM-DD as 'Jan 5' for chart XAxis labels."""
    try:
        dt = _dt_module.datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%b") + " " + str(dt.day)
    except Exception:
        return date_str


def _serialize_ohlcv(df) -> list:
    """Convert DataFrame to list of dicts with ISO date strings and lowercase column names.

    yfinance returns capitalized columns (Open, High, Low, Close, Volume).
    Lowercase them so the React chart reads d.open, d.close, etc.
    Also adds dateLabel ('Jan 5') for the CandlestickChart XAxis.
    """
    df = df.reset_index()
    # Rename date index
    if "Date" in df.columns:
        df = df.rename(columns={"Date": "date"})
    elif "index" in df.columns:
        df = df.rename(columns={"index": "date"})
    # Lowercase OHLCV columns
    col_lower = {c: c.lower() for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns}
    df = df.rename(columns=col_lower)
    df["date"] = df["date"].astype(str).str[:10]
    df["dateLabel"] = df["date"].apply(_make_date_label)
    return df.to_dict(orient="records")


def _serialize_forecast(f) -> dict:
    """Serialize a ForecastResult including agent identity fields."""
    return {
        "agent_name": f.agent_name,
        "round_num": f.round_num,
        "direction": f.direction,
        "confidence": f.confidence,
        "target_low": f.target_low,
        "target_high": f.target_high,
        "reasoning": f.reasoning,
        "status": f.status,
        "revised_from": f.revised_from,
    }


def _serialize_consensus(c) -> dict:
    """Serialize full Consensus including 5-layer institutional engine fields."""
    return {
        "consensus_target": c.consensus_target,
        "bull_prob": c.bull_prob,
        "base_prob": c.base_prob,
        "bear_prob": c.bear_prob,
        "bull_target": c.bull_target,
        "base_target": c.base_target,
        "bear_target": c.bear_target,
        "agent_count": c.agent_count,
        "avg_confidence": c.avg_confidence,
        "disagreement": c.disagreement,
        "disagreement_detail": c.disagreement_detail,
        "credible_low": c.credible_low,
        "credible_high": c.credible_high,
        "method": c.method,
        "conviction_score": c.conviction_score,
        "regime_label": c.regime_label,
        "upweighted_agents": c.upweighted_agents,
        "entropy_label": c.entropy_label,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/market")
def get_market():
    """OHLCV, indicators, macro context, and market regime."""
    try:
        df = data_mod.fetch_ohlcv("QQQ", period="1y")
        macro = data_mod.fetch_macro_context()
        price = data_mod.get_current_price(df)
        ind = ind_mod.compute_all(df)
        regime = ana_mod.detect_regime(df, vix=macro.get("vix"))
        ohlcv = _serialize_ohlcv(df[-252:])
        return {
            "ticker": "QQQ",
            "current_price": price,
            "ohlcv": ohlcv,
            "indicators": ind,
            "macro": macro,
            "regime": regime,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news")
def get_news():
    """Latest market news articles and digest summary."""
    try:
        articles = news_mod.fetch_all_news()
        raw_digest = news_mod.generate_market_digest(articles) if articles else {}
        # Convert datetime objects to ISO strings for JSON serialization
        digest = dict(raw_digest)
        if "generated_at" in digest and hasattr(digest["generated_at"], "isoformat"):
            digest["generated_at"] = digest["generated_at"].isoformat()
        return {
            "articles": [
                {
                    "title": a.title,
                    "source": a.source,
                    "sentiment": a.sentiment,
                    "sentiment_label": a.sentiment_label,
                    "category": a.category,
                    "tickers": a.tickers,
                    "url": a.url,
                    "published": a.published.isoformat() if hasattr(a.published, "isoformat") else str(a.published),
                }
                for a in articles
            ],
            "digest": digest,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/calendar")
def get_calendar():
    """Key dates: earnings, FOMC, economic releases, OPEX."""
    try:
        return {"events": ld_mod.get_all_key_dates()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/consensus")
def get_consensus():
    """Analyst consensus (buy/hold/sell) for QQQ top holdings."""
    try:
        return {"holdings": ld_mod.get_top_holdings_consensus()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analogues")
def get_analogues():
    """Historical analogues matched to current regime. Uses 5-year OHLCV so
    events back to 2018 are included (1-year df would miss most of them)."""
    try:
        df_5y = data_mod.fetch_ohlcv_5y()
        macro = data_mod.fetch_macro_context()
        regime = ana_mod.detect_regime(df_5y, vix=macro.get("vix"))
        results = ana_mod.find_analogues(df_5y, "", regime)
        return {
            "analogues": [
                {
                    "date": a.date,
                    "event": a.event_label,
                    "regime": a.regime,
                    "return_5d": a.return_5d,
                    "keyword_score": a.keyword_score,
                }
                for a in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/predict")
def predict():
    """Run the full 5-agent, 3-round debate simulation.

    WARNING: This endpoint blocks for ~60-120 seconds (15 Anthropic API calls).
    React callers MUST set AbortController timeout >= 180 seconds.
    """
    try:
        df_5y = data_mod.fetch_ohlcv_5y()
        df_1y = data_mod.fetch_ohlcv("QQQ", period="1y")
        macro = data_mod.fetch_macro_context()
        price = data_mod.get_current_price(df_1y)
        ind = ind_mod.compute_all(df_1y)
        regime = ana_mod.detect_regime(df_1y, vix=macro.get("vix"))

        articles = news_mod.fetch_all_news()
        digest = news_mod.generate_market_digest(articles) if articles else {}
        scenario = news_mod.build_scenario_from_news(digest, articles, regime)

        seed = {
            "ticker": "QQQ",
            "scenario": scenario,
            "price_history": df_1y,
            "current_price": price,
            "current_indicators": ind,
            "macro_context": macro,
            "regime": regime,
            "analogues": ana_mod.find_analogues(df_5y, scenario, regime),
            "live_news": articles,
            "live_news_text": news_mod.format_for_agents(articles),
            "live_quote": ld_mod.get_live_quote("QQQ"),
        }

        result = run_simulation(seed)

        rounds = [
            [_serialize_forecast(f) for f in round_forecasts]
            for round_forecasts in result.rounds
        ]

        return {
            "rounds": rounds,
            "consensus": _serialize_consensus(result.consensus),
            "scenario": scenario,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
