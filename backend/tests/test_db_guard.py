"""The conftest guard: the suite only runs against a database on this machine."""

import pytest

from backend.config import Settings
from backend.tests.conftest import require_local_db_host


def test_only_a_local_db_host_is_allowed():
    for host in (*Settings.LOCAL_DB_HOSTS, " LocalHost "):
        require_local_db_host(host)
    with pytest.raises(pytest.UsageError, match="DB_HOST is 'prod-db.internal'"):
        require_local_db_host("prod-db.internal")
