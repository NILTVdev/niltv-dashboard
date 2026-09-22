"""Refuse to run the backend tests against a database that is not on this machine.

Most test files delete rows before and after each test (applications,
ambassadors, brand accounts, network posts, ...), on whatever database the
settings point at. So before anything is collected, the host backend/database.py
will connect to must be one of Settings.LOCAL_DB_HOSTS. It is read through
get_settings(), the same way database.py reads it, so a DB_HOST set in a .env
file is checked too.
"""

import pytest

from backend.config import Settings, get_settings


def require_local_db_host(host: str) -> None:
    if host.strip().lower() not in Settings.LOCAL_DB_HOSTS:
        raise pytest.UsageError(
            f"DB_HOST is {host!r}, not a local database ({', '.join(Settings.LOCAL_DB_HOSTS)}). "
            f"The backend tests delete rows, so they only run against a database on this machine.")


def pytest_configure(config):
    # Not pytest_sessionstart: that is skipped when this conftest is only found
    # during collection (plain `pytest` from the repo root). pytest_configure
    # still runs then, before any test module is imported.
    require_local_db_host(get_settings().db_host)
