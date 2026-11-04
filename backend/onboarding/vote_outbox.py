"""Community Star vote confirmation mail.

The vote row is the outbox: POST /votes queues it in the same transaction, a
BackgroundTask tries it at once, and a daemon thread started with the app picks
up anything due. There is no cron on dev, so nothing here relies on one.

The raw token is never stored. Each send makes a new token, keeps its hash on
the row, and puts the raw value only in the email; a retry rotates again.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import CommunityStarApplication, CommunityStarVote
from backend.onboarding import mailer
from backend.routers.community_star import official_now

log = logging.getLogger(__name__)

TOKEN_HOURS = 48
BACKOFF_MINUTES = (1, 5, 15, 60)   # after the 1st..4th failure; the 5th is final
_LEASE = timedelta(minutes=5)      # a crash mid-send frees the row after this
_MIN_GAP = 0.1                     # 10 mails a second, shared by every sender
_IDLE_SECONDS = 5.0
_ERROR_SECONDS = 30.0
_BATCH = 50

_pace_lock = threading.Lock()
_next_slot = 0.0
_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def confirm_link(token: str) -> str:
    """The token rides in the fragment, so it never reaches a server log."""
    return f"{get_settings().site_base.rstrip('/')}/communitystar/#confirm={token}"


def _pace() -> None:
    global _next_slot
    with _pace_lock:
        now = time.monotonic()
        wait = max(0.0, _next_slot - now)
        _next_slot = max(now, _next_slot) + _MIN_GAP
    if wait:
        time.sleep(wait)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _claim(db: Session, confirm_deadline: datetime, vote_id: Optional[int] = None) -> Optional[tuple]:
    """Take one due row: rotate its token and lease it, so only this sender
    holds it. Returns (id, token hash, email, finalist name, raw token)."""
    now = _utcnow()
    q = db.query(CommunityStarVote).filter(
        CommunityStarVote.status == "pending",
        CommunityStarVote.mail_status == "queued",
        CommunityStarVote.mail_next_at <= now)
    if vote_id is not None:
        q = q.filter(CommunityStarVote.id == vote_id)
    vote = q.order_by(CommunityStarVote.mail_next_at, CommunityStarVote.id).with_for_update(skip_locked=True).first()
    if vote is None:
        return None
    official = official_now(db)
    if official >= confirm_deadline:
        vote.mail_status = "failed"
        vote.mail_last_error = "voting closed before this could be sent"
        db.commit()
        return ()
    token = secrets.token_urlsafe(32)
    vote.token_hash = hash_token(token)
    vote.token_expires = official + timedelta(hours=TOKEN_HOURS)
    vote.mail_attempts += 1
    vote.mail_next_at = now + _LEASE
    vote.last_sent_at = now
    finalist = db.get(CommunityStarApplication, vote.finalist_id)
    name = (finalist.card_name or finalist.full_name) if finalist else "your finalist"
    claimed = (vote.id, vote.token_hash, vote.email, name, token)
    db.commit()
    return claimed


def _finish(db: Session, vote_id: int, token_hash: str, ok: bool) -> None:
    vote = db.query(CommunityStarVote).filter(CommunityStarVote.id == vote_id).with_for_update().first()
    # A resend while this mail was going out rotated the row: that send owns it now.
    if vote is None or vote.token_hash != token_hash or vote.mail_status != "queued":
        db.rollback()
        return
    if ok:
        vote.mail_status = "sent"
        vote.sends += 1
        vote.mail_next_at = None
        vote.mail_last_error = None
    elif vote.mail_attempts > len(BACKOFF_MINUTES):
        vote.mail_status = "failed"
        vote.mail_next_at = None
        vote.mail_last_error = "send failed"
    else:
        vote.mail_next_at = _utcnow() + timedelta(minutes=BACKOFF_MINUTES[vote.mail_attempts - 1])
        vote.mail_last_error = "send failed"
    db.commit()


def _send_claimed(db: Session, claimed: tuple) -> None:
    vote_id, token_hash, to, name, token = claimed
    _pace()
    try:
        ok = mailer.send_community_star_vote_confirm(to, name, confirm_link(token))
    except Exception:  # noqa: BLE001 - one bad send must not stop the queue
        log.exception("community star vote mail failed id=%s", vote_id)
        ok = False
    _finish(db, vote_id, token_hash, ok)


def send_one(vote_id: int, confirm_deadline: datetime) -> None:
    """Background task after a vote post: try this row now."""
    db = SessionLocal()
    try:
        claimed = _claim(db, confirm_deadline, vote_id)
        if claimed:
            _send_claimed(db, claimed)
    except Exception:  # noqa: BLE001 - the thread retries anything left queued
        log.exception("community star vote mail: immediate send failed id=%s", vote_id)
    finally:
        db.close()


def drain(db: Session, confirm_deadline: datetime, limit: int = _BATCH) -> int:
    """Send up to ``limit`` due rows. Returns how many rows were taken."""
    taken = 0
    while taken < limit:
        claimed = _claim(db, confirm_deadline)
        if claimed is None:
            break
        taken += 1
        if claimed:
            _send_claimed(db, claimed)
    return taken


def _run() -> None:
    from backend.routers import community_star_voting as voting

    while not _stop.is_set():
        db = SessionLocal()
        pause = _IDLE_SECONDS
        try:
            voting.ensure_frozen(db)
            if drain(db, voting.confirm_deadline(voting.get_program(db))) >= _BATCH:
                pause = 0.0
        except Exception:  # noqa: BLE001 - keep the thread alive through a database blip
            log.exception("community star vote outbox tick failed")
            pause = _ERROR_SECONDS
        finally:
            db.close()
        _stop.wait(pause)


def start() -> None:
    """Start the outbox thread. Never under tests: they drive drain() directly."""
    global _thread
    if "pytest" in sys.modules or (_thread is not None and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name="community-star-vote-outbox", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
