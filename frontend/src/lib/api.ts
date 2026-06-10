const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export interface User {
  id: number;
  username: string;
  email: string;
  role: string;
}

// --- Auth ---
export const authApi = {
  register: (data: { username: string; email: string; password: string }) =>
    request<User>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  login: (data: { username: string; password: string }) =>
    request<{ access_token: string; token_type: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  me: () => request<User>("/api/auth/me"),
};

// --- Admin ---
export const adminApi = {
  listUsers: () => request<User[]>("/api/admin/users"),
  createUser: (data: { username: string; email: string; password: string; role?: string }) =>
    request<User>("/api/admin/users", { method: "POST", body: JSON.stringify(data) }),
  updateUser: (id: number, data: Partial<Omit<User, "id">>) =>
    request<User>(`/api/admin/users/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteUser: (id: number) =>
    request<{ message: string }>(`/api/admin/users/${id}`, { method: "DELETE" }),
};

// --- MT5 ---
export const mt5Api = {
  connect: (data: { server: string; login: string; password: string }) =>
    request<MT5Status>("/api/mt5/connect", { method: "POST", body: JSON.stringify(data) }),
  disconnect: () => request("/api/mt5/disconnect", { method: "POST" }),
  status: () => request<MT5StatusResponse>("/api/mt5/status"),
  reconnect: () => request<MT5Status>("/api/mt5/reconnect", { method: "POST" }),
};

// --- Market ---
export const marketApi = {
  tick: (symbol = "XAUUSD") => request<TickData>(`/api/market/tick?symbol=${symbol}`),
  candles: (symbol = "XAUUSD", timeframe = "H1", count = 100) =>
    request<CandleData[]>(`/api/market/candles?symbol=${symbol}&timeframe=${timeframe}&count=${count}`),
  symbolInfo: (symbol = "XAUUSD") => request(`/api/market/symbol-info?symbol=${symbol}`),
  positions: (symbol?: string) =>
    request<Position[]>(`/api/market/positions${symbol ? `?symbol=${symbol}` : ""}`),
  history: (days = 30) => request<TradeHistoryItem[]>(`/api/market/history?days=${days}`),
};

// --- AI ---
export const aiApi = {
  trend: (symbol = "XAUUSD") => request<TrendData>(`/api/ai/trend?symbol=${symbol}`),
  decision: (symbol = "XAUUSD") => request<DecisionData>(`/api/ai/decision?symbol=${symbol}`),
  zones: (symbol = "XAUUSD", direction = "BULLISH") =>
    request<ZoneData>(`/api/ai/zones?symbol=${symbol}&direction=${direction}`),
  signal: (symbol = "XAUUSD") => request<SignalData>(`/api/ai/signal?symbol=${symbol}`),
  dailyBias: (symbol = "XAUUSD") => request<DailyBiasData>(`/api/ai/daily-bias?symbol=${symbol}`),
};

// --- Trading ---
export const tradingApi = {
  start: (symbols: string[] = ["XAUUSD"], manualLot?: number | null) =>
    request("/api/trading/start", { method: "POST", body: JSON.stringify({ symbols, manual_lot: manualLot ?? null }) }),
  stop: () => request("/api/trading/stop", { method: "POST" }),
  status: () => request<{ active: boolean; connected: boolean }>("/api/trading/status"),
};

// --- News ---
export const newsApi = {
  status: () => request<NewsStatus>("/api/news/status"),
  calendar: (hours = 24) => request<NewsEvent[]>(`/api/news/calendar?hours=${hours}`),
};

// --- Analytics ---
export const analyticsApi = {
  performance: () => request<PerformanceData>("/api/analytics/performance"),
  backtest: () => request<BacktestData>("/api/analytics/backtest"),
  tradeLogs: (limit = 50) => request<TradeLog[]>(`/api/analytics/trade-logs?limit=${limit}`),
  clearTradeLogs: () => request("/api/analytics/trade-logs", { method: "DELETE" }),
  clearPerformance: () => request("/api/analytics/performance", { method: "DELETE" }),
  aiDecisions: (limit = 50) => request<AIDecisionLog[]>(`/api/analytics/ai-decisions?limit=${limit}`),
  errors: (limit = 50) => request(`/api/analytics/errors?limit=${limit}`),
  dailyProfits: () => request<DailyProfit[]>("/api/analytics/daily-profits"),
  fillStats: () => request<FillStatsData>("/api/analytics/fill-stats"),
};

// --- Types ---
export interface MT5Status {
  connected: boolean;
  server?: string;
  login?: number;
  balance?: number;
  equity?: number;
  margin?: number;
  free_margin?: number;
  profit?: number;
  leverage?: number;
  currency?: string;
  name?: string;
  error?: string;
}

export interface MT5StatusResponse {
  connected: boolean;
  account: AccountInfo | null;
  trading_active: boolean;
  losses_today?: number;
  daily_loss_limit?: number;
  halted?: boolean;
}

export interface AccountInfo {
  login: number;
  server: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  profit: number;
  leverage: number;
  currency: string;
  name: string;
}

export interface TickData {
  symbol: string;
  bid: number;
  ask: number;
  last: number;
  volume: number;
  time: string;
  spread: number;
}

export interface CandleData {
  datetime: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  spread: number;
}

export interface Position {
  ticket: number;
  symbol: string;
  type: string;
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  swap: number;
  time: string;
  magic: number;
  comment: string;
}

export interface TrendData {
  bias: string;
  ema8: number;
  ema21: number;
  strength: number;
  rsi: number;
  adx: number;
  market_structure: string;
  price_vs_ema21: string;
  reasons: string[];
}

export interface DecisionData {
  decision: string;
  confidence: number;
  reasons: string[];
  indicators: Record<string, number>;
}

export interface ZoneData {
  valid: boolean;
  zone_count: number;
  active_zone: {
    zone_type: string;
    direction: string;
    high: number;
    low: number;
    active: boolean;
  } | null;
  zones: Array<{
    zone_type: string;
    direction: string;
    high: number;
    low: number;
    active: boolean;
  }>;
}

export interface ICTSetup {
  direction: string;
  confirmation: string;
  entry_price: number;
  ob_high: number;
  ob_low: number;
  ob_mid: number;
  sl_price: number;
  tp_price: number;
}

export interface ICTResult {
  valid: boolean;
  reason: string;
  setup: ICTSetup | null;
}

export interface SignalData {
  action: string;
  symbol: string;
  entry_price: number;
  reason: string;
  ict: ICTResult | null;
  daily_bias?: string;
  trade_type?: string;
  order_kind?: string;
  state?: string;
  // Legacy fields (kept for compatibility)
  trend?: TrendData;
  decision?: DecisionData;
  zones?: ZoneData;
}

export interface DailyBiasData {
  bias: string;
  score: number;
  current_price: number;
  d1_ema20: number;
  d1_ema50: number;
  h4_ema20: number;
  h4_ema50: number;
  weekly_open: number;
  reasons: string[];
}

export interface PerformanceData {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  total_profit: number;
  max_drawdown: number;
  win_rate: number;
}

export interface BacktestData {
  available: boolean;
  strategy?: string;
  trades?: number;
  win_rate?: number;
  total_r?: number;
  expectancy?: number;
  profit_factor?: number;
  avg_win?: number;
  avg_loss?: number;
  max_drawdown_r?: number;
}

export interface TradeLog {
  id: number;
  symbol: string;
  action: string;
  lot_size: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  ticket: number;
  status: string;
  profit: number;
  h1_bias: string;
  ai_decision: string;
  m5_zone: string;
  opened_at: string;
  closed_at: string | null;
}

export interface AIDecisionLog {
  id: number;
  symbol: string;
  h1_bias: string;
  ai_decision: string;
  m5_zone_valid: number;
  rsi: number;
  macd_line: number;
  macd_signal: number;
  atr: number;
  ema8: number;
  ema21: number;
  confidence: number;
  created_at: string;
}

export interface TradeHistoryItem {
  ticket: number;
  order: number;
  symbol: string;
  type: number;
  volume: number;
  price: number;
  profit: number;
  swap: number;
  commission: number;
  time: string;
  comment: string;
}

export interface DailyProfit {
  date: string;
  total_profit: number;
  trade_count: number;
}

export interface FillStatsData {
  placed: number;
  filled: number;
  cancelled: number;
  pending: number;
  failed: number;
  fill_rate: number;
}

export interface NewsEvent {
  title: string;
  country: string;
  time_utc: string;
  minutes_away: number;
  impact: string;
  forecast: string;
  previous: string;
}

export interface NewsStatus {
  blocked: boolean;
  reason: string;
  upcoming_events: NewsEvent[];
}
