import logging
from typing import Optional
from cryptography.fernet import Fernet
import base64
import hashlib

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

from pydantic import BaseModel

from config import CREDENTIAL_ENCRYPTION_KEY
from database.db import get_db

logger = logging.getLogger("mt5.connector")

_MT5_UNAVAILABLE_MSG = "MetaTrader 5 is not available on this server. Please run MT5 on your Windows PC."


def _get_fernet() -> Fernet:
    key = hashlib.sha256(CREDENTIAL_ENCRYPTION_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_password(password: str) -> str:
    f = _get_fernet()
    return f.encrypt(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()


class MT5Credentials(BaseModel):
    server: str
    login: str
    password: str


class MT5ConnectionStatus(BaseModel):
    connected: bool
    server: Optional[str] = None
    login: Optional[int] = None
    balance: Optional[float] = None
    equity: Optional[float] = None
    margin: Optional[float] = None
    free_margin: Optional[float] = None
    profit: Optional[float] = None
    leverage: Optional[int] = None
    currency: Optional[str] = None
    name: Optional[str] = None
    error: Optional[str] = None


_active_connections: dict[int, bool] = {}


def save_mt5_credentials(user_id: int, creds: MT5Credentials):
    encrypted_pw = encrypt_password(creds.password)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM mt5_credentials WHERE user_id = ?", (user_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE mt5_credentials 
                   SET server = ?, login = ?, password_encrypted = ?, updated_at = CURRENT_TIMESTAMP 
                   WHERE user_id = ?""",
                (creds.server, creds.login, encrypted_pw, user_id)
            )
        else:
            conn.execute(
                """INSERT INTO mt5_credentials (user_id, server, login, password_encrypted) 
                   VALUES (?, ?, ?, ?)""",
                (user_id, creds.server, creds.login, encrypted_pw)
            )


def get_mt5_credentials(user_id: int) -> Optional[MT5Credentials]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT server, login, password_encrypted FROM mt5_credentials WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if not row:
            return None
        return MT5Credentials(
            server=row["server"],
            login=row["login"],
            password=decrypt_password(row["password_encrypted"])
        )


def connect_mt5(user_id: int, creds: MT5Credentials) -> MT5ConnectionStatus:
    if mt5 is None:
        logger.warning(_MT5_UNAVAILABLE_MSG)
        return MT5ConnectionStatus(connected=False, error=_MT5_UNAVAILABLE_MSG)
    try:
        # Check if MT5 module can access the terminal
        try:
            init_result = mt5.initialize()
        except Exception as init_err:
            logger.error(f"MT5 initialize() threw exception: {init_err}")
            return MT5ConnectionStatus(
                connected=False,
                error="MT5 terminal not found. Make sure MetaTrader 5 is installed and running."
            )

        if not init_result:
            err = mt5.last_error()
            return MT5ConnectionStatus(
                connected=False,
                error=f"MT5 initialization failed: {err}. Make sure MT5 terminal is open."
            )

        authorized = mt5.login(
            login=int(creds.login),
            password=creds.password,
            server=creds.server
        )

        if not authorized:
            error = mt5.last_error()
            mt5.shutdown()
            return MT5ConnectionStatus(connected=False, error=f"MT5 login failed: {error}")

        account_info = mt5.account_info()
        if account_info is None:
            mt5.shutdown()
            return MT5ConnectionStatus(connected=False, error="Failed to get account info")

        save_mt5_credentials(user_id, creds)
        _active_connections[user_id] = True

        logger.info(f"MT5 connected for user {user_id}: {account_info.login} @ {account_info.server}")

        return MT5ConnectionStatus(
            connected=True,
            server=account_info.server,
            login=account_info.login,
            balance=account_info.balance,
            equity=account_info.equity,
            margin=account_info.margin,
            free_margin=account_info.margin_free,
            profit=account_info.profit,
            leverage=account_info.leverage,
            currency=account_info.currency,
            name=account_info.name
        )

    except Exception as e:
        logger.error(f"MT5 connection error: {e}")
        return MT5ConnectionStatus(connected=False, error=str(e))


def disconnect_mt5(user_id: int):
    _active_connections.pop(user_id, None)
    if mt5 is not None:
        mt5.shutdown()
    logger.info(f"MT5 disconnected for user {user_id}")


def is_connected(user_id: int) -> bool:
    if mt5 is None:
        return False
    if user_id not in _active_connections:
        return False
    info = mt5.account_info()
    if info is None:
        _active_connections.pop(user_id, None)
        return False
    return True


def get_account_info() -> Optional[dict]:
    if mt5 is None:
        return None
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "login": int(info.login),
        "server": info.server,
        "balance": float(info.balance),
        "equity": float(info.equity),
        "margin": float(info.margin),
        "free_margin": float(info.margin_free),
        "profit": float(info.profit),
        "leverage": int(info.leverage),
        "currency": info.currency,
        "name": info.name,
    }


def reconnect_mt5(user_id: int) -> MT5ConnectionStatus:
    if mt5 is None:
        return MT5ConnectionStatus(connected=False, error=_MT5_UNAVAILABLE_MSG)
    creds = get_mt5_credentials(user_id)
    if not creds:
        return MT5ConnectionStatus(connected=False, error="No saved credentials found")
    mt5.shutdown()
    return connect_mt5(user_id, creds)
