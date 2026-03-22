import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

COLORS = {
    "bg": "#000000",
    "surface": "#161b22",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#8b949e",
    "green": "#22c55e",
    "red": "#ef4444",
    "blue": "#58a6ff",
    "yellow": "#d29922",
}


def build_candlestick(df: pd.DataFrame, indicators: dict) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        row_heights=[0.72, 0.28],
        shared_xaxes=True,
        vertical_spacing=0.02,
    )

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="QQQ",
            increasing=dict(line=dict(color=COLORS["green"], width=1), fillcolor=COLORS["green"]),
            decreasing=dict(line=dict(color=COLORS["red"], width=1), fillcolor=COLORS["red"]),
        ),
        row=1, col=1,
    )

    close = df["Close"].squeeze()

    # SMA overlays
    if indicators.get("sma_50"):
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=close.rolling(50).mean(),
                name="SMA50",
                line=dict(color=COLORS["blue"], width=1),
                opacity=0.5,
            ),
            row=1, col=1,
        )

    if indicators.get("sma_200"):
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=close.rolling(200).mean(),
                name="SMA200",
                line=dict(color=COLORS["yellow"], width=1),
                opacity=0.5,
            ),
            row=1, col=1,
        )

    # Current price line
    current_price = float(close.iloc[-1])
    fig.add_hline(
        y=current_price,
        line=dict(color=COLORS["green"], width=0.8, dash="dot"),
        row=1, col=1,
    )

    # MACD in subplot
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_series = ema12 - ema26
    signal_series = macd_series.ewm(span=9, adjust=False).mean()
    histogram = macd_series - signal_series
    bar_colors = [COLORS["green"] if v >= 0 else COLORS["red"] for v in histogram]

    fig.add_trace(
        go.Bar(x=df.index, y=histogram, name="Hist", marker_color=bar_colors, opacity=0.5),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=macd_series, name="MACD", line=dict(color=COLORS["blue"], width=1)),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=signal_series, name="Signal", line=dict(color=COLORS["yellow"], width=1)),
        row=2, col=1,
    )

    axis_style = dict(
        gridcolor=COLORS["border"],
        linecolor=COLORS["border"],
        tickfont=dict(color=COLORS["muted"], size=9, family="JetBrains Mono, monospace"),
        showgrid=True,
        zeroline=False,
    )

    fig.update_layout(
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        font=dict(color=COLORS["text"], family="JetBrains Mono, monospace", size=10),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        margin=dict(l=0, r=55, t=30, b=0),
        height=400,
        xaxis=axis_style,
        yaxis=dict(**axis_style, side="right"),
        xaxis2=axis_style,
        yaxis2=dict(**axis_style, side="right"),
    )

    return fig
