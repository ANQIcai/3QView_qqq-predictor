"""
tests/test_api.py — FastAPI endpoint tests using TestClient.

Coverage:
  - Each endpoint returns 200 with expected top-level keys
  - /api/analogues uses statistical similarity matching (10y QQQ — mocked)
  - /api/analogues new fields: similarity, return_1d/5d/10d/20d, max_dd
  - /api/analogues aggregate stats: avg_5d, win_rate, avg_max_dd
  - Boundary guard: matches within 20 days of end-of-history are skipped
  - All-zero score fallback: empty AnalogueResult returned gracefully
  - Backward compat: find_analogues() wrapper returns list[Analogue]
  - /api/news handles 0 articles gracefully
  - /api/predict response includes agent_name and round_num in forecasts
  - /api/predict consensus includes conviction_score and regime_label

/api/predict is NOT called in tests (15 Anthropic API calls = slow + costly).
It is mocked to verify serialization only.
"""

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


# ── /api/calendar ─────────────────────────────────────────────────────────────

def test_calendar_returns_200_and_events():
    r = client.get("/api/calendar")
    assert r.status_code == 200
    data = r.json()
    assert "events" in data
    assert isinstance(data["events"], list)


def test_calendar_events_have_date_field():
    r = client.get("/api/calendar")
    events = r.json()["events"]
    if events:
        assert "date" in events[0]


# ── /api/consensus ────────────────────────────────────────────────────────────

def test_consensus_returns_200_and_holdings():
    r = client.get("/api/consensus")
    assert r.status_code == 200
    assert "holdings" in r.json()
    assert isinstance(r.json()["holdings"], list)


# ── /api/analogues ────────────────────────────────────────────────────────────

def test_analogues_returns_200_and_list():
    r = client.get("/api/analogues")
    assert r.status_code == 200
    data = r.json()
    assert "analogues" in data
    assert isinstance(data["analogues"], list)


def test_analogues_have_new_fields():
    """New endpoint returns similarity, multi-period returns, max_dd. No regime per analogue."""
    r = client.get("/api/analogues")
    assert r.status_code == 200
    analogues = r.json()["analogues"]
    if analogues:
        a = analogues[0]
        assert "date" in a
        assert "event" in a
        assert "similarity" in a
        assert "return_1d" in a
        assert "return_5d" in a
        assert "return_10d" in a
        assert "return_20d" in a
        assert "max_dd" in a
        # regime is no longer per-analogue (it's in the Analogue object but not serialized)
        assert "keyword_score" not in a


def test_analogues_have_aggregate_stats():
    """Top-level response includes aggregate stats."""
    r = client.get("/api/analogues")
    data = r.json()
    assert "avg_5d" in data
    assert "win_rate" in data
    assert "avg_max_dd" in data


def test_analogues_not_empty():
    """Statistical matching against 10y history should always find matches."""
    r = client.get("/api/analogues")
    assert r.status_code == 200
    analogues = r.json()["analogues"]
    assert len(analogues) > 0, "No analogues returned — check _get_qqq_history() and scoring."


# ── analogues unit tests (boundary, edge cases, backward compat) ──────────────

import numpy as np

def _make_history_df(n_rows: int, seed: int = 42) -> "pd.DataFrame":
    """Build a synthetic QQQ-like OHLCV DataFrame for unit tests."""
    import pandas as pd
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_rows)
    close = 300 + np.cumsum(rng.normal(0, 2, n_rows))
    close = np.maximum(close, 1.0)
    df = pd.DataFrame({
        "Open": close * 0.999,
        "High": close * 1.005,
        "Low": close * 0.995,
        "Close": close,
        "Volume": rng.integers(50_000_000, 100_000_000, n_rows).astype(float),
    }, index=dates)
    return df


@patch("analogues._get_qqq_history")
def test_boundary_skip_excludes_near_end_matches(mock_hist):
    """Matches within 20 rows of the end of history must be skipped (no IndexError)."""
    import pandas as pd
    from analogues import find_analogues_full

    history = _make_history_df(300)
    mock_hist.return_value = history

    # Use last 60 rows as "today's" df — conditions should match the end of history
    df_today = history.tail(60).copy()
    result = find_analogues_full(df_today, "", "low_vol_uptrend", n=6)

    # All selected analogues must have idx + 20 < len(history) — validated by no IndexError
    # and all dates must be at least 20 trading days before the last row
    last_date = history.index[-1]
    for a in result.analogues:
        match_date = pd.Timestamp(a.date)
        gap_days = (last_date - match_date).days
        assert gap_days >= 20, f"Analogue {a.date} too close to end of history ({gap_days} days)"


