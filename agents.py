import time
from pathlib import Path
from dotenv import load_dotenv
import anthropic
from pydantic import BaseModel

load_dotenv()
from typing import Literal, Optional
from concurrent.futures import ThreadPoolExecutor

from consensus import aggregate_forecasts

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-6"
# Rounds 1 & 2 get fewer tokens (faster, still sufficient for 2-3 sentence reasoning).
# Round 3 gets the full budget for final committed forecast.
MAX_TOKENS_R1R2 = 500
MAX_TOKENS_R3 = 600

_KNOWLEDGE_DIR = Path(__file__).parent / "agents_knowledge"
_KNOWLEDGE_FILES = {
    "Macro Strategist":  "macro_strategist.md",
    "Momentum Analyst":  "momentum_analyst.md",
    "Sentiment Analyst": "sentiment_analyst.md",
    "Quant Modeler":     "quant_modeler.md",
    "Earnings Analyst":  "earnings_analyst.md",
}

def _load_knowledge() -> dict[str, str]:
    knowledge = {}
    for agent, filename in _KNOWLEDGE_FILES.items():
        path = _KNOWLEDGE_DIR / filename
        if path.exists():
            knowledge[agent] = path.read_text(encoding="utf-8").strip()
    return knowledge

_AGENT_KNOWLEDGE: dict[str, str] = _load_knowledge()

# JSON schema for tool-based structured output
FORECAST_TOOL = {
    "name": "submit_forecast",
    "description": "Submit your price forecast for the given scenario",
    "input_schema": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["bullish", "bearish", "neutral"],
                "description": "Your directional call for the 5-day outlook",
            },
            "confidence": {
                "type": "number",
                "description": "Conviction level from 0.0 (no conviction) to 1.0 (certain)",
            },
            "target_low": {
                "type": "number",
                "description": "Lower bound of 5-day price target",
            },
            "target_high": {
                "type": "number",
                "description": "Upper bound of 5-day price target",
            },
            "reasoning": {
                "type": "string",
                "description": "2-3 sentences explaining your forecast. Reference specific data.",
            },
            "revised_from": {
                "type": ["string", "null"],
                "description": "Your Round 1 direction if you changed it, else null",
            },
        },
        "required": ["direction", "confidence", "target_low", "target_high", "reasoning"],
    },
}

AGENT_PERSONAS: dict[str, dict] = {
    "Macro Strategist": {
        "system": (
            "You are a veteran macro strategist specializing in Federal Reserve policy, "
            "interest rate cycles, DXY movements, and yield curve dynamics. You have a "
            "historically cautious bias — rate cuts can signal panic as often as stimulus. "
            "Focus on historical analogues and macro regime context. Reference specific "
            "dates and analogues in your reasoning. Be concise and data-driven."
        ),
        "context_fields": ["scenario", "analogues", "macro_context", "regime"],
        "news_categories": ["Fed & Rates", "Economic Data", "Trade & Geopolitics"],
        "priority_data": ["economic_calendar"],
    },
    "Momentum Analyst": {
        "system": (
            "You are a quantitative momentum analyst. You live by RSI, MACD, moving average "
            "crossovers, and trend strength. Your bias is trend-following — you don't fight "
            "the tape. Reference specific indicator values (exact numbers) in your reasoning. "
            "Be concise and technically grounded."
        ),
        "context_fields": ["scenario", "current_indicators", "price_table", "regime"],
        "news_categories": ["Market Structure", "Tech & AI"],
        "priority_data": ["key_dates"],
    },
    "Sentiment Analyst": {
        "system": (
            "You are a market sentiment analyst. You track VIX levels and fear/greed signals. "
            "You have a contrarian bias — extreme fear is a buy signal, extreme complacency is "
            "a warning. Reference VIX levels and regime in your reasoning. Be concise."
        ),
        "context_fields": ["scenario", "macro_context", "current_indicators", "analogues"],
        "news_categories": ["Market Structure", "Trade & Geopolitics", "Fed & Rates"],
        "priority_data": [],
    },
    "Quant Modeler": {
        "system": (
            "You are a quantitative modeler specializing in volatility regimes and return "
            "distributions. You prefer wide confidence intervals over false precision. Think "
            "in probabilities. Reference vol regime, mean daily return, and max drawdown "
            "in your reasoning. Give wider target ranges than other agents when uncertainty "
            "is high. Be concise and statistically grounded."
        ),
        "context_fields": ["scenario", "current_indicators", "summary_stats", "regime", "analogues"],
        "news_categories": ["Market Structure", "Economic Data"],
        "priority_data": ["key_dates"],
    },
    "Earnings Analyst": {
        "system": (
            "You are a fundamental earnings analyst focusing on mega-cap tech. You understand "
            "how rate changes affect DCF valuations. QQQ is 40%+ mega-cap tech — rate cuts "
            "directly expand growth multiples. Reference NVDA, MSFT, AMZN, AAPL, META and "
            "their rate sensitivity. Be concise and fundamentals-driven."
        ),
        "context_fields": ["scenario", "macro_context", "current_indicators", "analogues"],
        "news_categories": ["Earnings", "Tech & AI", "Fed & Rates"],
        "priority_data": ["earnings_calendar", "analyst_consensus"],
    },
}


