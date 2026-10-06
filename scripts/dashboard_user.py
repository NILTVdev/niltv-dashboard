"""
Manage dashboard accounts from the command line (migration 029). The admin
page does the same once an admin exists; this is how the first one is made.

  python -m scripts.dashboard_user add tom --role admin      # prompts for the password
  python -m scripts.dashboard_user set-role jane onboarding
  python -m scripts.dashboard_user set-password jane         # prompts; signs jane out
  python -m scripts.dashboard_user remove jane
  python -m scripts.dashboard_user list

Roles: viewer (data screens), onboarding (+ onboarding workflow), admin (everything).
Pass --password-stdin to read the password from stdin instead of a prompt.
"""

import argparse
import getpass
import sys

from backend.auth import ROLES, hash_password
from backend.database import SessionLocal
from backend.models import DashboardUser
from backend.routers.users import normalize_username, validate_new_user, validate_password


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        sys.exit("Passwords do not match")
    return first


def _find(db, username: str) -> DashboardUser:
    user = db.query(DashboardUser).filter(DashboardUser.username == username).first()
    if user is None:
        sys.exit(f"No user named {username}")
    return user


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("username")
    add.add_argument("--role", choices=ROLES, required=True)
    add.add_argument("--password-stdin", action="store_true")
    role = sub.add_parser("set-role")
    role.add_argument("username")
    role.add_argument("role", choices=ROLES)
    pw = sub.add_parser("set-password")
    pw.add_argument("username")
    pw.add_argument("--password-stdin", action="store_true")
    rm = sub.add_parser("remove")
    rm.add_argument("username")
    sub.add_parser("list")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.cmd == "list":
            for u in db.query(DashboardUser).order_by(DashboardUser.username):
                print(f"{u.username:32} {u.role:11} last login {u.last_login_at or 'never'}")
            return

        username = normalize_username(args.username)
        if args.cmd == "add":
            if db.query(DashboardUser).filter(DashboardUser.username == username).first():
                sys.exit(f"User {username} already exists")
            password = _read_password(args.password_stdin)
            try:
                validate_new_user(username, password, args.role)
            except ValueError as e:
                sys.exit(str(e))
            db.add(DashboardUser(username=username, password_hash=hash_password(password),
                                 role=args.role, session_version=1))
            print(f"Added {username} ({args.role})")
        elif args.cmd == "set-role":
            user = _find(db, username)
            user.role = args.role
            user.session_version += 1
            print(f"{username} is now {args.role}")
        elif args.cmd == "set-password":
            user = _find(db, username)
            password = _read_password(args.password_stdin)
            try:
                validate_password(password)
            except ValueError as e:
                sys.exit(str(e))
            user.password_hash = hash_password(password)
            user.session_version += 1
            print(f"Password changed for {username}")
        elif args.cmd == "remove":
            db.delete(_find(db, username))
            print(f"Removed {username}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
