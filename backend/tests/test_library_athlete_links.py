"""Links between the content library and the athlete directory: the athlete
detail lists the library clips that tag one of the person's Instagram handles,
and library clips carry the directory key of each tagged athlete it knows.

All names and handles are synthetic.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import athlete_directory as d
from backend.database import SessionLocal
from backend.main import app
from backend.models import (
    Ambassador,
    AmbassadorSnapshot,
    Application,
    ApplicationEvent,
    Athlete,
    AthletePost,
    AthleteSnapshot,
    LibraryItem,
    LibrarySyncRun,
)

client = TestClient(app)
KEY = {"X-API-Key": "test"}
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _clean(db):
    db.query(LibraryItem).delete()
    db.query(LibrarySyncRun).delete()
    db.query(ApplicationEvent).delete()
    db.query(Application).delete()
    db.query(AmbassadorSnapshot).delete()
    db.query(Ambassador).delete()
    db.query(AthleteSnapshot).delete()
    db.query(AthletePost).delete()
    db.query(Athlete).delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    yield session
    _clean(session)
    session.close()


def clip(content_id, athletes=(), unresolved=(), posted="2026-09-01T12:00:00Z", **kw):
    return {"content_id": content_id, "ig_post_id": None, "title": f"Sample clip {content_id}",
            "status": "published", "qc_state": "ready", "posted_at": posted,
            "athletes": [{"id": None, "name": None, "handle": h} for h in athletes],
            "unresolved_handles": list(unresolved), **kw}


def sync(items):
    r = client.post("/api/library/sync", headers=KEY, json={
        "source": "niltv-app", "stage": "dev", "generated_at": "2026-09-02T00:00:00Z", "full": True,
        "items": items})
    assert r.status_code == 200, r.text


@pytest.fixture()
def seeded(db):
    roster = Athlete(name="Rory Roster", sport="Soccer", ig_handle="rory.roster", cached_last_pulled=T0)
    amber = Ambassador(ig_username="amber.amb", previous_usernames="amber.old", display_name="Amber Ambassador",
                       status="confirmed", sport="Lacrosse")
    cole = Ambassador(ig_username="cole.amb", display_name="Cole Confirmed", status="confirmed")
    db.add_all([roster, amber, cole])
    db.flush()
    # Rory is on the roster and a confirmed ambassador, so a NIL TV athlete.
    db.add(Ambassador(ig_username="rory.roster", display_name="Rory Roster", status="confirmed",
                      athlete_id=roster.id))
    db.add(Application(email="ivy@example.com", first_name="Ivy", last_name="Applicant",
                       instagram="instagram.com/ivy.app"))
    db.commit()
    sync([
        clip("c-new", athletes=["@Amber.Amb"], posted="2026-09-03T12:00:00Z"),
        clip("c-old-handle", athletes=["amber.old"], posted="2026-09-02T12:00:00Z"),
        clip("c-unresolved", unresolved=["Rory.Roster"]),
        clip("c-nobody", athletes=["someone.else"]),
        clip("c-no-handles"),
    ])
    # A clip the app no longer lists is marked removed and leaves the athlete page.
    db.add(LibraryItem(content_id="c-removed", stage="dev", title="Removed clip", status="published",
                       athletes=[{"id": None, "name": None, "handle": "amber.amb"}], removed=True))
    db.commit()
    return {"roster": roster.id, "amber": amber.id, "cole": cole.id}


def test_keys_by_handle_prefers_current_owner():
    people = d.merge(d.Records(
        [], [{"id": 1, "ig_username": "new.owner", "previous_usernames": "shared.handle", "display_name": None,
              "campus": None, "school": None, "sport": None, "year": None, "gender": None,
              "profile_pic_url": None, "status": "confirmed", "athlete_id": None, "cached_followers": None,
              "cached_collab_posts": None, "cached_collab_views": None, "cached_collab_engagement": None,
              "cached_last_pulled": None, "created_at": T0},
             {"id": 2, "ig_username": "shared.handle", "previous_usernames": None, "display_name": None,
              "campus": None, "school": None, "sport": None, "year": None, "gender": None,
              "profile_pic_url": None, "status": "confirmed", "athlete_id": None, "cached_followers": None,
              "cached_collab_posts": None, "cached_collab_views": None, "cached_collab_engagement": None,
              "cached_last_pulled": None, "created_at": T0}],
        [], {}, {}))
    keys = d.keys_by_handle(people)
    assert keys == {"new.owner": "amb-1", "shared.handle": "amb-2"}


def test_athlete_detail_lists_clips_for_every_handle(seeded):
    r = client.get(f"/api/athlete-directory/amb-{seeded['amber']}", headers=KEY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["clips_total"] == 2
    assert [c["content_id"] for c in body["clips"]] == ["c-new", "c-old-handle"]
    # The clip carries the normal library shape, performance included.
    assert body["clips"][0]["performance"]["matched"] is False


def test_unresolved_handle_counts_as_featuring(seeded):
    body = client.get(f"/api/athlete-directory/ath-{seeded['roster']}", headers=KEY).json()
    assert body["clips_total"] == 1
    assert [c["content_id"] for c in body["clips"]] == ["c-unresolved"]


def test_person_without_clips_gets_empty_list(seeded):
    body = client.get(f"/api/athlete-directory/amb-{seeded['cole']}", headers=KEY).json()
    assert body["clips"] == [] and body["clips_total"] == 0
    # The internal handle list never leaks into the person payload.
    assert "ig_handles" not in body["person"]


def test_library_links_known_athletes_to_their_page(seeded):
    r = client.get("/api/library/", headers=KEY, params={"limit": 50})
    assert r.status_code == 200, r.text
    links = {i["content_id"]: [a["directory_key"] for a in i["athletes"]] for i in r.json()["items"]}
    assert links["c-new"] == [f"amb-{seeded['amber']}"]
    assert links["c-old-handle"] == [f"amb-{seeded['amber']}"]
    assert links["c-nobody"] == [None]
    assert links["c-no-handles"] == []

    one = client.get("/api/library/c-new", headers=KEY).json()
    assert one["athletes"][0]["directory_key"] == f"amb-{seeded['amber']}"
