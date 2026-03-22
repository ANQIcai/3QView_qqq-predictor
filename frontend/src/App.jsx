import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  Cell, ReferenceLine, BarChart, PieChart, Pie
} from "recharts";
import {
  RefreshCw, ChevronLeft, ChevronRight, Send, TrendingUp, TrendingDown,
  Minus, AlertTriangle, MessageSquare, Activity, BarChart3, Zap, Clock,
  ExternalLink
} from "lucide-react";

// ═══════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════

const TICKER = "QQQ";
const API_BASE = ""; // proxied via Vite to http://localhost:8000

/** Format an ISO datetime string as "Xm ago" / "Xh ago" / "Xd ago". */
function timeAgo(published) {
  if (!published) return "";
  const ms = Date.now() - new Date(published).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}


const AGENT_PERSONAS = [
  { name: "Macro Strategist", role: "Fed · rates · DXY", color: "#5B8DEF" },
  { name: "Momentum Analyst", role: "RSI · MACD · trend", color: "#E8B849" },
  { name: "Sentiment Analyst", role: "VIX · fear/greed", color: "#C77DFF" },
  { name: "Quant Modeler", role: "Vol · stats", color: "#26a69a" },
  { name: "Earnings Analyst", role: "Tech · DCF", color: "#ef5350" },
];


// ═══════════════════════════════════════════════════════════════════
// THEME
// ═══════════════════════════════════════════════════════════════════
const T = {
  bg0: "#000000", bg1: "#0a0a0c", bg2: "#141416", bg3: "#1c1c1e",
  border: "#2a2a2e", borderHover: "#3a3a3e",
  text: "#d1d4dc", textSec: "#787b86", textMuted: "#555",
  bull: "#26a69a", bear: "#ef5350", warn: "#d29922",
};

// ═══════════════════════════════════════════════════════════════════
// UTILITY COMPONENTS
// ═══════════════════════════════════════════════════════════════════

const SectionHeader = ({ children, badge, style }) => (
  <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "1.2px", textTransform: "uppercase", color: T.textSec, marginBottom: 10, display: "flex", alignItems: "center", gap: 8, ...style }}>
    {children}
    {badge && <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 8, color: T.text, background: T.border, padding: "1px 6px", borderRadius: 3 }}>{badge}</span>}
  </div>
);

const ProbBar = ({ label, pct, color }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, width: 30, color }}>{label}</span>
    <div style={{ flex: 1, height: 4, background: T.border, borderRadius: 2, overflow: "hidden" }}>
      <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 2, transition: "width 600ms cubic-bezier(0.22,1,0.36,1)" }} />
    </div>
    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: T.textSec, width: 28, textAlign: "right" }}>{pct}%</span>
  </div>
);

const StatRow = ({ label, value, color = T.text, mono = true }) => (
  <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: 10, borderBottom: `1px solid ${T.border}` }}>
    <span style={{ color: T.textSec }}>{label}</span>
    <span style={{ fontFamily: mono ? "'JetBrains Mono',monospace" : "inherit", color }}>{value}</span>
  </div>
);

const DirIcon = ({ dir, size = 12 }) => {
  if (dir === "bullish") return <TrendingUp size={size} color={T.bull} />;
  if (dir === "bearish") return <TrendingDown size={size} color={T.bear} />;
  return <Minus size={size} color={T.textSec} />;
};

const dirColor = d => d === "bullish" ? T.bull : d === "bearish" ? T.bear : T.textSec;
const dirSym = d => d === "bullish" ? "▲" : d === "bearish" ? "▼" : "◆";

// ═══════════════════════════════════════════════════════════════════
// CANDLESTICK CHART
// ═══════════════════════════════════════════════════════════════════

