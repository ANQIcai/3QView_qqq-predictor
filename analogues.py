"""
analogues.py — Historical analogue matching for QQQ.

Data flow:
  _get_qqq_history()
      │  yf.download("QQQ", period="10y")  [module-level cache, 1hr TTL]
      ▼
  find_analogues_full(df, scenario, current_regime, n=6)
      │
      ├── Compute "today" features from df tail:
      │     RSI(14), 20d realized vol, price vs SMA200,
      │     20d return, drawdown from 52-week high
      │
      ├── Compute vectorized feature series over all 10y history
      │     (one-pass EWM RSI — NOT per-row, avoids O(n²))
      │
      ├── Score similarity 0.0–1.0 (+0.2 per matched criterion):
      │     RSI within ±10 | same vol regime | same SMA200 trend
      │     20d return within ±3% | drawdown within ±5%
      │
      ├── Sort descending → greedy anti-cluster (20 trading day gap)
      │
      ├── BOUNDARY GUARD: skip idx + 20 >= len(history)
      │     (prevents IndexError for recent matches)
      │
      ├── Compute forward returns (1d, 5d, 10d, 20d) + max drawdown
      │
      └── Apply MAJOR_EVENTS label (±5 calendar days ≈ ±3 trading days)
            or auto-generate: "High vol downtrend · RSI 31"

Backward compatibility:
  find_analogues(df, scenario, current_regime, n=6) -> list[Analogue]
      wraps find_analogues_full() for agents.py and /api/predict
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf

# ── Module-level 10y QQQ cache ─────────────────────────────────────────────────

_QQQ_HISTORY_CACHE: Optional[pd.DataFrame] = None
_QQQ_HISTORY_TIME: Optional[datetime] = None


def _get_qqq_history() -> pd.DataFrame:
    """Download 10y QQQ OHLCV and cache for 1 hour. Raises RuntimeError on failure."""
    global _QQQ_HISTORY_CACHE, _QQQ_HISTORY_TIME
    if (
        _QQQ_HISTORY_CACHE is not None
        and _QQQ_HISTORY_TIME is not None
        and (datetime.now() - _QQQ_HISTORY_TIME).seconds < 3600
    ):
        return _QQQ_HISTORY_CACHE

    logging.info("analogues: downloading 10y QQQ history (cold cache)…")
    try:
        df = yf.download("QQQ", period="10y", auto_adjust=True, progress=False)
    except Exception as exc:
        raise RuntimeError(f"Failed to download QQQ 10y history: {exc}") from exc

    if df is None or df.empty:
        raise RuntimeError("yfinance returned empty data for QQQ 10y history")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()
    _QQQ_HISTORY_CACHE = df
    _QQQ_HISTORY_TIME = datetime.now()
    return df


# ── Curated event labels ────────────────────────────────────────────────────────

MAJOR_EVENTS: dict[str, str] = {
    "2020-02-24": "COVID selloff begins",
    "2020-03-16": "COVID crash — Fed emergency 0%",
    "2020-03-23": "COVID bottom — unlimited QE",
    "2022-01-04": "2022 tech selloff — hawkish pivot",
    "2022-06-16": "Bear market — 75bps hike",
    "2022-10-13": "CPI surprise — intraday reversal",
    "2022-12-28": "2022 bear market low",
    "2023-03-13": "SVB collapse",
    "2023-10-27": "Q3 2023 correction bottom",
    "2024-07-11": "AI rotation — Mag7 selloff",
    "2024-08-05": "Yen carry trade unwind",
    "2024-12-18": "Fed hawkish cut — dot plot shock",
    "2025-02-19": "DeepSeek AI scare",
    "2025-04-02": "Liberation Day tariffs",
    "2025-04-07": "Tariff escalation",
    "2025-04-09": "90-day tariff pause — rally",
}

_MAJOR_EVENT_TIMESTAMPS = {pd.Timestamp(k): v for k, v in MAJOR_EVENTS.items()}


# ── Dataclasses ─────────────────────────────────────────────────────────────────

@dataclass
class Analogue:
    date: str
    event_label: str
    similarity_score: float   # 0.0–1.0
    return_1d: float
    return_5d: float
    return_10d: float
    return_20d: float
    max_drawdown_20d: float
    regime: str
    rsi_at_time: float


@dataclass
class AnalogueResult:
    analogues: list            # list[Analogue]
    avg_5d_return: float
    win_rate: float            # percentage of analogues with return_5d > 0
    avg_max_drawdown: float


# ── Regime detection (unchanged) ───────────────────────────────────────────────

def detect_regime(df: pd.DataFrame, vix: Optional[float] = None) -> str:
    close = df["Close"].dropna()
    sma_200 = (
        float(close.rolling(200).mean().iloc[-1])
        if len(close) >= 200
        else float(close.mean())
    )
    above_sma = float(close.iloc[-1]) > sma_200

    if vix is not None:
        high_vol = vix > 20
    else:
        std = float(close.pct_change().dropna().std())
        high_vol = std > 0.012

    if high_vol and above_sma:
        return "high_vol_uptrend"
    elif high_vol and not above_sma:
        return "high_vol_downtrend"
    elif not high_vol and above_sma:
        return "low_vol_uptrend"
    else:
        return "low_vol_ranging"


def _classify_window_regime(window_df: pd.DataFrame) -> str:
    close = window_df["Close"].dropna()
    if len(close) < 10:
        return "unknown"
    above_sma = float(close.iloc[-1]) > float(close.mean())
    high_vol = float(close.pct_change().std()) > 0.012
    if high_vol and above_sma:
        return "high_vol_uptrend"
    elif high_vol and not above_sma:
        return "high_vol_downtrend"
    elif not high_vol and above_sma:
        return "low_vol_uptrend"
    else:
        return "low_vol_ranging"


# ── Vectorized RSI series ──────────────────────────────────────────────────────

def _compute_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """Return RSI(period) as a Series aligned with close. One-pass EWM, O(n)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


