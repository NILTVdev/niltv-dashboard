"""Cross-repo contract: the app's ingest builds the library sync body with its
real mapping code and saves a sample (niltv-app
backend/test/fixtures/dashboard-library-sync.sample.json). That file is copied
here unchanged, so a change on either side that breaks the contract fails this
test. Refresh the copy when the app's sample changes."""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import LibraryItem, LibrarySyncRun

client = TestClient(app)
KEY = {"X-API-Key": "test"}
SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "dashboard-library-sync.sample.json")
                    .read_text(encoding="utf-8"))


def _clean(db):
    db.query(LibraryItem).delete()
    db.query(LibrarySyncRun).delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    yield session
    _clean(session)
    session.close()


def test_app_sample_is_accepted_and_stored(db):
    n = len(SAMPLE["items"])
    r = client.post("/api/library/sync", headers=KEY, json=SAMPLE)
    assert r.status_code == 200, r.text
    assert r.json() == {"received": n, "upserted": n, "removed": 0}

    rows = {row.content_id: row for row in db.query(LibraryItem)}
    assert set(rows) == {i["content_id"] for i in SAMPLE["items"]}
    for item in SAMPLE["items"]:
        row = rows[item["content_id"]]
        assert row.stage == SAMPLE["stage"] and row.removed is False
        assert row.ig_post_id == item["ig_post_id"]
        assert row.title == item["title"] and row.status == item["status"]
        assert row.qc_state == item["qc_state"]
        assert list(row.keywords) == item["keywords"]
        assert list(row.categories) == item["categories"]
        assert row.athletes == item["athletes"]
        assert list(row.unresolved_handles) == item["unresolved_handles"]
        assert row.duration_sec == item["duration_sec"]
        assert list(row.tags) == item["tags"]
        assert row.asset_type == item["asset_type"]
        assert (row.series_id, row.series_name) == (item["series_id"], item["series_name"])
        assert (row.season, row.episode) == (item["season"], item["episode"])

    run = db.query(LibrarySyncRun).one()
    assert run.ok and run.received == n and run.upserted == n


def test_app_sample_is_idempotent_and_full_snapshot_removes(db):
    assert client.post("/api/library/sync", headers=KEY, json=SAMPLE).status_code == 200
    again = client.post("/api/library/sync", headers=KEY, json=SAMPLE)
    assert again.json() == {"received": len(SAMPLE["items"]), "upserted": len(SAMPLE["items"]), "removed": 0}

    first_only = copy.deepcopy(SAMPLE)
    first_only["items"] = first_only["items"][:1]
    r = client.post("/api/library/sync", headers=KEY, json=first_only)
    assert r.status_code == 200, r.text
    assert r.json() == {"received": 1, "upserted": 1, "removed": len(SAMPLE["items"]) - 1}
