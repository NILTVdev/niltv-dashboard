"""local -> dev -> prod environment rules (backend/config.py, backend/auth.py,
backend/jobs/base.py):

* ENVIRONMENT=local bypasses X-API-Key, but only with a local database;
* dev and production require the key (DASHBOARD_API_KEY, else the password);
* side effects (S3/SNS/CloudWatch) are production-only unless ALLOW_SIDE_EFFECTS;
* the migration runner records what it applied.
Runs in CI against the seeded Postgres (ENVIRONMENT=dev there).
"""

import pytest
from fastapi.testclient import TestClient

from backend import auth as auth_module
from backend.config import Settings, get_settings
from backend.main import app

client = TestClient(app)
BASE = dict(db_pass="x", ig_access_token="x", ig_business_id="x", dashboard_password="secret")


def _settings(**over) -> Settings:
    s = Settings(**{**BASE, **over})
    s.validate_environment()
    return s


def test_local_requires_a_local_database():
    assert _settings(environment="local", db_host="localhost").auth_disabled
    assert _settings(environment="local", db_host="db").auth_disabled
    with pytest.raises(RuntimeError, match="DB_HOST must be a local database"):
        _settings(environment="local", db_host="prod-db.internal")
    assert _settings(environment="staging", db_host="h").environment == "dev"   # alias
    assert _settings(environment="Prod").environment == "production"
    with pytest.raises(RuntimeError, match="not one of"):
        _settings(environment="moon")


def test_dev_and_production_keep_auth_and_split_the_key():
    dev = _settings(environment="dev", db_host="anything")
    assert not dev.auth_disabled and dev.api_key == "secret"      # falls back to the password
    prod = _settings(environment="production", dashboard_api_key="k")
    assert not prod.auth_disabled and prod.api_key == "k" and prod.is_production


def test_side_effects_are_production_only_unless_opted_in():
    assert _settings(environment="production").side_effects_enabled
    assert not _settings(environment="dev", db_host="h").side_effects_enabled
    assert _settings(environment="dev", db_host="h", allow_side_effects=True).side_effects_enabled
    assert not _settings(environment="local", allow_side_effects=True).side_effects_enabled


def test_api_key_dependency_follows_the_environment(monkeypatch):
    # CI runs as dev: the key is enforced.
    assert client.get("/api/brand/accounts").status_code == 401
    assert client.get("/api/brand/accounts", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/brand/accounts", headers={"X-API-Key": get_settings().api_key}).status_code == 200

    # Same app, settings swapped to local: no key needed and /api/health says so.
    local = _settings(environment="local", db_host="localhost")
    monkeypatch.setattr(auth_module, "get_settings", lambda: local)
    assert client.get("/api/brand/accounts").status_code == 200
    monkeypatch.undo()
    assert client.get("/api/brand/accounts").status_code == 401

    health = client.get("/api/health").json()
    assert health["environment"] == get_settings().environment and health["auth"] == "api-key"

    # The keyed probe the dashboard's /api/health calls: 401 without the key, ok with it.
    assert client.get("/api/health/auth").status_code == 401
    keyed = client.get("/api/health/auth", headers={"X-API-Key": get_settings().api_key})
    assert keyed.status_code == 200 and keyed.json()["auth"] == "ok"


def test_migration_runner_recorded_every_file():
    """CI applies the schema with scripts.migrate; every file must be on record."""
    from sqlalchemy import text
    from backend.database import engine
    from scripts.migrate import _files
    with engine.connect() as conn:
        applied = {r[0] for r in conn.execute(text("SELECT filename FROM schema_migrations"))}
    assert applied == {p.name for p in _files()}
