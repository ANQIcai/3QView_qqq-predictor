import math
from dataclasses import dataclass, field
from typing import List

# ── Scenario classification ────────────────────────────────────────────────────

SCENARIO_CATEGORIES: dict[str, list[str]] = {
    "monetary_policy": [
        "fed", "federal reserve", "rate", "bps", "basis point", "hawkish", "dovish",
        "hike", "cut", "fomc", "taper", "qe", "qt", "quantitative", "powell",
        "interest rate", "yield curve", "monetary",
    ],
    "earnings": [
        "earnings", "revenue", "eps", "guidance", "beat", "miss", "profit",
        "margin", "quarterly", "q1", "q2", "q3", "q4", "results", "outlook",
        "sales", "income", "nvda", "msft", "aapl", "amzn", "meta", "googl",
    ],
    "geopolitical": [
        "war", "invasion", "geopolit", "sanction", "conflict", "military",
        "nato", "ukraine", "taiwan", "russia", "nuclear", "election", "coup",
    ],
    "trade": [
        "tariff", "trade", "import", "export", "china", "supply chain",
        "wto", "protectionist", "customs", "duties", "reshoring", "trade war",
    ],
    "macro_shock": [
        "recession", "gdp", "cpi", "inflation", "jobs", "unemployment",
        "pce", "payroll", "ism", "pmi", "housing", "retail", "consumer",
        "nonfarm", "jobs report",
    ],
}

# ── Agent × scenario relevance matrix ─────────────────────────────────────────

AGENT_SCENARIO_WEIGHTS: dict[str, dict[str, float]] = {
    "Macro Strategist": {
        "monetary_policy": 1.5, "earnings": 0.8, "geopolitical": 1.2,
        "trade": 1.2, "macro_shock": 1.3,
    },
    "Momentum Analyst": {
        "monetary_policy": 1.0, "earnings": 1.0, "geopolitical": 1.0,
        "trade": 1.0, "macro_shock": 1.0,
    },
    "Sentiment Analyst": {
        "monetary_policy": 1.1, "earnings": 1.0, "geopolitical": 1.4,
        "trade": 1.2, "macro_shock": 1.2,
    },
    "Quant Modeler": {
        "monetary_policy": 1.0, "earnings": 0.9, "geopolitical": 1.1,
        "trade": 1.0, "macro_shock": 1.1,
    },
    "Earnings Analyst": {
        "monetary_policy": 1.1, "earnings": 1.5, "geopolitical": 0.8,
        "trade": 1.0, "macro_shock": 0.9,
    },
}

# Base price uncertainty for Gaussian models (in dollars)
_BASE_SIGMA = 10.0

# ── Agent correlation matrix (hardcoded; see TODOS for empirical calibration) ─
_AGENT_CORRELATION: dict[tuple, float] = {
    ("Macro Strategist",  "Earnings Analyst"):   0.4,
    ("Earnings Analyst",  "Macro Strategist"):   0.4,
    ("Momentum Analyst",  "Quant Modeler"):      0.6,
    ("Quant Modeler",     "Momentum Analyst"):   0.6,
    ("Sentiment Analyst", "Macro Strategist"):   0.3,
    ("Macro Strategist",  "Sentiment Analyst"):  0.3,
}
_DEFAULT_AGENT_CORR = 0.2  # for any pair not listed above

# ── Regime → per-agent weight multipliers ─────────────────────────────────────
_REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "low_vol_uptrend":    {"Momentum Analyst": 1.3, "Quant Modeler": 1.2},
    "high_vol_uptrend":   {"Macro Strategist": 1.3, "Sentiment Analyst": 1.2},
    "low_vol_ranging":    {"Quant Modeler": 1.2, "Earnings Analyst": 1.2},
    "high_vol_downtrend": {"Macro Strategist": 1.4, "Sentiment Analyst": 1.3},
    "crisis":             {"Macro Strategist": 1.5, "Sentiment Analyst": 1.4},
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Consensus:
    bull_prob: float
    base_prob: float
    bear_prob: float
    consensus_target: float
    bull_target: float
    base_target: float
    bear_target: float
    agent_count: int
    avg_confidence: float
    disagreement: bool
    disagreement_detail: str
    credible_low: float = 0.0
    credible_high: float = 0.0
    method: str = "simple"
    # 5-layer institutional engine outputs
    conviction_score: int = 0
    regime_label: str = ""
    upweighted_agents: List[str] = field(default_factory=list)
    entropy_label: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def classify_scenario(text: str) -> str:
    """Keyword-match scenario text to one of five categories."""
    text_lower = text.lower()
    best_cat, best_count = "macro_shock", 0
    for cat, keywords in SCENARIO_CATEGORIES.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > best_count:
            best_count, best_cat = count, cat
    return best_cat


