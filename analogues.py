import pandas as pd
from dataclasses import dataclass
from typing import Optional

KEYWORD_VOCAB = {
    "fed", "fomc", "cut", "hike", "rate", "rates", "bps",
    "tariff", "tariffs", "trade", "earnings", "inflation",
    "cpi", "emergency", "recession", "gdp", "unemployment",
    "payroll", "jobs", "dovish", "hawkish", "pivot",
}

# Pre-tagged historical event library
HISTORICAL_EVENTS = [
    {"date": "2019-07-31", "label": "fed cut 25bps fomc rate dovish"},
    {"date": "2019-09-18", "label": "fed cut 25bps fomc rate"},
    {"date": "2019-10-30", "label": "fed cut 25bps fomc rate dovish"},
    {"date": "2020-03-03", "label": "fed emergency cut 50bps rate fomc"},
    {"date": "2020-03-15", "label": "fed emergency cut 100bps rate fomc"},
    {"date": "2022-03-16", "label": "fed hike rate 25bps fomc hawkish inflation"},
    {"date": "2022-05-04", "label": "fed hike rate 50bps fomc hawkish inflation"},
    {"date": "2022-06-15", "label": "fed hike rate 75bps fomc hawkish inflation"},
    {"date": "2022-11-02", "label": "fed hike rate 75bps fomc"},
    {"date": "2023-02-01", "label": "fed hike rate 25bps fomc pivot"},
    {"date": "2024-09-18", "label": "fed cut 50bps fomc rate dovish pivot"},
    {"date": "2024-11-07", "label": "fed cut 25bps fomc rate dovish"},
    {"date": "2024-12-18", "label": "fed cut 25bps fomc rate"},
    {"date": "2018-12-19", "label": "fed hike rate 25bps fomc hawkish"},
    {"date": "2021-11-03", "label": "fed tapering rate hawkish inflation"},
    {"date": "2020-03-20", "label": "covid emergency recession gdp"},
    {"date": "2025-04-02", "label": "tariff tariffs trade"},
]


@dataclass
class Analogue:
    date: str
    event_label: str
    regime: str
    return_5d: float
    keyword_score: int


def _extract_keywords(text: str) -> set:
    return {t.lower() for t in text.split()} & KEYWORD_VOCAB


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


def find_analogues(
    df: pd.DataFrame, scenario: str, current_regime: str, n: int = 3
) -> list[Analogue]:
    scenario_keywords = _extract_keywords(scenario)
    results: list[Analogue] = []

    for event in HISTORICAL_EVENTS:
        event_date = pd.Timestamp(event["date"])
        available = df.index[df.index >= event_date]
        if len(available) == 0:
            continue
        closest = available[0]
        idx = df.index.get_loc(closest)
        if idx + 5 >= len(df):
            continue

        window_df = df.iloc[max(0, idx - 30) : idx]
        if len(window_df) < 5:
            continue

        price_at = float(df["Close"].iloc[idx])
        price_5d = float(df["Close"].iloc[idx + 5])
        return_5d = (price_5d - price_at) / price_at * 100

        event_keywords = _extract_keywords(event["label"])
        keyword_score = len(scenario_keywords & event_keywords)

        results.append(
            Analogue(
                date=closest.strftime("%Y-%m-%d"),
                event_label=event["label"],
                regime=_classify_window_regime(window_df),
                return_5d=round(float(return_5d), 2),
                keyword_score=keyword_score,
            )
        )

    # Sort: keyword score first, then regime match
    results.sort(
        key=lambda a: (a.keyword_score, 1 if a.regime == current_regime else 0),
        reverse=True,
    )

    top = results[:n]

    # Fallback: pad with regime-only matches if not enough keyword hits
    if len([r for r in top if r.keyword_score > 0]) < n:
        extras = [r for r in results if r not in top and r.regime == current_regime]
        top = (top + extras)[:n]

    return top
