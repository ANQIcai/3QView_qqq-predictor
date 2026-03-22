"""
tests/test_api.py — FastAPI endpoint tests using TestClient.

Coverage:
  - Each endpoint returns 200 with expected top-level keys
  - /api/analogues uses 5y OHLCV (would return empty list with 1y df)
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


def test_analogues_uses_5y_data_not_empty():
    """Analogues should not be empty — they would be with a 1y df since
    HISTORICAL_EVENTS go back to 2018 and most events fall before 1y window."""
    r = client.get("/api/analogues")
    assert r.status_code == 200
    analogues = r.json()["analogues"]
    assert len(analogues) > 0, (
        "No analogues returned. /api/analogues may be using 1y df instead of 5y."
    )


def test_analogues_have_required_fields():
    r = client.get("/api/analogues")
    analogues = r.json()["analogues"]
    if analogues:
        a = analogues[0]
        assert "date" in a
        assert "event" in a
        assert "return_5d" in a
        assert "regime" in a


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