class ForecastResult(BaseModel):
    direction: Literal["bullish", "bearish", "neutral"]
    confidence: float
    target_low: float
    target_high: float
    reasoning: str
    timeframe: Literal["5d"] = "5d"
    round_num: int = 1
    revised_from: Optional[str] = None
    agent_name: str = ""
    status: str = "ok"  # "ok" | "error"


class SimulationResult:
    def __init__(self, rounds: list[list[ForecastResult]], consensus):
        self.rounds = rounds
        self.consensus = consensus


def build_agent_context(agent_name: str, seed: dict) -> str:
    fields = AGENT_PERSONAS[agent_name]["context_fields"]
    lines = [f"## Market Context (auto-generated from live news)\n{seed['scenario']}\n"]

    if "macro_context" in fields:
        m = seed.get("macro_context", {})
        lines.append(
            f"## Macro Context\n"
            f"- VIX: {m.get('vix', 'N/A')}\n"
            f"- DXY: {m.get('dxy', 'N/A')}\n"
            f"- 10Y Yield: {m.get('yield_10y', 'N/A')}%\n"
            f"- Fed Funds Rate: {m.get('fed_rate', 'N/A')}%\n"
        )

    if "current_indicators" in fields:
        ind = seed.get("current_indicators", {})
        lines.append(
            f"## Technical Indicators\n"
            f"- RSI(14): {ind.get('rsi')}\n"
            f"- MACD: {ind.get('macd')} (signal: {ind.get('macd_signal')})\n"
            f"- BB Position: {ind.get('bb_position')}\n"
            f"- SMA50: {ind.get('sma_50')}\n"
            f"- SMA200: {ind.get('sma_200')}\n"
        )

    if "summary_stats" in fields:
        stats = seed.get("current_indicators", {}).get("summary_stats", {})
        lines.append(
            f"## Statistical Summary\n"
            f"- Mean Daily Return: {stats.get('mean_daily_return_pct')}%\n"
            f"- Annual Vol: {stats.get('annual_vol_pct')}%\n"
            f"- Max Drawdown: {stats.get('max_drawdown_pct')}%\n"
            f"- Data Points: {stats.get('total_days')} days\n"
        )

    if "regime" in fields:
        lines.append(f"## Market Regime\n{seed.get('regime', 'unknown')}\n")

    if "analogues" in fields and seed.get("analogues"):
        lines.append("## Historical Analogues (statistically similar past conditions)")
        for a in seed["analogues"]:
            sign5 = "+" if a.return_5d > 0 else ""
            line = f"- {a.date}: {a.event_label} → 5d: {sign5}{a.return_5d:.1f}%"
            if hasattr(a, "return_1d"):
                s1 = "+" if a.return_1d > 0 else ""
                s10 = "+" if a.return_10d > 0 else ""
                s20 = "+" if a.return_20d > 0 else ""
                line += f" | 1d: {s1}{a.return_1d:.1f}% 10d: {s10}{a.return_10d:.1f}% 20d: {s20}{a.return_20d:.1f}%"
            if hasattr(a, "similarity_score"):
                line += f" [similarity: {a.similarity_score:.0%}]"
            if hasattr(a, "regime"):
                line += f" (regime: {a.regime})"
            lines.append(line)
        lines.append("")

    if "price_table" in fields and seed.get("price_history") is not None:
        df = seed["price_history"].tail(60)
        lines.append("## Recent Price History (last 60 trading days)")
        lines.append("| Date | Open | High | Low | Close |")
        lines.append("|------|------|------|-----|-------|")
        for idx, row in df.iterrows():
            lines.append(
                f"| {idx.strftime('%Y-%m-%d')} | {row['Open']:.2f} | {row['High']:.2f} | {row['Low']:.2f} | {row['Close']:.2f} |"
            )
        lines.append("")

    # ── Per-agent filtered news briefing ──────────────────────────────────────
    news_cats = AGENT_PERSONAS[agent_name].get("news_categories", [])
    live_news = seed.get("live_news", [])
    if live_news:
        from news import get_news_briefing
        lines.append(get_news_briefing(live_news, n=8, categories=news_cats or None))
        lines.append("")
    elif seed.get("live_news_text"):
        lines.append(seed["live_news_text"])
        lines.append("")

    # ── Priority data sections (agent-specific) ────────────────────────────
    priority = AGENT_PERSONAS[agent_name].get("priority_data", [])

    if "earnings_calendar" in priority and seed.get("earnings_calendar"):
        lines.append("## Upcoming Earnings (next 60 days)")
        for e in seed["earnings_calendar"][:8]:
            eps = f" | EPS est: {e['eps_estimate']}" if e.get("eps_estimate") else ""
            lines.append(f"- {e['date']} {e['symbol']}{eps}")
        lines.append("")

    if "economic_calendar" in priority and seed.get("economic_calendar"):
        lines.append("## Upcoming Economic Events (next 30 days)")
        for e in seed["economic_calendar"][:6]:
            detail = f" | Est: {e.get('estimate', 'N/A')} Prev: {e.get('previous', 'N/A')}"
            lines.append(f"- {e['date']} {e['event']}{detail}")
        lines.append("")

    if "analyst_consensus" in priority and seed.get("analyst_consensus"):
        lines.append("## Analyst Consensus (top QQQ holdings)")
        for a in seed["analyst_consensus"]:
            target = f" | PT: ${a['target_mean']:.0f}" if a.get("target_mean") else ""
            current = f" (curr: ${a['current_price']:.0f})" if a.get("current_price") else ""
            lines.append(
                f"- {a['symbol']}: Buy={a['buy']} Hold={a['hold']} Sell={a['sell']}{target}{current}"
            )
        lines.append("")

    if "key_dates" in priority and seed.get("key_dates"):
        lines.append("## Key Market Dates (next 30 days)")
        for e in seed["key_dates"][:6]:
            lines.append(f"- {e['date']} [{e['type'].upper()}] {e['event']}: {e.get('detail','')}")
        lines.append("")

    lines.append(f"## Current Price\n{seed['ticker']}: ${seed.get('current_price', 'N/A')}\n")
    lines.append(
        "Based on the current market conditions and latest news above, provide your "
        "5-trading-day QQQ price forecast. Reference specific news articles by source "
        "in your reasoning (e.g. 'The Reuters report on... supports my thesis because...')."
    )
    return "\n".join(lines)


