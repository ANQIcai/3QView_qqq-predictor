import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import yfinance as yf

HISTORY_PATH = Path.home() / ".qqq-sim" / "history.json"


def _ensure_dir() -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_history() -> list:
    _ensure_dir()
    if not HISTORY_PATH.exists():
        return []
    with open(HISTORY_PATH) as f:
        return json.load(f)


def save_prediction(seed: dict, simulation_result) -> None:
    _ensure_dir()
    history = load_history()
    c = simulation_result.consensus
    # Capture each agent's Round 3 direction for per-agent track record scoring
    agent_forecasts = {}
    for f in simulation_result.rounds[2]:
        if getattr(f, "status", "ok") == "ok":
            agent_forecasts[f.agent_name] = {
                "direction": f.direction,
                "target_mid": round((f.target_low + f.target_high) / 2, 2),
            }
    entry = {
        "id": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "ticker": seed["ticker"],
        "scenario": seed["scenario"],
        "current_price": seed.get("current_price"),
        "consensus_target": c.consensus_target,
        "bull_prob": c.bull_prob,
        "bear_prob": c.bear_prob,
        "agent_count": c.agent_count,
        "agent_forecasts": agent_forecasts,
        "scored": False,
        "actual_price_5d": None,
        "correct": None,
        "agent_correct": {},
    }
    history.append(entry)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def score_past_predictions() -> int:
    """Fetch actuals and score predictions that are 5+ trading days old."""
    history = load_history()
    scored = 0
    for entry in history:
        if entry.get("scored"):
            continue
        pred_date = pd.Timestamp(entry["date"])
        target_date = pred_date + pd.tseries.offsets.BDay(5)
        if target_date > pd.Timestamp.now():
            continue
        try:
            end = target_date + pd.tseries.offsets.BDay(1)
            df = yf.download(
                entry["ticker"],
                start=target_date.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
            )
            if df.empty:
                continue
            actual = float(df["Close"].iloc[0])
            current = entry.get("current_price") or 0
            target = entry["consensus_target"]
            entry["actual_price_5d"] = round(actual, 2)
            entry["correct"] = (actual > current) if (target > current) else (actual < current)
            # Per-agent scoring
            agent_correct = {}
            for agent, forecast in entry.get("agent_forecasts", {}).items():
                direction = forecast.get("direction")
                if direction == "bullish":
                    agent_correct[agent] = actual > current
                elif direction == "bearish":
                    agent_correct[agent] = actual < current
                else:  # neutral
                    agent_correct[agent] = (abs(actual - current) / current < 0.01) if current else False
            entry["agent_correct"] = agent_correct
            entry["scored"] = True
            scored += 1
        except Exception:
            continue
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)
    return scored


def get_scorecard() -> dict:
    scored = [h for h in load_history() if h.get("scored")]
    if not scored:
        return {"total": 0, "correct": 0, "wrong": 0, "accuracy": 0.0}
    correct = sum(1 for h in scored if h.get("correct"))
    return {
        "total": len(scored),
        "correct": correct,
        "wrong": len(scored) - correct,
        "accuracy": round(correct / len(scored) * 100, 1),
    }


def get_agent_track_records() -> dict:
    """Return per-agent accuracy ratio. Defaults to 0.5 (equal weight) when no data."""
    _ALL_AGENTS = [
        "Macro Strategist", "Momentum Analyst", "Sentiment Analyst",
        "Quant Modeler", "Earnings Analyst",
    ]
    history = load_history()
    totals: dict[str, int] = {}
    corrects: dict[str, int] = {}
    for entry in history:
        for agent, is_correct in entry.get("agent_correct", {}).items():
            totals[agent] = totals.get(agent, 0) + 1
            if is_correct:
                corrects[agent] = corrects.get(agent, 0) + 1
    return {
        agent: (corrects.get(agent, 0) / totals[agent]) if totals.get(agent, 0) > 0 else 0.5
        for agent in _ALL_AGENTS
    }


def seed_demo_history(ticker: str = "QQQ") -> None:
    """Pre-seed history.json with fabricated past predictions for demo purposes."""
    _ensure_dir()
    if HISTORY_PATH.exists():
        return
    demo = [
        {"date": "2025-03-01", "scenario": "Fed holds rates steady", "current_price": 468.20, "consensus_target": 475.00, "correct": True, "actual_price_5d": 476.40},
        {"date": "2025-02-20", "scenario": "Strong jobs report beats expectations", "current_price": 472.50, "consensus_target": 479.00, "correct": True, "actual_price_5d": 480.10},
        {"date": "2025-02-10", "scenario": "CPI comes in hotter than expected", "current_price": 480.30, "consensus_target": 471.00, "correct": True, "actual_price_5d": 469.80},
        {"date": "2025-01-28", "scenario": "Fed cuts 25bps, dovish language", "current_price": 461.10, "consensus_target": 470.00, "correct": True, "actual_price_5d": 471.50},
        {"date": "2025-01-15", "scenario": "Tech earnings miss broadly", "current_price": 455.80, "consensus_target": 447.00, "correct": False, "actual_price_5d": 459.20},
        {"date": "2025-01-05", "scenario": "Tariff announcement on China goods", "current_price": 459.40, "consensus_target": 451.00, "correct": True, "actual_price_5d": 450.10},
        {"date": "2024-12-20", "scenario": "Fed signals slower pace of cuts", "current_price": 488.20, "consensus_target": 478.00, "correct": True, "actual_price_5d": 476.30},
    ]
    history = []
    for d in demo:
        history.append({
            "id": f"demo-{d['date']}",
            "date": d["date"],
            "ticker": ticker,
            "scenario": d["scenario"],
            "current_price": d["current_price"],
            "consensus_target": d["consensus_target"],
            "bull_prob": 0.55,
            "bear_prob": 0.25,
            "agent_count": 5,
            "scored": True,
            "actual_price_5d": d["actual_price_5d"],
            "correct": d["correct"],
        })
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)
