"""Dashboard accounts.

``auth_router`` (/api/auth): called by the Next.js server, never a browser.
  POST /login     email + password -> the account (the Next layer signs the session)
  GET  /status    {"active_admins": n}; while it is 0 the shared env login still works
  GET  /me        the signed-in account
  POST /password  change your own password

``router`` (/api/users): admin-only account management (backend.accounts
keeps /api/users off every non-admin role).
"""

from __future__ import annotations

import secrets
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import accounts
from backend.auth import actor_name, require_api_key
from backend.database import get_db
from backend.models import DashboardUser

auth_router = APIRouter(dependencies=[Depends(require_api_key)])
router = APIRouter(dependencies=[Depends(require_api_key)])

# Failed logins per email: N per window. One uvicorn worker, so a dict is enough.
# Emails whose failures have all aged out are dropped once the dict passes
# _FAIL_KEYS_PRUNE, so trying many addresses can't grow it without bound.
_FAIL_LIMIT = 8
_FAIL_WINDOW = 15 * 60.0
_FAIL_KEYS_PRUNE = 1000
_fails: dict[str, deque] = {}

# Failed sign-ins across all emails. Each attempt costs a scrypt hash (~16 MB,
# ~50 ms) on a small box that also serves the public signup form and the
# webhooks, so a burst of failures is cut off before it can starve them.
_GLOBAL_FAIL_LIMIT = 60
_GLOBAL_FAIL_WINDOW = 60.0
_global_fails: deque = deque()

# Field limits: an email can't be longer than 254 characters, and long
# passwords only cost hashing time.
_EMAIL_MAX, _NAME_MAX, _PASSWORD_MAX = 254, 200, 1024

# Unknown and disabled emails are checked against this throwaway hash, so a
# failed login takes the same time whether or not the account exists.
_DUMMY_HASH = accounts.hash_password(secrets.token_urlsafe(24))


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: str
    active: bool
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    last_login_at: Optional[datetime] = None
    session_version: int = 1


class LoginIn(BaseModel):
    email: str = Field(max_length=_EMAIL_MAX)
    password: str = Field(max_length=_PASSWORD_MAX)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=_PASSWORD_MAX)
    new_password: str = Field(max_length=_PASSWORD_MAX)


class UserCreate(BaseModel):
    email: str = Field(max_length=_EMAIL_MAX)
    name: str = Field(max_length=_NAME_MAX)
    role: str
    password: str = Field(max_length=_PASSWORD_MAX)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=_NAME_MAX)
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(None, max_length=_PASSWORD_MAX)


def _prune_fails(now: float) -> None:
    if len(_fails) <= _FAIL_KEYS_PRUNE:
        return
    for email in [e for e, d in _fails.items() if not d or now - d[-1] > _FAIL_WINDOW]:
        del _fails[email]


def _recent_fails(key: str, now: float) -> deque:
    fails = _fails.get(key, deque())
    while fails and now - fails[0] > _FAIL_WINDOW:
        fails.popleft()
    return fails


def _record_fail(key: str, fails: deque, now: float) -> None:
    fails.append(now)
    _fails[key] = fails
    _prune_fails(now)


def _active_admins(db: Session) -> int:
    q = db.query(func.count(DashboardUser.id)).filter(DashboardUser.role == "admin", DashboardUser.active.is_(True))
    return q.scalar() or 0


def _current(request: Request, db: Session) -> DashboardUser:
    user = getattr(request.state, "dashboard_user", None)
    if user is None:
        raise HTTPException(status_code=400, detail="No signed-in account on this request")
    return db.query(DashboardUser).filter(DashboardUser.id == user.id).one()


def _require_admin(request: Request) -> None:
    user = getattr(request.state, "dashboard_user", None)
    if user is not None and user.role != "admin":  # None = service caller / bootstrap login
        raise HTTPException(status_code=403, detail="Admins only")


# -- /api/auth --------------------------------------------------------------

