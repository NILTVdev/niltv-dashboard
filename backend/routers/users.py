"""Dashboard accounts: login and user management (migration 029).

* ``auth_router`` (/api/auth) - X-API-Key only. The Next.js login route posts
  the username/password here and stores the returned session token in the
  auth_token cookie; ``/me`` reads the session back.
* ``router`` (/api/users) - admin role. List, add, change role, reset
  password, remove.

Mutations are POST, like the rest of the API.
"""

from __future__ import annotations

import re
import time
from collections import deque
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import (
    ROLES, SESSION_TTL, check_password_timing_safe, current_user, hash_password,
    make_session_token, require_api_key, require_role,
)
from backend.database import get_db
from backend.models import DashboardUser

auth_router = APIRouter(dependencies=[Depends(require_api_key)])
router = APIRouter(dependencies=[Depends(require_api_key), Depends(require_role("admin"))])

USERNAME_RE = re.compile(r"^[a-z0-9._@-]{2,64}$")
MIN_PASSWORD = 10

# Failed logins per username. Login calls all arrive from the Next.js server,
# so the client IP is not useful here; the username is. One uvicorn worker,
# so an in-process dict is enough.
_FAIL_LIMIT = 10
_FAIL_WINDOW = 900.0
_failures: dict[str, deque] = {}


def _locked_out(username: str, now: float) -> bool:
    q = _failures.setdefault(username, deque())
    while q and now - q[0] > _FAIL_WINDOW:
        q.popleft()
    return len(q) >= _FAIL_LIMIT


def normalize_username(raw: str) -> str:
    return (raw or "").strip().lower()


def validate_new_user(username: str, password: str, role: str) -> None:
    if not USERNAME_RE.match(username):
        raise ValueError("Username must be 2-64 characters: letters, digits, . _ @ -")
    validate_password(password)
    validate_role(role)


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")


def validate_role(role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}")


# -- Login ------------------------------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int]
    username: str
    role: str
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


@auth_router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    username = normalize_username(payload.username)
    now = time.time()
    if _locked_out(username, now):
        raise HTTPException(status_code=429, detail="Too many failed sign-ins, try again later")
    user = db.query(DashboardUser).filter(DashboardUser.username == username).first()
    if not check_password_timing_safe(payload.password, user.password_hash if user else None):
        _failures[username].append(now)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _failures.pop(username, None)
    user.last_login_at = func.now()
    db.commit()
    db.refresh(user)
    return {"token": make_session_token(user), "max_age": SESSION_TTL,
            "user": UserOut.model_validate(user).model_dump(mode="json")}


@auth_router.get("/me", response_model=UserOut)
def me(user=Depends(current_user)):
    return user


# -- User management (admin) -------------------------------------------------

class UserCreate(BaseModel):
    username: str
    password: str
    role: str


class UserUpdate(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = None


def _get(db: Session, user_id: int) -> DashboardUser:
    user = db.get(DashboardUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _admin_count(db: Session) -> int:
    return db.query(DashboardUser).filter(DashboardUser.role == "admin").count()


# No trailing slash: the dashboard proxy calls /api/users as-is.
@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(DashboardUser).order_by(DashboardUser.username).all()


@router.post("", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    username = normalize_username(payload.username)
    try:
        validate_new_user(username, payload.password, payload.role)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if db.query(DashboardUser).filter(DashboardUser.username == username).first():
        raise HTTPException(status_code=409, detail=f"User {username} already exists")
    user = DashboardUser(username=username, password_hash=hash_password(payload.password),
                         role=payload.role, session_version=1)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/update", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    user = _get(db, user_id)
    try:
        if payload.role is not None:
            validate_role(payload.role)
        if payload.password is not None:
            validate_password(payload.password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    changed = False
    if payload.role is not None and payload.role != user.role:
        if user.role == "admin" and _admin_count(db) <= 1:
            raise HTTPException(status_code=409, detail="Cannot demote the last admin")
        user.role = payload.role
        changed = True
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        changed = True
    if changed:
        # Old tokens carry the old role / predate the reset: sign them out.
        user.session_version += 1
        db.commit()
        db.refresh(user)
    return user


@router.post("/{user_id}/delete")
def delete_user(user_id: int, db: Session = Depends(get_db), actor=Depends(current_user)):
    user = _get(db, user_id)
    if actor.id is not None and actor.id == user.id:
        raise HTTPException(status_code=409, detail="You cannot remove your own account")
    if user.role == "admin" and _admin_count(db) <= 1:
        raise HTTPException(status_code=409, detail="Cannot remove the last admin")
    db.delete(user)
    db.commit()
    return {"status": "ok", "id": user_id}