@patch("analogues._get_qqq_history")
def test_empty_history_returns_empty_result(mock_hist):
    """History shorter than 252 rows returns empty AnalogueResult gracefully."""
    from analogues import find_analogues_full, AnalogueResult

    mock_hist.return_value = _make_history_df(100)
    df_today = _make_history_df(60)
    result = find_analogues_full(df_today, "", "low_vol_uptrend", n=6)

    assert isinstance(result, AnalogueResult)
    assert result.analogues == []
    assert result.win_rate == 0.0
    assert result.avg_5d_return == 0.0


@patch("analogues._get_qqq_history")
def test_find_analogues_backward_compat_returns_list(mock_hist):
    """find_analogues() wrapper must return list[Analogue] for agents.py compatibility."""
    from analogues import find_analogues, Analogue

    mock_hist.return_value = _make_history_df(600)
    df_today = _make_history_df(252)
    results = find_analogues(df_today, "test scenario", "low_vol_uptrend", n=3)

    assert isinstance(results, list)
    for a in results:
        assert isinstance(a, Analogue)
        assert hasattr(a, "date")
        assert hasattr(a, "event_label")
        assert hasattr(a, "return_5d")
        assert hasattr(a, "regime")
        assert hasattr(a, "similarity_score")


@patch("analogues._get_qqq_history")
def test_anti_clustering_results_are_20_days_apart(mock_hist):
    """Returned analogues must each be >= 20 trading days apart."""
    import pandas as pd
    from analogues import find_analogues_full

    mock_hist.return_value = _make_history_df(1000)
    df_today = _make_history_df(252)
    result = find_analogues_full(df_today, "", "low_vol_uptrend", n=6)

    dates = sorted(pd.Timestamp(a.date) for a in result.analogues)
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days
        assert gap >= 20, f"Analogues {dates[i-1]} and {dates[i]} are only {gap} days apart"


@patch("analogues._get_qqq_history")
def test_analogue_result_stats_are_consistent(mock_hist):
    """avg_5d_return and win_rate must match the individual analogue values."""
    from analogues import find_analogues_full

    mock_hist.return_value = _make_history_df(1000)
    df_today = _make_history_df(252)
    result = find_analogues_full(df_today, "", "low_vol_uptrend", n=4)

    if result.analogues:
        expected_avg = round(sum(a.return_5d for a in result.analogues) / len(result.analogues), 2)
        assert abs(result.avg_5d_return - expected_avg) < 0.01

        expected_wr = round(
            sum(1 for a in result.analogues if a.return_5d > 0) / len(result.analogues) * 100, 1
        )
        assert abs(result.win_rate - expected_wr) < 0.1


# ── /api/news ─────────────────────────────────────────────────────────────────

@patch("api.news_mod.fetch_all_news", return_value=[])
def test_news_empty_articles_returns_empty_digest(mock_news):
    r = client.get("/api/news")
    assert r.status_code == 200
    data = r.json()
    assert data["articles"] == []
    assert data["digest"] == {}


def test_news_returns_200_and_expected_keys():
    r = client.get("/api/news")
    assert r.status_code == 200
    data = r.json()
    assert "articles" in data
    assert "digest" in data


def test_news_articles_have_required_fields():
    r = client.get("/api/news")
    articles = r.json()["articles"]
    if articles:
        a = articles[0]
        for field in ("title", "source", "sentiment", "url", "published"):
            assert field in a, f"Missing field: {field}"


# ── /api/market ───────────────────────────────────────────────────────────────

def test_market_returns_200_and_expected_keys():
    r = client.get("/api/market")
    assert r.status_code == 200
    data = r.json()
    for key in ("ticker", "current_price", "ohlcv", "indicators", "macro", "regime"):
        assert key in data, f"Missing key: {key}"


def test_market_ohlcv_entries_have_date_string():
    r = client.get("/api/market")
    ohlcv = r.json()["ohlcv"]
    assert len(ohlcv) > 0
    # date must be YYYY-MM-DD string, not a timestamp integer
    first = ohlcv[0]
    assert "date" in first
    assert isinstance(first["date"], str)
    assert len(first["date"]) == 10  # YYYY-MM-DD