const CandlestickChart = ({ data }) => {
  const recent = data.slice(-90);
  const chartData = recent.map(d => ({
    ...d,
    fill: d.close >= d.open ? T.bull : T.bear,
    bodyLow: Math.min(d.open, d.close),
    bodyHigh: Math.max(d.open, d.close),
    bodySize: Math.abs(d.close - d.open),
    wickRange: [d.low, d.high],
  }));

  const allLows = chartData.map(d => d.low);
  const allHighs = chartData.map(d => d.high);
  const yMin = Math.floor(Math.min(...allLows) - 2);
  const yMax = Math.ceil(Math.max(...allHighs) + 2);

  const CustomCandle = ({ x, y, width, height, payload }) => {
    if (!payload) return null;
    const { open, close, high, low, fill } = payload;
    const barW = Math.max(width * 0.7, 2);
    const xc = x + width / 2;
    const yScale = (val) => {
      const range = yMax - yMin;
      return y + height - ((val - yMin) / range) * height;
    };
    const yOpen = yScale(open);
    const yClose = yScale(close);
    const yHigh = yScale(high);
    const yLow = yScale(low);
    const bodyTop = Math.min(yOpen, yClose);
    const bodyH = Math.max(Math.abs(yOpen - yClose), 1);

    return (
      <g>
        <line x1={xc} y1={yHigh} x2={xc} y2={yLow} stroke={fill} strokeWidth={1} opacity={0.6} />
        <rect x={xc - barW / 2} y={bodyTop} width={barW} height={bodyH} fill={fill} rx={1} />
      </g>
    );
  };

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.[0]) return null;
    const d = payload[0].payload;
    return (
      <div style={{ background: T.bg3, border: `1px solid ${T.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 10 }}>
        <div style={{ color: T.textSec, marginBottom: 4, fontFamily: "'JetBrains Mono',monospace" }}>{d.date}</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2px 12px" }}>
          <span style={{ color: T.textSec }}>O</span><span style={{ color: T.text, fontFamily: "'JetBrains Mono',monospace" }}>{d.open}</span>
          <span style={{ color: T.textSec }}>H</span><span style={{ color: T.text, fontFamily: "'JetBrains Mono',monospace" }}>{d.high}</span>
          <span style={{ color: T.textSec }}>L</span><span style={{ color: T.text, fontFamily: "'JetBrains Mono',monospace" }}>{d.low}</span>
          <span style={{ color: T.textSec }}>C</span><span style={{ color: d.close >= d.open ? T.bull : T.bear, fontFamily: "'JetBrains Mono',monospace" }}>{d.close}</span>
        </div>
      </div>
    );
  };

  // SMA20 overlay
  const smaData = chartData.map((d, i) => {
    if (i < 19) return { ...d, sma20: null };
    const slice = chartData.slice(i - 19, i + 1);
    const avg = slice.reduce((s, v) => s + v.close, 0) / 20;
    return { ...d, sma20: +avg.toFixed(2) };
  });

  return (
    <div style={{ background: T.bg2, border: `1px solid ${T.border}`, borderRadius: 6, padding: "12px 8px 4px 0" }}>
      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={smaData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <XAxis dataKey="dateLabel" tick={{ fontSize: 9, fill: T.textMuted }} interval={14} tickLine={false} axisLine={{ stroke: T.border }} />
          <YAxis domain={[yMin, yMax]} tick={{ fontSize: 9, fill: T.textSec }} tickLine={false} axisLine={false} orientation="right" tickFormatter={v => v.toFixed(0)} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="high" shape={<CustomCandle />} isAnimationActive={false} />
          <Line dataKey="sma20" stroke="#5B8DEF" strokeWidth={1.2} dot={false} strokeDasharray="4 2" connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// VOLUME BAR (mini)
// ═══════════════════════════════════════════════════════════════════
const VolumeBar = ({ data }) => {
  const recent = data.slice(-90);
  return (
    <div style={{ background: T.bg2, border: `1px solid ${T.border}`, borderTop: "none", borderRadius: "0 0 6px 6px", padding: "0 8px 4px 0" }}>
      <ResponsiveContainer width="100%" height={48}>
        <BarChart data={recent} margin={{ top: 2, right: 12, bottom: 0, left: 0 }}>
          <XAxis dataKey="dateLabel" hide />
          <YAxis hide />
          <Bar dataKey="volume" isAnimationActive={false}>
            {recent.map((d, i) => (
              <Cell key={i} fill={d.close >= d.open ? "rgba(38,166,154,0.3)" : "rgba(239,83,80,0.3)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// SIDEBAR SECTIONS
// ═══════════════════════════════════════════════════════════════════

const MarketPulse = ({ price = 0, change = 0, changePct = 0, macro = {}, regime = "" }) => {
  const chgColor = change >= 0 ? T.bull : T.bear;
  const sign = change >= 0 ? "+" : "";
  const regimeColor = regime.includes("bear") ? T.bear : regime.includes("bull") ? T.bull : T.textSec;
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: T.textSec, marginBottom: 10 }}>MARKET PULSE</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, paddingBottom: 10, borderBottom: `1px solid ${T.border}`, marginBottom: 8 }}>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 17, fontWeight: 700, color: T.text }}>${price.toFixed(2)}</span>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: chgColor }}>{sign}{change} ({sign}{changePct}%)</span>
      </div>
      <StatRow label="VIX" value={macro.vix ?? "—"} />
      <StatRow label="DXY" value={macro.dxy ?? "—"} />
      <StatRow label="10Y Yield" value={macro.yield_10y != null ? `${macro.yield_10y}%` : "—"} />
      <StatRow label="Fed Rate" value={macro.fed_rate != null ? `${macro.fed_rate}%` : "—"} />
      <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: 10 }}>
        <span style={{ color: T.textSec }}>Regime</span>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", color: regimeColor, fontWeight: 600 }}>{regime.replace(/_/g, " ")}</span>
      </div>
    </div>
  );
};

const NewsPanel = ({ articles = [] }) => {
  const [filter, setFilter] = useState("All");
  const cats = ["All", "Fed & Rates", "Earnings", "Tech & AI", "Macro"];
  const filterMap = { "All": null, "Fed & Rates": ["Fed & Rates"], "Earnings": ["Earnings"], "Tech & AI": ["Tech & AI"], "Macro": ["Macro"] };
  const filtered = filterMap[filter] ? articles.filter(a => filterMap[filter].includes(a.category)) : articles;

  return (
    <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 12, marginTop: 8 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: T.textSec, marginBottom: 8 }}>
        QQQ NEWS <span style={{ fontWeight: 400, color: T.textMuted, letterSpacing: 0 }}>{articles.length}</span>
      </div>
      <div style={{ display: "flex", gap: 0, flexWrap: "wrap", marginBottom: 8 }}>
        {cats.map(c => (
          <button key={c} onClick={() => setFilter(c)} style={{
            padding: "3px 8px", fontSize: 10, border: "none", borderRadius: 4, cursor: "pointer",
            background: filter === c ? "rgba(255,255,255,0.04)" : "transparent",
            color: filter === c ? T.text : T.textSec,
            fontWeight: filter === c ? 600 : 400,
            fontFamily: "'DM Sans',sans-serif", transition: "all 180ms ease",
          }}>{c}</button>
        ))}
      </div>
      <div style={{ maxHeight: 320, overflowY: "auto", scrollbarWidth: "thin", scrollbarColor: `${T.borderHover} transparent` }}>
        {filtered.map((a, i) => (
          <div key={a.url || i} style={{
            padding: "7px 0", borderBottom: `1px solid ${T.border}`,
            borderLeft: a.sentiment > 0.3 ? `2px solid ${T.bull}` : a.sentiment < -0.3 ? `2px solid ${T.bear}` : "none",
            paddingLeft: a.sentiment > 0.3 || a.sentiment < -0.3 ? 8 : 0,
            transition: "background 180ms ease",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", marginBottom: 4 }}>
              {a.tickers.slice(0, 4).map(t => (
                <span key={t} style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 8, color: T.textSec, border: `1px solid ${T.border}`, borderRadius: 3, padding: "1px 4px" }}>{t}</span>
              ))}
              <span style={{ fontSize: 8, color: T.textMuted }}>{timeAgo(a.published)} · {a.source}</span>
            </div>
            <div style={{ fontSize: 11.5, color: T.text, lineHeight: 1.35, fontWeight: 500, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{a.title}</div>
            {a.url && <a href={a.url} target="_blank" rel="noreferrer" style={{ fontSize: 9, color: T.textMuted, textDecoration: "none", marginTop: 3, display: "inline-flex", alignItems: "center", gap: 3 }}>Read more <ExternalLink size={8} /></a>}
          </div>
        ))}
      </div>
    </div>
  );
};

const CalendarSection = ({ events = [] }) => {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth());
  const [year, setYear] = useState(now.getFullYear());

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstDay = new Date(year, month, 1).getDay();
  const monthName = new Date(year, month).toLocaleDateString("en-US", { month: "long" });

  const typeColors = { earnings: T.bear, fomc: T.bull, economic: T.textSec, opex: T.text };
  const typeLabels = { earnings: "Earn", fomc: "FOMC", economic: "Eco", opex: "OpEx" };

  const prefix = `${year}-${String(month + 1).padStart(2, "0")}-`;
  const monthEvents = events.filter(e => e.date.startsWith(prefix));
  const eventDays = new Set(monthEvents.map(e => parseInt(e.date.slice(-2))));

  const prev = () => { if (month === 0) { setMonth(11); setYear(y => y - 1); } else setMonth(m => m - 1); };
  const next = () => { if (month === 11) { setMonth(0); setYear(y => y + 1); } else setMonth(m => m + 1); };

  return (
    <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 12, marginTop: 8 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: T.textSec, marginBottom: 8 }}>KEY DATES</div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <button onClick={prev} style={{ background: "none", border: "none", color: T.textSec, cursor: "pointer", padding: 4 }}><ChevronLeft size={14} /></button>
        <span style={{ fontSize: 11, color: T.text, fontWeight: 600 }}>{monthName} {year}</span>
        <button onClick={next} style={{ background: "none", border: "none", color: T.textSec, cursor: "pointer", padding: 4 }}><ChevronRight size={14} /></button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 1, marginBottom: 6 }}>
        {["S","M","T","W","T","F","S"].map((d,i) => (
          <div key={i} style={{ fontSize: 8, color: T.textMuted, textAlign: "center", padding: 2 }}>{d}</div>
        ))}
        {Array.from({ length: firstDay }).map((_, i) => <div key={`e${i}`} />)}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const day = i + 1;
          const hasEvent = eventDays.has(day);
          const isToday = day === now.getDate() && month === now.getMonth() && year === now.getFullYear();
          return (
            <div key={day} style={{
              fontSize: 9, textAlign: "center", padding: "3px 0", borderRadius: 3,
              color: isToday ? T.bg0 : hasEvent ? T.text : T.textSec,
              background: isToday ? T.bull : hasEvent ? "rgba(255,255,255,0.04)" : "transparent",
              fontWeight: isToday ? 700 : hasEvent ? 600 : 400,
              fontFamily: "'JetBrains Mono',monospace",
            }}>{day}</div>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
        {Object.entries(typeLabels).map(([k, v]) => (
          <span key={k} style={{ fontSize: 8, color: typeColors[k] }}>● {v}</span>
        ))}
      </div>
      {monthEvents.slice(0, 6).map((e, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "flex-start", padding: "3px 0", borderBottom: `1px solid ${T.border}` }}>
          <span style={{ color: typeColors[e.type], fontSize: 8, marginTop: 2 }}>●</span>
          <div style={{ fontSize: 9 }}>
            <span style={{ fontFamily: "'JetBrains Mono',monospace", color: T.textSec }}>{e.date}</span>{" "}
            <span style={{ color: T.text }}>{e.event}</span>
            <div style={{ color: T.textMuted, fontSize: 8 }}>→ {e.agent}</div>
          </div>
        </div>
      ))}
    </div>
  );
};

const IndicatorsPanel = ({ indicators = {} }) => {
  const ind = indicators;
  const rows = [
    { label: "RSI(14)", value: ind.rsi != null ? +ind.rsi.toFixed(2) : "—", color: ind.rsi > 30 && ind.rsi < 70 ? T.bull : T.bear },
    { label: "MACD", value: ind.macd != null ? `${ind.macd > 0 ? "+" : ""}${(+ind.macd).toFixed(2)}` : "—", color: ind.macd > 0 ? T.bull : T.bear },
    { label: "BB Pos", value: ind.bb_position ?? "—", color: ind.bb_position === "lower" ? T.bull : ind.bb_position === "upper" ? T.bear : T.text },
    { label: "SMA20", value: ind.sma_20 != null ? +ind.sma_20.toFixed(2) : "—", color: T.text },
    { label: "SMA50", value: ind.sma_50 != null ? +ind.sma_50.toFixed(2) : "—", color: T.text },
    { label: "SMA200", value: ind.sma_200 != null ? +ind.sma_200.toFixed(2) : "—", color: T.text },
    { label: "EMA9", value: ind.ema_9 != null ? +ind.ema_9.toFixed(2) : "—", color: T.text },
    { label: "ATR(14)", value: ind.atr != null ? +ind.atr.toFixed(2) : "—", color: T.text },
  ];
  return (
    <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 12, marginTop: 8, marginBottom: 16 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: T.textSec, marginBottom: 8 }}>INDICATORS</div>
      {rows.map((r, i) => <StatRow key={i} label={r.label} value={r.value} color={r.color} />)}
    </div>
  );
};

const ConsensusTable = ({ holdings = [] }) => (
  <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 12, marginTop: 8, marginBottom: 16 }}>
    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: T.textSec, marginBottom: 8 }}>ANALYST CONSENSUS</div>
    <table style={{ width: "100%", fontSize: 10, borderCollapse: "collapse" }}>
      <thead>
        <tr>
          <th style={{ color: T.textMuted, textAlign: "left", padding: "4px 0", fontWeight: 600 }}>Sym</th>
          <th style={{ color: T.bull, textAlign: "right", padding: "4px 0", fontWeight: 600 }}>Buy</th>
          <th style={{ color: T.textSec, textAlign: "right", padding: "4px 0", fontWeight: 600 }}>Hold</th>
          <th style={{ color: T.bear, textAlign: "right", padding: "4px 0", fontWeight: 600 }}>Sell</th>
          <th style={{ color: T.text, textAlign: "right", padding: "4px 0", fontWeight: 600 }}>PT</th>
        </tr>
      </thead>
      <tbody>
        {holdings.map(c => (
          <tr key={c.symbol} style={{ borderTop: `1px solid ${T.border}` }}>
            <td style={{ color: T.text, padding: "4px 0", fontWeight: 500 }}>{c.symbol}</td>
            <td style={{ fontFamily: "'JetBrains Mono',monospace", color: T.bull, textAlign: "right", padding: "4px 0" }}>{c.buy ?? "—"}</td>
            <td style={{ fontFamily: "'JetBrains Mono',monospace", color: T.textSec, textAlign: "right", padding: "4px 0" }}>{c.hold ?? "—"}</td>
            <td style={{ fontFamily: "'JetBrains Mono',monospace", color: T.bear, textAlign: "right", padding: "4px 0" }}>{c.sell ?? "—"}</td>
            <td style={{ fontFamily: "'JetBrains Mono',monospace", color: T.text, textAlign: "right", padding: "4px 0" }}>{c.target_mean != null ? `$${(+c.target_mean).toFixed(0)}` : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const AnaloguesPanel = ({ analogues = [] }) => (
  <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 12, marginTop: 8, marginBottom: 16 }}>
    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: T.textSec, marginBottom: 8 }}>HISTORICAL ANALOGUES</div>
    {analogues.map((a, i) => (
      <div key={i} style={{ padding: "4px 0", borderBottom: `1px solid ${T.border}` }}>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: T.textSec }}>{a.date}</span>{" "}
        <span style={{ fontSize: 10, color: T.text }}>— {a.event}</span>
        <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: a.return_5d > 0 ? T.bull : T.bear, fontWeight: 600 }}>
          {a.return_5d > 0 ? "+" : ""}{a.return_5d}% (5d)
        </div>
      </div>
    ))}
  </div>
);

// ═══════════════════════════════════════════════════════════════════
// AGENT CARD
// ═══════════════════════════════════════════════════════════════════

const AgentCard = ({ agent, forecast }) => {
  const [hovered, setHovered] = useState(false);
  const accent = forecast.status === "ok" ? dirColor(forecast.direction) : T.textSec;
  const confPct = Math.round(forecast.confidence * 100);

  return (
    <div
      onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{
        background: T.bg3, border: `1px solid ${hovered ? T.borderHover : T.border}`,
        borderRadius: 6, padding: 12, flex: 1, minWidth: 0,
        borderTop: `2px solid ${accent}`,
        transition: "all 180ms ease",
        boxShadow: hovered ? "0 2px 12px rgba(0,0,0,0.3)" : "none",
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, color: T.text, marginBottom: 2 }}>{agent.name}</div>
      <div style={{ fontSize: 9, color: T.textSec, marginBottom: 8, letterSpacing: "0.02em" }}>{agent.role}</div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, fontWeight: 600, color: accent }}>
          {dirSym(forecast.direction)} {forecast.direction.charAt(0).toUpperCase() + forecast.direction.slice(1)}
        </span>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: T.textSec }}>{confPct}%</span>
      </div>
      <div style={{ height: 2, background: T.border, borderRadius: 1, marginBottom: 6 }}>
        <div style={{ height: "100%", width: `${confPct}%`, background: accent, borderRadius: 1, transition: "width 600ms cubic-bezier(0.22,1,0.36,1)" }} />
      </div>
      {forecast.status === "ok" && forecast.target_low > 0 && (
        <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: T.textSec, marginBottom: 4 }}>
          Target <span style={{ color: T.text }}>${forecast.target_low.toFixed(0)}–${forecast.target_high.toFixed(0)}</span>
        </div>
      )}
      <div style={{ fontSize: 9.5, color: T.textSec, lineHeight: 1.5, borderLeft: `2px solid ${T.border}`, paddingLeft: 8, marginTop: 6 }}>
        {forecast.reasoning}
      </div>
      {forecast.revised_from && forecast.revised_from !== forecast.direction && (
        <div style={{ fontSize: 8, color: T.textSec, border: `1px solid ${T.border}`, borderRadius: 4, padding: "2px 5px", display: "inline-block", marginTop: 4 }}>
          ↕ Revised from {forecast.revised_from}
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// ASK AN AGENT PANEL
// ═══════════════════════════════════════════════════════════════════

const AskAgent = ({ simulation, agents }) => {
  const [selected, setSelected] = useState(0);
  const [messages, setMessages] = useState({});
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  // All hooks must be declared before any conditional return.
  // Use `selected` (not `chatKey`) as dep since chatKey is derived post-guard.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, selected]);

  if (!simulation) {
    return (
      <div style={{ fontSize: 10, color: T.textMuted, padding: "20px 0", textAlign: "center" }}>
        Run a prediction to ask agents about their reasoning.
      </div>
    );
  }

  const forecast = simulation[2][selected];
  const agent = agents[selected];
  const chatKey = agent.name;
  const chat = messages[chatKey] || [];
  const accent = dirColor(forecast.direction);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const q = input.trim();
    setInput("");
    const newChat = [...chat, { role: "user", content: q }];
    setMessages(prev => ({ ...prev, [chatKey]: newChat }));
    setLoading(true);

    try {
      const resp = await fetch("/api/agent-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_name: agent.name,
          messages: newChat,
          forecast_direction: forecast.direction,
          forecast_confidence: forecast.confidence,
          forecast_target_low: forecast.target_low,
          forecast_target_high: forecast.target_high,
          forecast_reasoning: forecast.reasoning,
        }),
      });
      const data = await resp.json();
      const answer = data.response || "Agent unavailable.";
      setMessages(prev => ({ ...prev, [chatKey]: [...(prev[chatKey] || []), { role: "assistant", content: answer }] }));
    } catch {
      setMessages(prev => ({ ...prev, [chatKey]: [...(prev[chatKey] || []), { role: "assistant", content: "⚠ Connection error — try again." }] }));
    }
    setLoading(false);
  };

  return (
    <div>
      {/* Agent selector */}
      <div style={{ display: "flex", gap: 4, marginBottom: 10, flexWrap: "wrap" }}>
        {agents.map((a, i) => (
          <button key={i} onClick={() => setSelected(i)} style={{
            padding: "3px 8px", fontSize: 9, border: `1px solid ${selected === i ? T.borderHover : T.border}`,
            borderRadius: 4, cursor: "pointer", fontFamily: "'DM Sans',sans-serif",
            background: selected === i ? T.bg3 : "transparent",
            color: selected === i ? T.text : T.textSec,
            transition: "all 180ms ease",
          }}>{a.name.split(" ")[0]}</button>
        ))}
      </div>

      {/* Compact agent stance — one line */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", marginBottom: 8, borderBottom: `1px solid ${T.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, fontWeight: 600, color: accent }}>
            {dirSym(forecast.direction)} {forecast.direction.charAt(0).toUpperCase() + forecast.direction.slice(1)}
          </span>
          <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: T.textSec }}>{Math.round(forecast.confidence * 100)}%</span>
        </div>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: T.text }}>${forecast.target_low.toFixed(0)}–${forecast.target_high.toFixed(0)}</span>
      </div>

      {/* Chat */}
      <div ref={scrollRef} style={{ maxHeight: 260, overflowY: "auto", marginBottom: 8, scrollbarWidth: "thin", scrollbarColor: `${T.borderHover} transparent` }}>
        {chat.map((m, i) => (
          <div key={i} style={{
            background: m.role === "user" ? T.bg2 : T.bg3,
            border: `1px solid ${T.border}`, borderRadius: 6,
            padding: "8px 12px", fontSize: 10.5, marginBottom: 6,
            color: m.role === "user" ? T.textSec : T.text,
          }}>
            <div style={{ fontSize: 8, color: T.textSec, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
              {m.role === "user" ? "You" : agent.name}
            </div>
            {m.content}
          </div>
        ))}
        {loading && (
          <div style={{ fontSize: 10, color: T.textMuted, padding: 8, textAlign: "center" }}>
            <span style={{ animation: "pulse 1.5s ease infinite" }}>Thinking…</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div style={{ display: "flex", gap: 6 }}>
        <input
          value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && sendMessage()}
          placeholder="Ask about this agent's reasoning…"
          style={{
            flex: 1, background: T.bg0, border: `1px solid ${T.border}`, borderRadius: 4,
            color: T.text, fontSize: 11, padding: "6px 10px", outline: "none",
            fontFamily: "'DM Sans',sans-serif",
            transition: "border-color 180ms ease",
          }}
          onFocus={e => e.target.style.borderColor = T.borderHover}
          onBlur={e => e.target.style.borderColor = T.border}
        />
        <button onClick={sendMessage} disabled={loading || !input.trim()} style={{
          background: T.border, border: `1px solid ${T.borderHover}`, borderRadius: 4,
          color: T.text, padding: "4px 10px", cursor: loading ? "wait" : "pointer",
          display: "flex", alignItems: "center", opacity: loading || !input.trim() ? 0.4 : 1,
          transition: "all 180ms ease",
        }}><Send size={12} /></button>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════════

export default function App() {
  const [simulation, setSimulation] = useState(null);
  const [activeRound, setActiveRound] = useState(2);
  const [predicting, setPredicting] = useState(false);
  const [predictResult, setPredictResult] = useState(null);

  // Market data state
  const [marketData, setMarketData] = useState(null);
  const [newsData, setNewsData] = useState({ articles: [], digest: {} });
  const [calendarData, setCalendarData] = useState([]);
  const [consensusData, setConsensusData] = useState([]);
  const [analoguesData, setAnaloguesData] = useState([]);
  const [loading, setLoading] = useState(true);

  // Fetch all market data on mount
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [market, news, calendar, consensus, analogues] = await Promise.all([
          fetch(`${API_BASE}/api/market`).then(r => r.json()),
          fetch(`${API_BASE}/api/news`).then(r => r.json()),
          fetch(`${API_BASE}/api/calendar`).then(r => r.json()),
          fetch(`${API_BASE}/api/consensus`).then(r => r.json()),
          fetch(`${API_BASE}/api/analogues`).then(r => r.json()),
        ]);
        setMarketData(market);
        setNewsData(news);
        setCalendarData(calendar.events || []);
        setConsensusData(consensus.holdings || []);
        setAnaloguesData(analogues.analogues || []);
      } catch (e) {
        console.error("Failed to fetch market data:", e);
      }
      setLoading(false);
    };
    fetchAll();
  }, []);

  // Derive values from market data
  const ohlcv = marketData?.ohlcv || [];
  const CURRENT_PRICE = marketData?.current_price || 0;
  const lastTwo = ohlcv.slice(-2);
  const PRICE_CHANGE = lastTwo.length === 2 ? +(lastTwo[1].close - lastTwo[0].close).toFixed(2) : 0;
  const PRICE_CHANGE_PCT = lastTwo.length === 2 ? +((PRICE_CHANGE / lastTwo[0].close) * 100).toFixed(2) : 0;
  const MACRO = marketData?.macro || {};
  const REGIME = marketData?.regime || "";
  const INDICATORS = marketData?.indicators || {};
  const DIGEST = newsData.digest || {};

  const predict = useCallback(async () => {
    setPredicting(true);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 minutes
      const resp = await fetch("/api/predict", {
        method: "POST",
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      const data = await resp.json();
      if (data.rounds && data.rounds.length === 3) {
        setSimulation(data.rounds);
        setPredictResult(data);
        setActiveRound(2);
      } else {
        console.error("Invalid prediction response:", data);
      }
    } catch (e) {
      console.error("Prediction failed:", e);
    }
    setPredicting(false);
  }, []);

  // Derive consensus
  const consensus = useMemo(() => {
    if (!simulation) return null;
    const r3 = simulation[2].filter(f => f.status === "ok");
    if (!r3.length) return null;
    const bulls = r3.filter(f => f.direction === "bullish").length;
    const bears = r3.filter(f => f.direction === "bearish").length;
    const neutrals = r3.length - bulls - bears;
    const bullPct = Math.round((bulls / r3.length) * 100);
    const bearPct = Math.round((bears / r3.length) * 100);
    const basePct = 100 - bullPct - bearPct;
    const avgConf = r3.reduce((s, f) => s + f.confidence, 0) / r3.length;
    const avgTL = r3.reduce((s, f) => s + f.target_low, 0) / r3.length;
    const avgTH = r3.reduce((s, f) => s + f.target_high, 0) / r3.length;
    const target = (avgTL + avgTH) / 2;
    const conv = Math.round(avgConf * (1 - Math.abs(bulls - bears) / r3.length * 0.3) * 100);
    return { bullPct, basePct, bearPct, avgConf, target, bullTarget: avgTH, bearTarget: avgTL, baseTarget: target, agentCount: r3.length, conviction: conv, credLow: avgTL * 0.99, credHigh: avgTH * 1.01 };
  }, [simulation]);

  const tbColor = PRICE_CHANGE >= 0 ? T.bull : T.bear;
  const sign = PRICE_CHANGE >= 0 ? "+" : "";

  // Loading skeleton while market data fetches
  if (loading) return (
    <div style={{ display: "flex", height: "100vh", background: T.bg0, alignItems: "center", justifyContent: "center" }}>
      <div style={{ color: T.textSec, fontSize: 12, fontFamily: "'DM Sans',sans-serif" }}>Loading market data…</div>
    </div>
  );

  return (
    <div style={{ display: "flex", height: "100vh", background: T.bg0, color: T.text, fontFamily: "'DM Sans',-apple-system,BlinkMacSystemFont,sans-serif", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500;600&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${T.borderHover}; border-radius: 2px; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        .fade-in { animation: fadeIn 350ms ease both; }
        .fade-d1 { animation: fadeIn 350ms ease 80ms both; }
        .fade-d2 { animation: fadeIn 350ms ease 160ms both; }
        .fade-d3 { animation: fadeIn 350ms ease 240ms both; }
        .fade-d4 { animation: fadeIn 350ms ease 320ms both; }
        input::placeholder { color: ${T.textMuted}; }
      `}</style>

      {/* ── SIDEBAR ──────────────────────────────────────── */}
      <aside style={{
        width: 280, minWidth: 280, background: T.bg1, borderRight: `1px solid ${T.border}`,
        overflowY: "auto", padding: "16px 14px", scrollbarWidth: "thin",
        scrollbarColor: `${T.borderHover} transparent`,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <span style={{ fontSize: 17, fontWeight: 700, color: T.text, letterSpacing: "0.01em" }}>Market Intel</span>
          <button style={{ background: "none", border: "none", color: T.textSec, cursor: "pointer", padding: 4, borderRadius: 4, transition: "color 180ms" }}
            onMouseEnter={e => e.currentTarget.style.color = T.text}
            onMouseLeave={e => e.currentTarget.style.color = T.textSec}>
            <RefreshCw size={13} />
          </button>
        </div>
        <MarketPulse price={CURRENT_PRICE} change={PRICE_CHANGE} changePct={PRICE_CHANGE_PCT} macro={MACRO} regime={REGIME} />
        <NewsPanel articles={newsData.articles} />
        <CalendarSection events={calendarData} />
        <IndicatorsPanel indicators={INDICATORS} />
        <ConsensusTable holdings={consensusData} />
        <AnaloguesPanel analogues={analoguesData} />
      </aside>

      {/* ── MAIN ─────────────────────────────────────────── */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Topbar */}
        <div style={{
          background: "linear-gradient(180deg, #141416 0%, #0d0d0f 100%)",
          borderBottom: `1px solid ${T.border}`, padding: "10px 20px",
          display: "flex", alignItems: "center", gap: 14, fontSize: 11, flexShrink: 0,
        }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: T.text }}>3Q<span style={{ color: T.bull }}>View</span></span>
          <span style={{ width: 1, height: 16, background: T.border, opacity: 0.6 }} />
          <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 600, color: T.text }}>{TICKER}</span>
          <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 600, color: tbColor }}>{CURRENT_PRICE.toFixed(2)}</span>
          <span style={{ fontFamily: "'JetBrains Mono',monospace", color: tbColor, fontSize: 10 }}>{sign}{PRICE_CHANGE} ({sign}{PRICE_CHANGE_PCT}%)</span>
          <span style={{ width: 1, height: 16, background: T.border, opacity: 0.6 }} />
          <span style={{ color: T.textSec, letterSpacing: "0.02em" }}>NASDAQ · 1Y daily · Regime: {REGIME.replace(/_/g, " ")}</span>
        </div>

        {/* Content */}
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          {/* Centre column */}
          <div style={{ flex: 3, overflowY: "auto", padding: "20px 20px 40px 20px", scrollbarWidth: "thin", scrollbarColor: `${T.borderHover} transparent` }}>
            {/* Chart */}
            <CandlestickChart data={ohlcv} />
            <VolumeBar data={ohlcv} />

            {/* AI Digest */}
            <div className="fade-in" style={{ background: T.bg3, border: `1px solid ${T.border}`, borderRadius: 6, padding: "14px 16px", margin: "12px 0 8px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: 9, color: T.textSec, textTransform: "uppercase", letterSpacing: "1.2px", fontWeight: 600 }}>AI Market Digest</span>
                <span style={{ fontSize: 8, color: T.textMuted }}>{DIGEST.generated_at ? timeAgo(DIGEST.generated_at) + " ago" : "live"}</span>
              </div>
              <div style={{ fontSize: 11.5, color: T.text, lineHeight: 1.6 }}>{DIGEST.digest || "Market digest loading…"}</div>
              <div style={{ marginTop: 10, display: "flex", gap: 18, flexWrap: "wrap", paddingTop: 8, borderTop: `1px solid ${T.border}` }}>
                <span style={{ fontSize: 9, color: T.bull, fontWeight: 600 }}>● {DIGEST.sentiment || "Neutral"}</span>
                <span style={{ fontSize: 9, color: T.textSec }}>KEY RISK: {DIGEST.key_risk || "—"}</span>
              </div>
            </div>

            {/* Predict button */}
            <button onClick={predict} disabled={predicting} style={{
              width: "100%", padding: "10px 0", background: predicting ? T.bg3 : T.border,
              border: `1px solid ${T.borderHover}`, borderRadius: 6, color: T.text,
              fontWeight: 600, fontSize: 12, letterSpacing: "0.04em", cursor: predicting ? "wait" : "pointer",
              fontFamily: "'DM Sans',sans-serif", transition: "all 180ms ease",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
            }}>
              {predicting ? <><Activity size={14} style={{ animation: "pulse 1s ease infinite" }} /> Running prediction — 3 rounds × 5 agents…</> : <><Zap size={14} /> Predict QQQ Direction</>}
            </button>

            {/* Simulation results */}
            {!simulation && !predicting && (
              <div style={{ textAlign: "center", padding: "32px 16px", color: T.textMuted, fontSize: 11, border: `1px dashed ${T.border}`, borderRadius: 6, marginTop: 8 }}>
                Review the market digest above, then click <b style={{ color: T.textSec }}>Predict QQQ Direction</b>
              </div>
            )}

            {simulation && (
              <div className="fade-in">
                {/* Status */}
                <div style={{ fontSize: 9, color: T.textSec, padding: "6px 0", lineHeight: 1.8 }}>
                  <span style={{ color: T.bull }}>●</span> Simulation complete · {consensus?.agentCount}/5 agents
                </div>

                {/* Consensus */}
                {consensus && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, margin: "12px 0" }}>
                    <div>
                      <SectionHeader badge={consensus.bullPct > 50 ? "BAYESIAN" : null}>Scenario Probabilities</SectionHeader>
                      <ProbBar label="Bull" pct={consensus.bullPct} color={T.bull} />
                      <ProbBar label="Base" pct={consensus.basePct} color={T.textSec} />
                      <ProbBar label="Bear" pct={consensus.bearPct} color={T.bear} />
                      <div style={{ fontSize: 9, color: T.textMuted, marginTop: 4 }}>{consensus.agentCount}/5 agents · avg conf {Math.round(consensus.avgConf * 100)}%</div>
                    </div>
                    <div>
                      <SectionHeader style={{ marginTop: 0 }}>Price Targets (5d)</SectionHeader>
                      {[["Bull", `$${consensus.bullTarget.toFixed(2)}`, T.bull], ["Base", `$${consensus.baseTarget.toFixed(2)}`, T.text], ["Bear", `$${consensus.bearTarget.toFixed(2)}`, T.bear]].map(([l, v, c]) => (
                        <div key={l} style={{ display: "flex", justifyContent: "space-between", fontSize: 10, padding: "4px 0" }}>
                          <span style={{ color: T.textSec }}>{l}</span>
                          <span style={{ fontFamily: "'JetBrains Mono',monospace", color: c, fontWeight: 500 }}>{v}</span>
                        </div>
                      ))}
                    </div>
                    <div>
                      <SectionHeader style={{ marginTop: 0 }}>Consensus</SectionHeader>
                      {(() => {
                        const dp = ((consensus.target - CURRENT_PRICE) / CURRENT_PRICE * 100);
                        const tc = dp >= 0 ? T.bull : T.bear;
                        const ds = dp >= 0 ? "+" : "";
                        const cvColor = consensus.conviction >= 67 ? T.bull : consensus.conviction >= 34 ? T.warn : T.bear;
                        const cvTier = consensus.conviction >= 67 ? "HIGH" : consensus.conviction >= 34 ? "MOD" : "LOW";
                        return <>
                          <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 24, fontWeight: 700, color: tc }}>${consensus.target.toFixed(2)}</div>
                          <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: T.textSec, marginTop: 2 }}>{ds}{dp.toFixed(1)}% vs ${CURRENT_PRICE.toFixed(2)}</div>
                          <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: cvColor, marginTop: 6, fontWeight: 600 }}>{consensus.conviction} <span style={{ fontSize: 9, fontWeight: 400 }}>{cvTier}</span></div>
                          <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: T.text, marginTop: 4 }}>90% CI: ${consensus.credLow.toFixed(2)} – ${consensus.credHigh.toFixed(2)}</div>
                        </>;
                      })()}
                    </div>
                  </div>
                )}

                {/* Regime badge */}
                <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: T.textSec, padding: "7px 10px", background: T.bg1, borderRadius: 4, border: `1px solid ${T.border}`, marginBottom: 4 }}>
                  REGIME: <span style={{ color: T.text }}>{(predictResult?.consensus?.regime_label || REGIME).replace(/_/g, " ").toUpperCase()}</span>
                </div>
                <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 8, color: T.textMuted, marginBottom: 16, letterSpacing: "0.4px" }}>
                  BL Prior → Copula Correction → Regime Weights → Entropy Adjustment → Kelly Sizing
                </div>

                {/* Agent Summary — compact one-liner per agent */}
                <div style={{ margin: "12px 0 16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                    <span style={{ fontSize: 9, color: T.textSec, textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: 600 }}>Agent Summary</span>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 8, color: T.textMuted }}>R3 FINAL</span>
                  </div>
                  {AGENT_PERSONAS.map((a, i) => {
                    const f = simulation[2][i];
                    const sc = f.status === "ok" ? dirColor(f.direction) : T.textMuted;
                    const confPct = f.status === "ok" ? Math.round(f.confidence * 100) : 0;
                    const oneLiner = f.status === "ok" ? f.reasoning.split(". ")[0] : "Unavailable";
                    return (
                      <div key={i} style={{
                        display: "flex", alignItems: "center", gap: 10, padding: "5px 0",
                        borderBottom: `1px solid ${T.border}`, fontSize: 10,
                      }}>
                        <span style={{ width: 100, color: T.textSec, fontSize: 9, flexShrink: 0 }}>{a.name.split(" ")[0]}</span>
                        <span style={{ fontFamily: "'JetBrains Mono',monospace", width: 70, color: sc, fontWeight: 600, flexShrink: 0 }}>
                          {f.status === "ok" ? `${dirSym(f.direction)} ${f.direction.charAt(0).toUpperCase() + f.direction.slice(1)}` : "—"}
                        </span>
                        <span style={{ fontFamily: "'JetBrains Mono',monospace", width: 30, color: T.textSec, flexShrink: 0 }}>{confPct}%</span>
                        <span style={{ color: T.textMuted, fontSize: 9, flex: 1, lineHeight: 1.4 }}>
                          {oneLiner}
                        </span>
                      </div>
                    );
                  })}
                </div>

                {/* Round tabs */}
                <div style={{ display: "flex", gap: 0, marginBottom: 12 }}>
                  {["R1 — Independent", "R2 — Challenge", "R3 — Final"].map((label, idx) => (
                    <button key={idx} onClick={() => setActiveRound(idx)} style={{
                      padding: "6px 14px", fontSize: 10, border: `1px solid ${T.border}`,
                      borderRight: idx < 2 ? "none" : `1px solid ${T.border}`,
                      borderRadius: idx === 0 ? "4px 0 0 4px" : idx === 2 ? "0 4px 4px 0" : 0,
                      background: activeRound === idx ? T.bg3 : "transparent",
                      color: activeRound === idx ? T.text : T.textSec,
                      fontWeight: activeRound === idx ? 600 : 400,
                      cursor: "pointer", fontFamily: "'DM Sans',sans-serif",
                      transition: "all 180ms ease",
                    }}>{label}</button>
                  ))}
                </div>

                {/* Agent cards */}
                <div style={{ display: "flex", gap: 8 }}>
                  {AGENT_PERSONAS.map((a, i) => (
                    <AgentCard key={i} agent={a} forecast={simulation[activeRound][i]} />
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ── RIGHT COLUMN ──────────────────────────────── */}
          <div style={{ width: 300, minWidth: 300, borderLeft: `1px solid ${T.border}`, overflowY: "auto", padding: "44px 16px 20px 16px", scrollbarWidth: "thin", scrollbarColor: `${T.borderHover} transparent` }}>
            <SectionHeader>
              <MessageSquare size={12} /> Ask an Agent
            </SectionHeader>
            <AskAgent simulation={simulation} agents={AGENT_PERSONAS} />
          </div>
        </div>
      </main>
    </div>
  );
}
