#!/usr/bin/env python3
"""
PC Bridge for MT5 Trading Bot
Run this on your Windows PC where MetaTrader 5 is installed.
It polls the VPS for trading state and runs the local strategy when enabled.
"""
import sys
import os
import asyncio
import logging
import time

# Add backend to path so we can import the strategy modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)

# Use urllib instead of requests to avoid extra dependency
try:
    import urllib.request
    import urllib.error
    import json
except ImportError:
    print("ERROR: Python standard library missing. This should not happen.")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("pc_bridge")

# ---------------------------------------------------------------------------
# CONFIGURATION — change these to match your setup
# ---------------------------------------------------------------------------
VPS_URL = "https://api.algotradeai.net"
USERNAME = "garad"               # your login username
PASSWORD = "Pr0tect8850"         # your login password
POLL_INTERVAL = 5                # seconds between polls
HEARTBEAT_INTERVAL = 30          # seconds between heartbeats

# ---------------------------------------------------------------------------


class VPSClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token = None
        self.user_id = None

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            text = e.read().decode()
            logger.warning(f"HTTP {e.code} on {path}: {text}")
            return {"error": text}
        except Exception as e:
            logger.warning(f"Request failed for {path}: {e}")
            return {"error": str(e)}

    def login(self) -> bool:
        resp = self._request("POST", "/api/auth/login", {
            "username": USERNAME,
            "password": PASSWORD,
        })
        if "access_token" in resp:
            self.token = resp["access_token"]
            # Decode user_id from token payload (no signature verification needed)
            import base64
            payload_b64 = self.token.split(".")[1]
            # Add padding if needed
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.b64decode(payload_b64).decode())
            self.user_id = int(payload.get("sub", 0))
            logger.info(f"Logged in as {USERNAME} (user_id={self.user_id})")
            return True
        logger.error(f"Login failed: {resp.get('detail', resp)}")
        return False

    def poll(self) -> dict:
        return self._request("GET", "/api/bridge/poll")

    def heartbeat(self) -> dict:
        return self._request("POST", "/api/bridge/heartbeat", {"pc_version": "1.0.0"})

    def log_trade(self, **kwargs) -> dict:
        return self._request("POST", "/api/bridge/trade-log", kwargs)

    def update_account(self, **kwargs) -> dict:
        return self._request("POST", "/api/bridge/account", kwargs)


class BridgeRunner:
    def __init__(self):
        self.vps = VPSClient(VPS_URL)
        self._running = False
        self._trade_task = None

    async def run(self):
        if not self.vps.login():
            logger.error("Cannot start bridge: login failed")
            return

        logger.info("PC Bridge started. Waiting for VPS trading signals...")
        self._running = True
        last_heartbeat = 0
        last_account_update = 0

        # Lazy-import strategy modules only when needed
        from strategies.trading_loop import start_trading, stop_trading, is_trading_active, trading_loop
        from mt5.connector import is_connected as mt5_is_connected, get_account_info
        from mt5.data_streamer import get_open_positions

        while self._running:
            try:
                # Heartbeat
                now = time.time()
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    self.vps.heartbeat()
                    last_heartbeat = now

                # Poll VPS for trading state
                state = self.vps.poll()
                if "error" in state:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                should_trade = state.get("trading_enabled", False)
                symbols = state.get("symbols", ["XAUUSD"])
                manual_lot = state.get("manual_lot")
                user_id = self.vps.user_id

                currently_trading = is_trading_active(user_id)

                if should_trade and not currently_trading:
                    # Ensure MT5 is connected before starting
                    if not mt5_is_connected(user_id):
                        logger.warning("MT5 not connected locally — cannot start trading")
                    else:
                        logger.info(f"Starting local trading on {symbols}")
                        start_trading(user_id, symbols, manual_lot=manual_lot)
                        self._trade_task = asyncio.create_task(trading_loop(user_id))

                elif not should_trade and currently_trading:
                    logger.info("Stopping local trading (VPS requested stop)")
                    stop_trading(user_id)
                    if self._trade_task:
                        self._trade_task.cancel()
                        try:
                            await self._trade_task
                        except asyncio.CancelledError:
                            pass
                        self._trade_task = None

                # Send account snapshot to VPS periodically
                if should_trade and now - last_account_update > 10:
                    account = get_account_info()
                    if account:
                        self.vps.update_account(
                            balance=account.get("balance", 0),
                            equity=account.get("equity", 0),
                            margin=account.get("margin", 0),
                            free_margin=account.get("margin_free", 0),
                            profit=account.get("profit", 0),
                        )
                    last_account_update = now

            except Exception as e:
                logger.error(f"Bridge loop error: {e}")

            await asyncio.sleep(POLL_INTERVAL)

        # Cleanup
        if self._trade_task:
            logger.info("Cancelling local trading task...")
            self._trade_task.cancel()
            try:
                await self._trade_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    runner = BridgeRunner()
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        logger.info("Bridge stopped by user")
        runner._running = False