def _call_agent(
    agent_name: str,
    seed: dict,
    prior_messages: list,
    round_num: int,
    stagger_delay: float = 0.0,
) -> ForecastResult:
    """Single agent API call with retry. Runs inside a ThreadPoolExecutor thread."""
    if stagger_delay:
        time.sleep(stagger_delay)

    context = build_agent_context(agent_name, seed)
    # Interleave assistant acks so consecutive user messages don't cause 400s
    messages = []
    for msg in prior_messages:
        messages.append(msg)
        if msg["role"] == "user":
            messages.append({"role": "assistant", "content": "Understood."})
    messages.append({"role": "user", "content": context})

    try:
        for attempt in range(4):
            try:
                knowledge = _AGENT_KNOWLEDGE.get(agent_name, "")
                base_system = AGENT_PERSONAS[agent_name]["system"]
                system_prompt = f"{knowledge}\n\n{base_system}" if knowledge else base_system
                system_prompt += (
                    " Reference the historical analogues provided when forming your view. "
                    "Explain whether the current situation is more similar to the bullish or "
                    "bearish analogues, and why this time might differ."
                )
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS_R3 if round_num == 3 else MAX_TOKENS_R1R2,
                    system=system_prompt,
                    tools=[FORECAST_TOOL],
                    tool_choice={"type": "tool", "name": "submit_forecast"},
                    messages=messages,
                )
                tool_block = next(
                    (b for b in response.content if b.type == "tool_use"), None
                )
                if tool_block:
                    inp = tool_block.input
                    # Guard against model returning incomplete tool input (can happen near token limit)
                    required = ("direction", "confidence", "target_low", "target_high", "reasoning")
                    if not all(k in inp and inp[k] for k in required):
                        # Fallback: scrape reasoning from any text content block
                        text_blocks = [b for b in response.content if b.type == "text" and b.text.strip()]
                        if text_blocks and "reasoning" not in inp:
                            inp = dict(inp)
                            inp["reasoning"] = text_blocks[0].text.strip()[:400]
                        if not all(k in inp and inp[k] for k in required):
                            if attempt < 3:
                                time.sleep(2 ** attempt)
                                continue
                            raise RuntimeError(f"Incomplete tool input after retries: {list(inp.keys())}")
                    return ForecastResult(
                        direction=inp["direction"],
                        confidence=max(0.0, min(1.0, float(inp["confidence"]))),
                        target_low=float(inp["target_low"]),
                        target_high=float(inp["target_high"]),
                        reasoning=inp.get("reasoning", "No reasoning provided."),
                        round_num=round_num,
                        revised_from=inp.get("revised_from"),
                        agent_name=agent_name,
                        status="ok",
                    )
            except anthropic.RateLimitError:
                wait = 2 * (2 ** attempt)  # 2s, 4s, 8s
                if attempt < 3:
                    time.sleep(wait)
                    continue
                raise
            except anthropic.APIStatusError:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise

        raise RuntimeError("No tool_use block returned after retries")

    except Exception as e:
        return ForecastResult(
            direction="neutral",
            confidence=0.5,
            target_low=0.0,
            target_high=0.0,
            reasoning=f"Agent unavailable: {str(e)[:100]}",
            round_num=round_num,
            agent_name=agent_name,
            status="error",
        )