def _conviction_multipliers(rounds: list) -> dict:
    """
    Compare each agent's direction across Rounds 1 → 2 → 3.
      Held all 3 rounds unchanged : 1.3×
      Flipped direction in R3      : 0.6×
      Changed once then held       : 1.0×
    """
    multipliers = {}
    for f0 in rounds[0]:
        name = f0.agent_name
        if f0.status != "ok":
            multipliers[name] = 1.0
            continue
        d1 = f0.direction
        d2 = next((f.direction for f in rounds[1] if f.agent_name == name and f.status == "ok"), None)
        d3 = next((f.direction for f in rounds[2] if f.agent_name == name and f.status == "ok"), None)
        if d2 is None or d3 is None:
            multipliers[name] = 1.0
        elif d1 == d2 == d3:
            multipliers[name] = 1.3
        elif d2 != d3:
            multipliers[name] = 0.6
        else:
            multipliers[name] = 1.0
    return multipliers


# ── Simple consensus (original, kept as fallback) ─────────────────────────────

def aggregate_forecasts(forecasts) -> Consensus:
    """Confidence-weighted consensus. Used by agents.py and as Bayesian fallback."""
    valid = [f for f in forecasts if getattr(f, "status", "ok") == "ok"]

    if not valid:
        return Consensus(
            bull_prob=0.0, base_prob=0.0, bear_prob=1.0,
            consensus_target=0.0,
            bull_target=0.0, base_target=0.0, bear_target=0.0,
            agent_count=0, avg_confidence=0.0,
            disagreement=False, disagreement_detail="No valid forecasts",
        )

    total_conf = sum(f.confidence for f in valid)
    bull_conf = sum(f.confidence for f in valid if f.direction == "bullish")
    bear_conf = sum(f.confidence for f in valid if f.direction == "bearish")
    base_conf = sum(f.confidence for f in valid if f.direction == "neutral")

    bull_prob = bull_conf / total_conf if total_conf > 0 else 0.0
    bear_prob = bear_conf / total_conf if total_conf > 0 else 0.0
    base_prob = base_conf / total_conf if total_conf > 0 else 0.0

    midpoints = [(f.target_low + f.target_high) / 2 for f in valid]
    consensus_target = sum(m * f.confidence for m, f in zip(midpoints, valid)) / total_conf

    sorted_highs = sorted([f.target_high for f in valid], reverse=True)
    sorted_lows = sorted([f.target_low for f in valid])
    bull_target = sum(sorted_highs[:2]) / 2
    bear_target = sum(sorted_lows[:2]) / 2

    bullish_hc = [f for f in valid if f.direction == "bullish" and f.confidence > 0.65]
    bearish_hc = [f for f in valid if f.direction == "bearish" and f.confidence > 0.65]
    disagreement = len(bullish_hc) > 0 and len(bearish_hc) > 0
    if disagreement:
        detail = (
            ", ".join(f.agent_name for f in bullish_hc) + " (bullish) vs "
            + ", ".join(f.agent_name for f in bearish_hc) + " (bearish)"
        )
    else:
        detail = ""

    return Consensus(
        bull_prob=round(bull_prob, 3),
        base_prob=round(base_prob, 3),
        bear_prob=round(bear_prob, 3),
        consensus_target=round(consensus_target, 2),
        bull_target=round(bull_target, 2),
        base_target=round(consensus_target, 2),
        bear_target=round(bear_target, 2),
        agent_count=len(valid),
        avg_confidence=round(total_conf / len(valid), 3),
        disagreement=disagreement,
        disagreement_detail=detail,
    )


