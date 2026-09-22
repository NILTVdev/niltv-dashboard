"""Refuse to run the backend tests against a database that is not on this machine.

Most test files delete rows before and after each test (applications,
ambassadors, brand accounts, network posts, ...), on whatever database the
settings point at. So before anything is collected, the host backend/database.py
will connect to must be one of Settings.LOCAL_DB_HOSTS. It is read through
get_settings(), the same way database.py reads it, so a DB_HOST set in a .env
file is checked too. Missing or invalid settings are reported the same way.
"""

import pytest
from pydantic import ValidationError

from backend.config import Settings, get_settings


def configured_db_host() -> str:
    try:
        return get_settings().db_host
    except ValidationError as e:
        fields = ", ".join(
            str(err["loc"][0]).upper() + ("" if err["type"] == "missing" else f" ({err['msg']})")
            for err in e.errors())
        raise pytest.UsageError(
            f"Backend settings are missing or invalid: {fields}. "
            f"Set them the way .github/workflows/backend-ci.yml does.") from None
    except RuntimeError as e:  # validate_environment: bad ENVIRONMENT, or local on a remote DB
        raise pytest.UsageError(str(e)) from None


def require_local_db_host(host: str) -> None:
    if host.strip().lower() not in Settings.LOCAL_DB_HOSTS:
        raise pytest.UsageError(
            f"DB_HOST is {host!r}, not a local database ({', '.join(Settings.LOCAL_DB_HOSTS)}). "
            f"The backend tests delete rows, so they only run against a database on this machine.")


def pytest_configure(config):
    # Not pytest_sessionstart: that is skipped when this conftest is only found
    # during collection (plain `pytest` from the repo root). pytest_configure
    # still runs then, before any test module is imported.
    require_local_db_host(configured_db_host())
