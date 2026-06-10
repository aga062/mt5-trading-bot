from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr

from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from database.db import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role: str = "user"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    with get_db() as conn:
        row = conn.execute("SELECT id, username, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise credentials_exception
        return {"id": row["id"], "username": row["username"], "email": row["email"], "role": row["role"]}


def get_current_admin(token: str = Depends(oauth2_scheme)) -> dict:
    user = get_current_user(token)
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def register_user(data: UserRegister) -> UserOut:
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (data.username, data.email)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Username or email already exists")

        pw_hash = hash_password(data.password)
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (data.username, data.email, pw_hash)
        )
        user_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO performance_metrics (user_id) VALUES (?)",
            (user_id,)
        )

        return UserOut(id=user_id, username=data.username, email=data.email)


def login_user(data: UserLogin) -> Token:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (data.username,)
        ).fetchone()
        if not row or not verify_password(data.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_access_token(data={"sub": row["id"]})
        return Token(access_token=token, token_type="bearer")


# ── Admin CRUD ─────────────────────────────────────────────────────────────

class AdminUserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "user"


class AdminUserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None


def admin_create_user(data: AdminUserCreate) -> UserOut:
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (data.username, data.email)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Username or email already exists")

        pw_hash = hash_password(data.password)
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (data.username, data.email, pw_hash, data.role)
        )
        user_id = cursor.lastrowid
        conn.execute("INSERT INTO performance_metrics (user_id) VALUES (?)", (user_id,))
        return UserOut(id=user_id, username=data.username, email=data.email, role=data.role)


def admin_list_users() -> list[UserOut]:
    with get_db() as conn:
        rows = conn.execute("SELECT id, username, email, role FROM users ORDER BY created_at DESC").fetchall()
        return [UserOut(id=r["id"], username=r["username"], email=r["email"], role=r["role"]) for r in rows]


def admin_update_user(user_id: int, data: AdminUserUpdate) -> UserOut:
    with get_db() as conn:
        row = conn.execute("SELECT id, username, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        updates = []
        params = []
        if data.username is not None:
            updates.append("username = ?")
            params.append(data.username)
        if data.email is not None:
            updates.append("email = ?")
            params.append(data.email)
        if data.password is not None:
            updates.append("password_hash = ?")
            params.append(hash_password(data.password))
        if data.role is not None:
            updates.append("role = ?")
            params.append(data.role)

        if updates:
            params.append(user_id)
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)

        row = conn.execute("SELECT id, username, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
        return UserOut(id=row["id"], username=row["username"], email=row["email"], role=row["role"])


def admin_delete_user(user_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return {"message": "User deleted"}
