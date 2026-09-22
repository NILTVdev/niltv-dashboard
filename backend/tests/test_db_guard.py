"""The conftest guard: the suite only runs against a database on this machine."""

import pytest

from backend.config import Settings
from backend.tests import conftest
from backend.tests.conftest import require_local_db_host


def test_guard_needs_valid_settings_and_a_local_db_host(monkeypatch):
    for host in (*Settings.LOCAL_DB_HOSTS, " LocalHost "):
        require_local_db_host(host)
    with pytest.raises(pytest.UsageError, match="DB_HOST is 'prod-db.internal'"):
        require_local_db_host("prod-db.internal")

    # get_settings() without the cache (and without a .env file).
    def fresh_settings():
        s = Settings(_env_file=None)
        s.validate_environment()
        return s
    monkeypatch.setattr(conftest, "get_settings", fresh_settings)

    monkeypatch.setenv("ENVIRONMENT", "moon")
    with pytest.raises(pytest.UsageError, match="ENVIRONMENT='moon' is not one of"):
        conftest.configured_db_host()

    monkeypatch.delenv("DB_PASS", raising=False)
    with pytest.raises(pytest.UsageError, match=r"missing or invalid: DB_PASS\."):
        conftest.configured_db_host()
