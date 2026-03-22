import pandas as pd
from typing import Optional


def calc_rsi(series: pd.Series, period: int = 14) -> Optional[float]:
    series = series.dropna()
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if pd.notna(val) else None


def calc_macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    series = series.dropna()
    if len(series) < slow + signal:
        return None, None, None
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return (
        round(float(macd.iloc[-1]), 4),
        round(float(signal_line.iloc[-1]), 4),
        round(float(histogram.iloc[-1]), 4),
    )


def calc_bollinger(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[Optional[float], Optional[float], Optional[float], str]:
    series = series.dropna()
    if len(series) < period:
        return None, None, None, "mid"
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    last_close = float(series.iloc[-1])
    last_upper = float(upper.iloc[-1])
    last_lower = float(lower.iloc[-1])
    last_mid = float(sma.iloc[-1])
    if last_close >= last_upper * 0.98:
        position = "upper"
    elif last_close <= last_lower * 1.02:
        position = "lower"
    else:
        position = "mid"
    return round(last_upper, 2), round(last_mid, 2), round(last_lower, 2), position


def calc_sma(series: pd.Series, window: int) -> Optional[float]:
    series = series.dropna()
    if len(series) < window:
        return None
    val = series.rolling(window).mean().iloc[-1]
    return round(float(val), 2) if pd.notna(val) else None


def calc_summary_stats(df: pd.DataFrame) -> dict:
    close = df["Close"].dropna()
    returns = close.pct_change().dropna()
    cumulative = (1 + returns).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    return {
        "mean_daily_return_pct": round(float(returns.mean()) * 100, 4),
        "annual_vol_pct": round(float(returns.std()) * (252**0.5) * 100, 2),
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
        "total_days": len(close),
    }


def calc_ema(series: pd.Series, span: int) -> Optional[float]:
    series = series.dropna()
    if len(series) < span:
        return None
    val = series.ewm(span=span, adjust=False).mean().iloc[-1]
    return round(float(val), 2) if pd.notna(val) else None


def calc_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Average True Range over `period` bars."""
    high = df["High"].squeeze().dropna()
    low = df["Low"].squeeze().dropna()
    close = df["Close"].squeeze().dropna()
    if len(close) < period + 1:
        return None
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(com=period - 1, min_periods=period).mean()
    val = atr.iloc[-1]
    return round(float(val), 2) if pd.notna(val) else None


def compute_all(df: pd.DataFrame) -> dict:
    close = df["Close"].squeeze()
    macd_val, signal_val, hist_val = calc_macd(close)
    _, _, _, bb_pos = calc_bollinger(close)
    return {
        "rsi": calc_rsi(close),
        "macd": macd_val,
        "macd_signal": signal_val,
        "macd_hist": hist_val,
        "bb_position": bb_pos,
        "sma_20": calc_sma(close, 20),
        "sma_50": calc_sma(close, 50),
        "sma_200": calc_sma(close, 200),
        "ema_9": calc_ema(close, 9),
        "atr": calc_atr(df),
        "summary_stats": calc_summary_stats(df),
    }
