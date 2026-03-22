# 3QView — Multi-Agent AI QQQ Predictor

React + FastAPI. Five Claude-powered analyst agents debate QQQ's 5-day direction across 3 rounds.

## Stack

| Layer | Tech |
|-------|------|
| Frontend | React 18 + Vite + Recharts + Lucide |
| Backend API | FastAPI + Uvicorn |
| AI Agents | Anthropic Claude (5 personas, 3 rounds) |
| Market Data | yfinance, Finnhub |
| News | AlphaVantage, Finnhub |

## Setup

```bash
# 1. Clone
git clone https://github.com/ANQIcai/Oracle3Q_qqq-predictor.git
cd Oracle3Q_qqq-predictor  # repo name unchanged

# 2. Python deps
pip install -r requirements.txt
pip install fastapi uvicorn httpx

# 3. Env vars
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY and FINNHUB_API_KEY

# 4. Start FastAPI backend
uvicorn api:app --host 0.0.0.0 --port 8000

# 5. Start React frontend (new terminal)
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/market` | OHLCV, indicators, macro, regime |
| GET | `/api/news` | Articles + AI digest |
| GET | `/api/calendar` | Earnings, FOMC, economic releases, OpEx |
| GET | `/api/consensus` | Analyst buy/hold/sell for top holdings |
| GET | `/api/analogues` | Historical analogues (5-year dataset) |
| POST | `/api/predict` | Full 3-round, 5-agent simulation (~90s) |

## Architecture

```
React (localhost:5173)
    │  HTTP via Vite proxy
    ▼
FastAPI (localhost:8000)
    ├── data.py ──── yfinance OHLCV + macro
    ├── indicators.py ── RSI, MACD, BB, SMA
    ├── analogues.py ── historical pattern match
    ├── news.py ──── AlphaVantage + Finnhub news
    ├── live_data.py ── calendar, consensus, quote
    └── agents.py ── 5 Claude agents × 3 rounds
                         ↓
                    Anthropic API
```

## Notes

- `/api/predict` takes 60–120 seconds (15 Claude API calls). The React frontend uses a 3-minute AbortController timeout.
- Both the Streamlit app (`app.py`) and FastAPI backend can run simultaneously — each uses its own in-process cache.
