# TODOS

## FastAPI Backend

- **Shared cache between Streamlit and FastAPI**: Replace `@st.cache_data` in `data.py` with a shared `cachetools.TTLCache` so both the Streamlit app (`app.py`) and FastAPI backend share one in-process cache instead of two separate ones. Currently each process maintains its own cache.

- **Auth on `/api/predict`**: Add an `X-API-Key` header check to prevent unauthorized callers from triggering 15 Anthropic API calls (~$0.50/run). Simple: `if request.headers.get("X-API-Key") != os.getenv("PREDICT_API_KEY"): raise HTTPException(401)`.

## Analogues

- **AnaloguesPanel UI upgrade**: Update `AnaloguesPanel` in `frontend/src/App.jsx` to display the richer data now returned by `/api/analogues`:
  - Show `similarity_score` as a colored badge (green ≥ 0.8, yellow ≥ 0.5, gray below)
  - Multi-period return columns: 1d / 5d / 10d / 20d
  - Footer row showing aggregate stats: avg 5d return, win rate, avg max drawdown
  - **Why:** The backend now ships richer match quality data; the UI currently only shows date, event, return_5d. The new fields are unused by the frontend until this is done.
  - **Depends on:** Analogues overhaul (merged) — new API fields required.

- **Weighted similarity scoring**: The current equal-weight scoring (+0.2 per criterion) treats RSI proximity the same as 20d-return proximity. Experiment with weighted criteria after validating the equal-weight baseline:
  - RSI within ±10: 0.30 (most predictive of short-term momentum state)
  - Same SMA200 trend: 0.30 (regime alignment)
  - Same vol regime: 0.20
  - 20d return within ±3%: 0.10
  - Drawdown within ±5%: 0.10
  - **Why:** Equal weighting is simple and defensible as a baseline, but trend + RSI alignment is empirically more predictive of forward 5d returns than recent return similarity.
  - **Depends on:** Real-world analogue results to validate before tuning.