# ── Bayesian ensemble consensus ───────────────────────────────────────────────

def aggregate_forecasts_bayesian(rounds: list, scenario_text: str) -> Consensus:
    """
    Four-layer Bayesian ensemble:

    1. Track record weighting  — per-agent historical accuracy from history.json.
                                  Defaults to 0.5 (equal) when no data exists.
    2. Scenario-expertise match — AGENT_SCENARIO_WEIGHTS matrix × detected category.
    3. Conviction multiplier   — consistency across all 3 debate rounds.
    4. Bayesian Gaussian update — treats each agent as N(midpoint, σ²) where
                                  σ = BASE_SIGMA / composite_weight.
                                  Posterior = weighted Gaussian with 90% CI.

    Final weight = track_record × scenario_relevance × conviction × confidence.
    """
    from history import get_agent_track_records  # deferred to avoid circular import

    valid = [f for f in rounds[2] if f.status == "ok"]
    if not valid:
        return aggregate_forecasts(rounds[2])

    # Layer 1: track record
    track_records = get_agent_track_records()

    # Layer 2: scenario expertise
    category = classify_scenario(scenario_text)

    # Layer 3: conviction
    conviction = _conviction_multipliers(rounds)

    # Composite weight per agent
    composite: dict[str, float] = {}
    for f in valid:
        name = f.agent_name
        tr = track_records.get(name, 0.5)
        sr = AGENT_SCENARIO_WEIGHTS.get(name, {}).get(category, 1.0)
        cv = conviction.get(name, 1.0)
        composite[name] = tr * sr * cv * f.confidence

    # Layer 4: Bayesian Gaussian update
    # Each agent contributes likelihood N(midpoint_i, σ_i²), σ_i = BASE_SIGMA / w_i.
    # Posterior with flat prior: precision-weighted mean, variance = 1/Σ(1/σ_i²).
    total_precision = 0.0
    weighted_mean_num = 0.0
    for f in valid:
        w = max(composite[f.agent_name], 0.01)
        midpoint = (f.target_low + f.target_high) / 2
        sigma = _BASE_SIGMA / w
        precision = 1.0 / sigma ** 2
        total_precision += precision
        weighted_mean_num += midpoint * precision

    posterior_mean = weighted_mean_num / total_precision
    posterior_std = math.sqrt(1.0 / total_precision)
    credible_low = round(posterior_mean - 1.645 * posterior_std, 2)
    credible_high = round(posterior_mean + 1.645 * posterior_std, 2)

    # Direction probabilities: composite-weight-based
    total_w = sum(composite[f.agent_name] for f in valid)
    bull_w = sum(composite[f.agent_name] for f in valid if f.direction == "bullish")
    bear_w = sum(composite[f.agent_name] for f in valid if f.direction == "bearish")
    base_w = sum(composite[f.agent_name] for f in valid if f.direction == "neutral")
    bull_prob = bull_w / total_w if total_w > 0 else 0.0
    bear_prob = bear_w / total_w if total_w > 0 else 0.0
    base_prob = base_w / total_w if total_w > 0 else 0.0

    sorted_highs = sorted([f.target_high for f in valid], reverse=True)
    sorted_lows = sorted([f.target_low for f in valid])
    bull_target = sum(sorted_highs[:2]) / 2
    bear_target = sum(sorted_lows[:2]) / 2

    # Disagreement: opposing above-average-weight agents
    avg_w = total_w / len(valid)
    bullish_hw = [f for f in valid if f.direction == "bullish" and composite[f.agent_name] >= avg_w * 0.8]
    bearish_hw = [f for f in valid if f.direction == "bearish" and composite[f.agent_name] >= avg_w * 0.8]
    disagreement = len(bullish_hw) > 0 and len(bearish_hw) > 0
    if disagreement:
        detail = (
            ", ".join(f.agent_name for f in bullish_hw) + " (bullish) vs "
            + ", ".join(f.agent_name for f in bearish_hw) + " (bearish)"
        )
    else:
        detail = ""

    avg_conf = sum(f.confidence for f in valid) / len(valid)

    return Consensus(
        bull_prob=round(bull_prob, 3),
        base_prob=round(base_prob, 3),
        bear_prob=round(bear_prob, 3),
        consensus_target=round(posterior_mean, 2),
        bull_target=round(bull_target, 2),
        base_target=round(posterior_mean, 2),
        bear_target=round(bear_target, 2),
        agent_count=len(valid),
        avg_confidence=round(avg_conf, 3),
        disagreement=disagreement,
        disagreement_detail=detail,
        credible_low=credible_low,
        credible_high=credible_high,
        method="bayesian",
    )