def test_market_has_close_price():
    r = client.get("/api/market")
    assert r.json()["current_price"] > 0


# ── /api/predict (mocked — not calling Anthropic) ─────────────────────────────

def _make_forecast(agent_name, round_num, direction="bullish"):
    f = MagicMock()
    f.agent_name = agent_name
    f.round_num = round_num
    f.direction = direction
    f.confidence = 0.75
    f.target_low = 470.0
    f.target_high = 490.0
    f.reasoning = "Test reasoning."
    f.status = "ok"
    f.revised_from = None
    return f


def _make_consensus():
    c = MagicMock()
    c.consensus_target = 480.0
    c.bull_prob = 0.6
    c.base_prob = 0.3
    c.bear_prob = 0.1
    c.bull_target = 495.0
    c.base_target = 480.0
    c.bear_target = 460.0
    c.agent_count = 5
    c.avg_confidence = 0.72
    c.disagreement = False
    c.disagreement_detail = ""
    c.credible_low = 465.0
    c.credible_high = 498.0
    c.method = "institutional"
    c.conviction_score = 68
    c.regime_label = "trending_up"
    c.upweighted_agents = ["Momentum Analyst"]
    c.entropy_label = "MODERATE"
    return c


@patch("api.run_simulation")
@patch("api.news_mod.build_scenario_from_news", return_value="Test scenario.")
@patch("api.news_mod.generate_market_digest", return_value={"key_risk": "None"})
@patch("api.news_mod.fetch_all_news", return_value=[])
def test_predict_returns_rounds_and_consensus(mock_news, mock_digest, mock_scenario, mock_sim):
    agents = ["Macro Strategist", "Momentum Analyst", "Sentiment Analyst",
              "Quant Modeler", "Earnings Analyst"]
    mock_result = MagicMock()
    mock_result.rounds = [
        [_make_forecast(a, i + 1) for a in agents]
        for i in range(3)
    ]
    mock_result.consensus = _make_consensus()
    mock_sim.return_value = mock_result

    r = client.post("/api/predict")
    assert r.status_code == 200
    data = r.json()
    assert "rounds" in data
    assert "consensus" in data
    assert len(data["rounds"]) == 3


@patch("api.run_simulation")
@patch("api.news_mod.build_scenario_from_news", return_value="Test scenario.")
@patch("api.news_mod.generate_market_digest", return_value={})
@patch("api.news_mod.fetch_all_news", return_value=[])
def test_predict_forecasts_have_agent_name(mock_news, mock_digest, mock_scenario, mock_sim):
    agents = ["Macro Strategist", "Momentum Analyst", "Sentiment Analyst",
              "Quant Modeler", "Earnings Analyst"]
    mock_result = MagicMock()
    mock_result.rounds = [
        [_make_forecast(a, i + 1) for a in agents]
        for i in range(3)
    ]
    mock_result.consensus = _make_consensus()
    mock_sim.return_value = mock_result

    r = client.post("/api/predict")
    round1 = r.json()["rounds"][0]
    assert len(round1) == 5
    names = {f["agent_name"] for f in round1}
    assert "Macro Strategist" in names
    # round_num must be present
    assert all("round_num" in f for f in round1)


@patch("api.run_simulation")
@patch("api.news_mod.build_scenario_from_news", return_value="Test scenario.")
@patch("api.news_mod.generate_market_digest", return_value={})
@patch("api.news_mod.fetch_all_news", return_value=[])
def test_predict_consensus_has_conviction_score(mock_news, mock_digest, mock_scenario, mock_sim):
    agents = ["Macro Strategist", "Momentum Analyst", "Sentiment Analyst",
              "Quant Modeler", "Earnings Analyst"]
    mock_result = MagicMock()
    mock_result.rounds = [[_make_forecast(a, 1) for a in agents] for _ in range(3)]
    mock_result.consensus = _make_consensus()
    mock_sim.return_value = mock_result

    r = client.post("/api/predict")
    consensus = r.json()["consensus"]
    assert "conviction_score" in consensus
    assert "regime_label" in consensus
    assert "disagreement" in consensus
    assert "credible_low" in consensus
    assert "entropy_label" in consensus