@auth_router.post("/login", response_model=UserOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    email = accounts.normalize_email(payload.email)
    now = time.monotonic()
    while _global_fails and now - _global_fails[0] > _GLOBAL_FAIL_WINDOW:
        _global_fails.popleft()
    if len(_global_fails) >= _GLOBAL_FAIL_LIMIT:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts right now. Try again in a minute.")
    fails = _recent_fails(email, now)
    if len(fails) >= _FAIL_LIMIT:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")
    user = db.query(DashboardUser).filter(DashboardUser.email == email).first()
    password_ok = accounts.verify_password(payload.password, user.password_hash if user is not None else _DUMMY_HASH)
    if user is None or not user.active or not password_ok:
        _record_fail(email, fails, now)
        _global_fails.append(now)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _fails.pop(email, None)
    user.last_login_at = _now()
    db.commit()
    return user


@auth_router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    return {"active_admins": _active_admins(db)}


@auth_router.get("/me", response_model=UserOut)
def me(request: Request, db: Session = Depends(get_db)):
    return _current(request, db)


@auth_router.post("/password")
def change_password(payload: PasswordIn, request: Request, db: Session = Depends(get_db)):
    """Change your own password. Ends every session of this account, this one
    included: the dashboard signs you out and you sign in with the new one."""
    user = _current(request, db)
    key, now = f"password-change:{user.id}", time.monotonic()
    fails = _recent_fails(key, now)
    if len(fails) >= _FAIL_LIMIT:
        raise HTTPException(status_code=429, detail="Too many wrong passwords. Try again in 15 minutes.")
    if not accounts.verify_password(payload.current_password, user.password_hash):
        _record_fail(key, fails, now)
        raise HTTPException(status_code=400, detail="Current password is wrong")
    try:
        accounts.check_password_rules(payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _fails.pop(key, None)
    user.password_hash = accounts.hash_password(payload.new_password)
    user.session_version += 1
    user.updated_at = _now()
    db.commit()
    return {"ok": True, "signed_out": True}


# -- /api/users (admin) -----------------------------------------------------

@router.get("/", response_model=list[UserOut])
def list_users(request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    return db.query(DashboardUser).order_by(DashboardUser.role, DashboardUser.name).all()


@router.post("/", response_model=UserOut)
def create_user(payload: UserCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    email = accounts.normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email")
    if payload.role not in accounts.ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {accounts.ROLES}")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    try:
        accounts.check_password_rules(payload.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if db.query(DashboardUser).filter(DashboardUser.email == email).first():
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    user = DashboardUser(email=email, name=payload.name.strip(), role=payload.role,
                         password_hash=accounts.hash_password(payload.password),
                         created_by=actor_name(request, "shared login"), created_at=_now())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/update", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    user = db.query(DashboardUser).filter(DashboardUser.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    me_id = getattr(getattr(request.state, "dashboard_user", None), "id", None)
    demoting = payload.role is not None and payload.role != "admin" and user.role == "admin"
    disabling = payload.active is False and user.active and user.role == "admin"
    if demoting or disabling:
        # Lock the admin rows first, so two admins demoting or disabling each
        # other at the same moment can't both pass this check and leave none.
        admin_ids = db.query(DashboardUser.id).filter(
            DashboardUser.role == "admin", DashboardUser.active.is_(True)).with_for_update().all()
        if not [r.id for r in admin_ids if r.id != user.id]:
            raise HTTPException(status_code=409, detail="Keep at least one active admin")
    if me_id == user.id and (demoting or payload.active is False):
        raise HTTPException(status_code=409, detail="You can't remove your own admin access")
    if payload.role is not None:
        if payload.role not in accounts.ROLES:
            raise HTTPException(status_code=400, detail=f"role must be one of {accounts.ROLES}")
        user.role = payload.role
    if payload.name is not None and payload.name.strip():
        user.name = payload.name.strip()
    # A password reset or a disable ends the account's existing sessions, so
    # re-enabling it later doesn't bring old cookies back.
    if payload.active is not None:
        if payload.active is False and user.active:
            user.session_version += 1
        user.active = payload.active
    if payload.password:
        try:
            accounts.check_password_rules(payload.password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        user.password_hash = accounts.hash_password(payload.password)
        user.session_version += 1
    user.updated_at = _now()
    db.commit()
    db.refresh(user)
    return user