def format_round_summary(results: list[ForecastResult]) -> str:
    lines = []
    for r in results:
        if r.status == "error":
            lines.append(f"[{r.agent_name}] STATUS=error (excluded)")
        else:
            lines.append(
                f"[{r.agent_name}] direction={r.direction} confidence={r.confidence:.2f} "
                f"target=${r.target_low:.0f}–${r.target_high:.0f}\n"
                f'  reasoning: "{r.reasoning}"'
            )
    return "\n".join(lines)


def run_simulation(seed: dict) -> SimulationResult:
    """Run 3-round debate simulation using ThreadPoolExecutor (sync, Streamlit-safe)."""
    agent_names = list(AGENT_PERSONAS.keys())

    def run_round(round_num: int, prior_messages: list) -> list[ForecastResult]:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                name: executor.submit(_call_agent, name, seed, prior_messages, round_num, i * 0.1)
                for i, name in enumerate(agent_names)  # 0.1s stagger avoids burst rate limits
            }
            return [futures[name].result() for name in agent_names]

    # Round 1: each agent forecasts independently
    round1 = run_round(1, [])

    # Round 2: agents see all Round 1 results and can challenge each other
    r1_summary = format_round_summary(round1)
    round2_messages = [
        {
            "role": "user",
            "content": (
                f"Round 1 forecasts from all analysts:\n\n{r1_summary}\n\n"
                "You are now in Round 2. Review the other analysts' forecasts above. "
                "You may revise your position if their arguments are compelling. "
                "If you disagree with any analyst, reference them by name explicitly."
            ),
        }
    ]
    round2 = run_round(2, round2_messages)

    # Round 3: final positions after seeing Round 2 debate
    r2_summary = format_round_summary(round2)
    round3_messages = round2_messages + [
        {
            "role": "user",
            "content": (
                f"Round 2 positions:\n\n{r2_summary}\n\n"
                "This is Round 3 — your final, committed forecast. No further revision."
            ),
        }
    ]
    round3 = run_round(3, round3_messages)

    # Consensus uses Round 3 only; Rounds 1 & 2 archived for UI display
    consensus = aggregate_forecasts(round3)
    return SimulationResult(rounds=[round1, round2, round3], consensus=consensus)
