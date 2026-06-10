import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Database
DATABASE_URL = os.getenv("DATABASE_URL", str(BASE_DIR / "trading.db"))

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-to-a-secure-random-key-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Encryption key for MT5 credentials
CREDENTIAL_ENCRYPTION_KEY = os.getenv(
    "CREDENTIAL_ENCRYPTION_KEY",
    "change-this-to-a-32-byte-key-in-prod!"
)

# Trading settings
DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD"]
RISK_PER_TRADE_PERCENT = 1.0
ATR_SL_MULTIPLIER = 1.2      # balanced SL — wide enough to avoid noise wicks
ATR_TP_MULTIPLIER = 2.0      # faster TP (1:2 R:R)
TP_RR_CAP = None             # cap TP at this R:R (None = target next key level). Backtest: uncapped TPs avg ~7:1 and kill win rate.
MAX_OPEN_TRADES = 2
TRADING_LOOP_INTERVAL_SECONDS = 3  # faster scan for scalping
DAILY_LOSS_LIMIT = 5  # stop opening new trades after N losing trades in a day (UTC)

# Timeframes
D1_CANDLE_COUNT = 120    # D1 daily bias (needs 50+ for EMA50)
H4_CANDLE_COUNT = 120    # H4 daily bias confirmation
H1_CANDLE_COUNT = 100    # H1 key levels + bias
M15_CANDLE_COUNT = 100   # M15 trend + approach
M5_CANDLE_COUNT = 100    # M5 sweep + entry

# Daily Bias (Layer 0)
DAILY_BIAS_CACHE_SECONDS = 900   # recompute D1/H4 bias at most every 15 min
DAILY_BIAS_THRESHOLD = 2         # |score| >= 2 of 4 factors required for a directional bias

# Limit-order entry (at Order Block 50%)
PENDING_ORDER_EXPIRY_MINUTES = 15  # cancel unfilled limit orders after N min (~3 M5 candles)

# Session Filter (UTC hours)
SESSION_FILTER_ENABLED = False  # deactivated per user — bot trades all hours
LONDON_SESSION_START = 7   # 07:00 UTC
LONDON_SESSION_END = 16    # 16:00 UTC
NY_SESSION_START = 12      # 12:00 UTC
NY_SESSION_END = 21        # 21:00 UTC

# Spread Filter (in points — XAUUSD 1 point = $0.01)
MAX_SPREAD_POINTS = 400  # max acceptable spread (Exness XAUUSD uses 3 digits, 1 point = $0.001)

# WebSocket
WS_HEARTBEAT_INTERVAL = 5

# Logging
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
