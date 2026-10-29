"""Create or reset a dashboard account from the server shell.

The Users page in the dashboard is the normal way to manage accounts. This
is the fallback for the first admin and for lockouts.

    python -m scripts.dashboard_user create --email you@niltv.com --name "Your Name" --role admin
    python -m scripts.dashboard_user reset  --email you@niltv.com
    python -m scripts.dashboard_user list

The password is prompted for (never passed on the command line).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone

from backend import accounts
from backend.database import SessionLocal
from backend.models import DashboardUser


def _password() -> str:
    pw = getpass.getpass("New password: ")
    if pw != getpass.getpass("Repeat: "):
        sys.exit("Passwords do not match")
    try:
        accounts.check_password_rules(pw)
    except ValueError as e:
        sys.exit(str(e))
    return pw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("create", "reset", "list"))
    ap.add_argument("--email")
    ap.add_argument("--name")
    ap.add_argument("--role", choices=accounts.ROLES, default="admin")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.action == "list":
            for u in db.query(DashboardUser).order_by(DashboardUser.role, DashboardUser.email):
                print(f"{u.id:>4}  {u.role:<8} {'active' if u.active else 'DISABLED':<9} {u.email}  ({u.name})")
            return
        if not args.email:
            sys.exit("--email is required")
        email = accounts.normalize_email(args.email)
        user = db.query(DashboardUser).filter(DashboardUser.email == email).first()
        now = datetime.now(tz=timezone.utc)
        if args.action == "create":
            if user:
                sys.exit(f"{email} already exists; use reset")
            if not args.name:
                sys.exit("--name is required")
            db.add(DashboardUser(email=email, name=args.name, role=args.role,
                                 password_hash=accounts.hash_password(_password()),
                                 created_by="server shell", created_at=now))
            print(f"Created {args.role} account {email}")
        else:
            if not user:
                sys.exit(f"No account {email}")
            user.password_hash = accounts.hash_password(_password())
            user.active = True
            user.updated_at = now
            print(f"Password reset and account enabled: {email}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