# ── Event label helper ─────────────────────────────────────────────────────────

def _get_event_label(
    ts: pd.Timestamp,
    regime: str,
    rsi: float,
    high_vol: bool,
) -> str:
    """Return MAJOR_EVENTS label if within ±5 calendar days, else auto-generate."""
    for event_ts, label in _MAJOR_EVENT_TIMESTAMPS.items():
        if abs((ts - event_ts).days) <= 5:
            return label
    regime_map = {
        "high_vol_uptrend": "High vol uptrend",
        "high_vol_downtrend": "High vol downtrend",
        "low_vol_uptrend": "Low vol uptrend",
        "low_vol_ranging": "Low vol ranging",
        "unknown": "Unknown regime",
    }
    regime_label = regime_map.get(regime, regime.replace("_", " ").capitalize())
    return f"{regime_label} · RSI {rsi:.0f}"


# ── Core similarity matching ───────────────────────────────────────────────────

def find_analogues_full(
    df: pd.DataFrame,
    scenario: str,
    current_regime: str,
    n: int = 6,
) -> AnalogueResult:
    """
    Find top-n historical analogues to current QQQ conditions.

    Parameters
    ----------
    df              : Recent QQQ OHLCV (1y or 5y) — used to compute today's features.
    scenario        : Unused (kept for API compat; keyword matching replaced by stats).
    current_regime  : Regime string from detect_regime().
    n               : Number of analogues to return (default 6).

    Returns
    -------
    AnalogueResult with analogues list and aggregate stats.
    """
    history = _get_qqq_history()
    close = history["Close"].dropna()

    if len(close) < 252:
        return AnalogueResult(analogues=[], avg_5d_return=0.0, win_rate=0.0, avg_max_drawdown=0.0)

    # ── Today's features from df ──────────────────────────────────────────────
    curr_close = df["Close"].dropna()

    curr_rsi_series = _compute_rsi_series(curr_close)
    curr_rsi = float(curr_rsi_series.iloc[-1]) if pd.notna(curr_rsi_series.iloc[-1]) else 50.0

    curr_vol_series = curr_close.pct_change().rolling(20).std()
    curr_vol = float(curr_vol_series.iloc[-1]) if pd.notna(curr_vol_series.iloc[-1]) else 0.0
    curr_high_vol = curr_vol > 0.012

    sma200 = curr_close.rolling(200).mean()
    curr_above_sma = (
        float(curr_close.iloc[-1]) > float(sma200.iloc[-1])
        if len(curr_close) >= 200 and pd.notna(sma200.iloc[-1])
        else True
    )

    curr_20d_ret = (
        (float(curr_close.iloc[-1]) - float(curr_close.iloc[-21])) / float(curr_close.iloc[-21]) * 100
        if len(curr_close) > 21
        else 0.0
    )

    hi_52wk = curr_close.rolling(min(252, len(curr_close))).max().iloc[-1]
    curr_drawdown = (
        (float(curr_close.iloc[-1]) - float(hi_52wk)) / float(hi_52wk) * 100
        if pd.notna(hi_52wk) and float(hi_52wk) > 0
        else 0.0
    )

    # ── Historical feature series (vectorized, one-pass) ──────────────────────
    hist_rsi = _compute_rsi_series(close)
    hist_vol = close.pct_change().rolling(20).std()
    hist_sma200 = close.rolling(200).mean()
    hist_20d_ret = close.pct_change(20) * 100
    hist_52wk_high = close.rolling(252).max()
    hist_drawdown = (close - hist_52wk_high) / hist_52wk_high * 100

    # ── Score each day ────────────────────────────────────────────────────────
    # Start at 252 so all feature series are fully warmed up.
    scores: list[tuple[int, float]] = []
    for i in range(252, len(close)):
        if i + 20 >= len(close):   # boundary guard — need 20 days of forward data
            continue

        rsi_h = hist_rsi.iloc[i]
        vol_h = hist_vol.iloc[i]
        sma_h = hist_sma200.iloc[i]
        ret20_h = hist_20d_ret.iloc[i]
        dd_h = hist_drawdown.iloc[i]

        if any(pd.isna(v) for v in (rsi_h, vol_h, sma_h, ret20_h, dd_h)):
            continue

        score = 0.0
        if abs(float(rsi_h) - curr_rsi) <= 10:
            score += 0.2
        if (float(vol_h) > 0.012) == curr_high_vol:
            score += 0.2
        if (float(close.iloc[i]) > float(sma_h)) == curr_above_sma:
            score += 0.2
        if abs(float(ret20_h) - curr_20d_ret) <= 3.0:
            score += 0.2
        if abs(float(dd_h) - curr_drawdown) <= 5.0:
            score += 0.2

        scores.append((i, round(score, 2)))

    scores.sort(key=lambda x: x[1], reverse=True)

    # ── Greedy anti-clustering (skip dates within 20 trading days) ────────────
    selected: list[int] = []
    for idx, _ in scores:
        if all(abs(idx - s) >= 20 for s in selected):
            selected.append(idx)
            if len(selected) == n:
                break

    if not selected:
        return AnalogueResult(analogues=[], avg_5d_return=0.0, win_rate=0.0, avg_max_drawdown=0.0)

    # ── Build Analogue objects ────────────────────────────────────────────────
    close_vals = close.values
    dates = close.index
    score_map = {idx: s for idx, s in scores}

    analogues: list[Analogue] = []
    for idx in selected:
        price_at = float(close_vals[idx])

        r1d = (float(close_vals[idx + 1]) - price_at) / price_at * 100
        r5d = (float(close_vals[idx + 5]) - price_at) / price_at * 100
        r10d = (float(close_vals[idx + 10]) - price_at) / price_at * 100
        r20d = (float(close_vals[idx + 20]) - price_at) / price_at * 100
        max_dd = (float(min(close_vals[idx: idx + 21])) - price_at) / price_at * 100

        rsi_val = hist_rsi.iloc[idx]
        rsi_float = round(float(rsi_val), 2) if pd.notna(rsi_val) else 50.0
        high_vol_at = float(hist_vol.iloc[idx]) > 0.012 if pd.notna(hist_vol.iloc[idx]) else False
        window_df = history.iloc[max(0, idx - 30): idx]
        regime = _classify_window_regime(window_df)
        label = _get_event_label(dates[idx], regime, rsi_float, high_vol_at)

        analogues.append(Analogue(
            date=dates[idx].strftime("%Y-%m-%d"),
            event_label=label,
            similarity_score=score_map[idx],
            return_1d=round(r1d, 2),
            return_5d=round(r5d, 2),
            return_10d=round(r10d, 2),
            return_20d=round(r20d, 2),
            max_drawdown_20d=round(max_dd, 2),
            regime=regime,
            rsi_at_time=rsi_float,
        ))

    avg_5d = round(sum(a.return_5d for a in analogues) / len(analogues), 2)
    win_rate = round(sum(1 for a in analogues if a.return_5d > 0) / len(analogues) * 100, 1)
    avg_max_dd = round(sum(a.max_drawdown_20d for a in analogues) / len(analogues), 2)

    return AnalogueResult(
        analogues=analogues,
        avg_5d_return=avg_5d,
        win_rate=win_rate,
        avg_max_drawdown=avg_max_dd,
    )


def find_analogues(
    df: pd.DataFrame,
    scenario: str,
    current_regime: str,
    n: int = 6,
) -> list[Analogue]:
    """Backward-compatible wrapper. Returns list[Analogue] for agents.py and /api/predict."""
    return find_analogues_full(df, scenario, current_regime, n).analogues
