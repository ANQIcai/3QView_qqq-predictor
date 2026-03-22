import yfinance as yf
import pandas as pd
import streamlit as st
from concurrent.futures import ThreadPoolExecutor

MACRO_TICKERS = {
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "yield_10y": "^TNX",
}

FRED_FALLBACK = 5.25  # last known Fed Funds Rate


class DataFetchError(Exception):
    pass


@st.cache_data(ttl=3600)
def fetch_ohlcv_5y(ticker: str = "QQQ") -> pd.DataFrame:
    """5-year OHLCV for historical analogues (cached 1h — rarely changes)."""
    df = yf.download(ticker, period="5y", auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise DataFetchError(f"No data returned for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    return df


@st.cache_data(ttl=300)
def fetch_ohlcv(ticker: str = "QQQ", period: str = "2y") -> pd.DataFrame:
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise DataFetchError(f"No data returned for {ticker}")
    # Flatten multi-level columns if present (yfinance sometimes returns them)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    return df


@st.cache_data(ttl=300)
def fetch_macro_context() -> dict:
    result = {}
    for key, ticker in MACRO_TICKERS.items():
        try:
            data = yf.download(ticker, period="5d", auto_adjust=True, progress=False)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            if not data.empty:
                last = data["Close"].dropna().iloc[-1]
                result[key] = round(float(last), 2)
            else:
                result[key] = None
        except Exception:
            result[key] = None

    result["fed_rate"] = _fetch_fed_rate()
    return result


def _fetch_fed_rate() -> float:
    def _fetch():
        import pandas_datareader.data as web
        df = web.DataReader("FEDFUNDS", "fred")
        return float(df.iloc[-1, 0])

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_fetch)
            return future.result(timeout=5)
    except Exception:
        return FRED_FALLBACK


def get_current_price(df: pd.DataFrame) -> float:
    return round(float(df["Close"].iloc[-1]), 2)