# ── 5-Layer Institutional Consensus Engine ────────────────────────────────────

def aggregate_forecasts_institutional(
    rounds: list,
    scenario_text: str,
    regime: str,
    current_price: float,
    macro_context: dict = None,
) -> Consensus:
    """
    5-Layer Institutional Consensus Engine:

    Layer 1 — Black-Litterman Prior: scalar BL fuses a market-implied return
              (RF + 1.15×ERP, annualised → 5-day) with agent Gaussian views via
              precision-weighted update.  Prior precision = 1/(τ×σ²), τ=0.025.

    Layer 2 — Copula Dependency Correction: effective_N = N²/Σcorr accounts for
              inter-agent correlation; posterior_std ×= sqrt(N/effective_N).

    Layer 3 — Regime-Adaptive Weights: multiplies composite weight for agents
              best suited to the current market regime (or "crisis" if VIX>35).

    Layer 4 — Shannon Entropy Disagreement: H>1.0 → HIGH ENTROPY, CI×1.5;
              H<0.5 → GROUPTHINK.

    Layer 5 — Fractional Kelly Conviction: kelly × 0.35 fraction → 0–100 score.
    """
    from history import get_agent_track_records  # deferred to avoid circular import

    valid = [f for f in rounds[2] if f.status == "ok"]
    if not valid:
        return aggregate_forecasts(rounds[2])

    if macro_context is None:
        macro_context = {}

    # ── Layer 1: Black-Litterman Prior ────────────────────────────────────────
    RF  = macro_context.get("risk_free_rate", 0.05)
    ERP = 0.05  # equity risk premium (constant)
    tau = 0.025
    implied_annual = RF + 1.15 * ERP
    if current_price and current_price > 0:
        bl_prior_mean  = current_price * (1.0 + implied_annual * 5.0 / 252.0)
        prior_precision = 1.0 / (tau * _BASE_SIGMA ** 2)
    else:
        bl_prior_mean   = None
        prior_precision = 0.0

    # ── Prerequisite: track record + scenario + conviction weights ────────────
    track_records = get_agent_track_records()
    category  = classify_scenario(scenario_text)
    conviction = _conviction_multipliers(rounds)

    # ── Layer 3: Regime-Adaptive Weights ─────────────────────────────────────
    actual_regime = regime
    if macro_context.get("vix", 0) > 35:
        actual_regime = "crisis"
    regime_mults = _REGIME_WEIGHTS.get(actual_regime, {})

    composite: dict[str, float] = {}
    for f in valid:
        name = f.agent_name
        tr = track_records.get(name, 0.5)
        sr = AGENT_SCENARIO_WEIGHTS.get(name, {}).get(category, 1.0)
        cv = conviction.get(name, 1.0)
        rg = regime_mults.get(name, 1.0)
        composite[name] = tr * sr * cv * rg * f.confidence

    upweighted_agents = [
        name for name in regime_mults
        if regime_mults[name] > 1.0 and any(f.agent_name == name for f in valid)
    ]

    # ── Layer 1 (cont.) + 4 (Gaussian update) ────────────────────────────────
    total_precision  = prior_precision
    weighted_mean_num = (prior_precision * bl_prior_mean) if bl_prior_mean is not None else 0.0
    for f in valid:
        w         = max(composite[f.agent_name], 0.01)
        midpoint  = (f.target_low + f.target_high) / 2.0
        sigma     = _BASE_SIGMA / w
        precision = 1.0 / sigma ** 2
        total_precision   += precision
        weighted_mean_num += midpoint * precision

    posterior_mean = weighted_mean_num / total_precision
    posterior_std  = math.sqrt(1.0 / total_precision)

    # ── Layer 2: Copula correction ────────────────────────────────────────────
    N = len(valid)
    agent_names = [f.agent_name for f in valid]
    sum_corr = 0.0
    for i, a in enumerate(agent_names):
        for j, b_name in enumerate(agent_names):
            if i == j:
                sum_corr += 1.0
            else:
                sum_corr += _AGENT_CORRELATION.get((a, b_name), _DEFAULT_AGENT_CORR)
    effective_N    = (N ** 2) / sum_corr if sum_corr > 0 else float(N)
    copula_factor  = math.sqrt(N / effective_N) if effective_N > 0 else 1.0
    posterior_std *= copula_factor

    # ── Direction probabilities ───────────────────────────────────────────────
    total_w = sum(composite[f.agent_name] for f in valid)
    bull_w  = sum(composite[f.agent_name] for f in valid if f.direction == "bullish")
    bear_w  = sum(composite[f.agent_name] for f in valid if f.direction == "bearish")
    base_w  = sum(composite[f.agent_name] for f in valid if f.direction == "neutral")
    bull_prob = bull_w / total_w if total_w > 0 else 0.0
    bear_prob = bear_w / total_w if total_w > 0 else 0.0
    base_prob = base_w / total_w if total_w > 0 else 0.0

    # ── Layer 4: Shannon Entropy → entropy_label + CI adjustment ─────────────
    H = 0.0
    for p in (bull_prob, bear_prob, base_prob):
        if p > 0:
            H -= p * math.log2(p)
    if H > 1.0:
        entropy_label = "HIGH ENTROPY"
        posterior_std *= 1.5
    elif H < 0.5:
        entropy_label = "GROUPTHINK"
    else:
        entropy_label = ""

    credible_low  = round(posterior_mean - 1.645 * posterior_std, 2)
    credible_high = round(posterior_mean + 1.645 * posterior_std, 2)

    # ── Layer 5: Fractional Kelly Conviction ──────────────────────────────────
    p_best = max(bull_prob, bear_prob, base_prob)
    b = (posterior_mean / current_price - 1.0) if current_price and current_price > 0 else 0.0
    if b <= 0:
        conviction_score = 0
    else:
        q = 1.0 - p_best
        kelly = (p_best * b - q) / b * 0.35
        kelly = max(0.0, min(kelly, 0.25))
        conviction_score = int(kelly / 0.25 * 100)

    # ── Price targets ─────────────────────────────────────────────────────────
    sorted_highs = sorted([f.target_high for f in valid], reverse=True)
    sorted_lows  = sorted([f.target_low  for f in valid])
    bull_target  = sum(sorted_highs[:2]) / 2
    bear_target  = sum(sorted_lows[:2])  / 2

    # ── Disagreement ──────────────────────────────────────────────────────────
    avg_w      = total_w / N
    bullish_hw = [f for f in valid if f.direction == "bullish" and composite[f.agent_name] >= avg_w * 0.8]
    bearish_hw = [f for f in valid if f.direction == "bearish" and composite[f.agent_name] >= avg_w * 0.8]
    disagreement = len(bullish_hw) > 0 and len(bearish_hw) > 0
    detail = (
        ", ".join(f.agent_name for f in bullish_hw) + " (bullish) vs "
        + ", ".join(f.agent_name for f in bearish_hw) + " (bearish)"
    ) if disagreement else ""

    avg_conf = sum(f.confidence for f in valid) / N

    return Consensus(
        bull_prob=round(bull_prob, 3),
        base_prob=round(base_prob, 3),
        bear_prob=round(bear_prob, 3),
        consensus_target=round(posterior_mean, 2),
        bull_target=round(bull_target, 2),
        base_target=round(posterior_mean, 2),
        bear_target=round(bear_target, 2),
        agent_count=N,
        avg_confidence=round(avg_conf, 3),
        disagreement=disagreement,
        disagreement_detail=detail,
        credible_low=credible_low,
        credible_high=credible_high,
        method="institutional",
        conviction_score=conviction_score,
        regime_label=actual_regime,
        upweighted_agents=upweighted_agents,
        entropy_label=entropy_label,
    )
