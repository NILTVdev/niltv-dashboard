"""Athlete directory: merge rules, parsing, filters, and who may see what.

Pure tests build ``Records`` by hand; the API tests seed the local Postgres.
All names, handles, emails and phone numbers are synthetic.
"""

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import accounts
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
    DashboardUser,
    NiltvNetworkPost,
    NiltvNetworkPostSnapshot,
)

client = TestClient(app)
KEY = {"X-API-Key": "test"}  # matches DASHBOARD_PASSWORD in the CI env
BASE = "/api/athlete-directory"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


# ── Builders for pure tests ───────────────────────────────────────────────────

def ath(id, name="Test Athlete", ig=None, **kw):
    return {"id": id, "name": name, "sport": kw.get("sport"), "year": None, "ig_handle": ig,
            "tiktok_handle": None, "x_handle": kw.get("x"), "cached_ig_followers": kw.get("followers"),
            "cached_last_pulled": kw.get("pulled"), "created_at": kw.get("created", T0)}


def amb(id, ig=None, status="confirmed", athlete_id=None, **kw):
    return {"id": id, "ig_username": ig, "display_name": kw.get("name"), "previous_usernames": kw.get("prev"),
            "campus": kw.get("campus"), "school": kw.get("school"), "sport": kw.get("sport"), "year": None,
            "gender": None, "profile_pic_url": None, "status": status, "athlete_id": athlete_id,
            "cached_followers": kw.get("followers"), "cached_collab_posts": kw.get("posts"),
            "cached_collab_views": kw.get("views"), "cached_collab_engagement": None,
            "cached_last_pulled": kw.get("pulled"), "created_at": kw.get("created", T0)}


def app_row(id, ig=None, ambassador_id=None, first="Test", last="Applicant", **kw):
    return {"id": id, "ambassador_id": ambassador_id, "first_name": first, "last_name": last,
            "university": kw.get("school"), "sport": kw.get("sport"), "year": None,
            "campus_channel": kw.get("campus"), "instagram": ig,
            "instagram_followers": kw.get("followers"), "tiktok": None, "tiktok_followers": kw.get("tiktok"),
            "youtube": None, "youtube_subscribers": None, "nil_deals_done": None, "nil_deals_wanted": None,
            "content_type": None, "consent_partners": kw.get("consent", False), "status": "applicant",
            "created_at": kw.get("created", T0), "updated_at": kw.get("updated")}


def people(athletes=(), ambassadors=(), applications=(), posts=None):
    return d.merge(d.Records(list(athletes), list(ambassadors), list(applications), posts or {}))


def by_key(ps):
    return {p["key"]: p for p in ps}


# ── Normalizing and parsing ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("@Jane.Doe", "jane.doe"),
    ("  jane_doe. ", "jane_doe"),
    ("https://www.instagram.com/Jane.Doe/?hl=en", "jane.doe"),
    ("instagram.com/jane.doe", "jane.doe"),
    ("http://instagram.com/@jane_doe/", "jane_doe"),
    ("m.instagram.com/jane_doe#top", "jane_doe"),
    ("N/A", None),
    ("none", None),
    ("jane doe", None),
    ("", None),
    (None, None),
])
def test_normalize_handle(raw, want):
    assert d.normalize_handle(raw) == want


@pytest.mark.parametrize("text,want", [
    ("12.5k", 12500),
    ("12.5K followers", 12500),
    ("1,200", 1200),
    ("1.2M", 1200000),
    ("850", 850),
    ("about 3k+", 3000),
    ("10-20k", 10000),
    ("2 thousand", 2000),
    ("lots", None),
    ("", None),
    (None, None),
    ("n/a", None),
])
def test_parse_follower_count(text, want):
    assert d.parse_follower_count(text) == want


# ── Merge rules ───────────────────────────────────────────────────────────────

def test_application_ambassador_athlete_chain_is_one_person():
    ps = people(
        athletes=[ath(5, "Roster Name", ig="old_handle", followers=900, pulled=T0)],
        ambassadors=[amb(12, ig="new_handle", athlete_id=5, followers=1000, pulled=T0 + timedelta(days=1))],
        applications=[app_row(40, ig="something_else", ambassador_id=12, followers="50k")],
    )
    assert len(ps) == 1
    p = ps[0]
    assert p["key"] == "amb-12"
    assert set(p["member_keys"]) == {"amb-12", "ath-5", "app-40"}
    assert p["sources"] == ["athlete", "ambassador", "application"]
    assert p["display_name"] == "Roster Name"
    # Measured wins over the application's self-reported text; newest pull wins.
    assert p["followers"] == 1000 and p["followers_source"] == "ambassador"
    assert p["followers_self_reported"] is False
    assert p["status"] == "ambassador_confirmed"


def test_handle_match_links_across_tables_with_urls_and_at_signs():
    ps = people(
        athletes=[ath(1, "Alpha Example", ig="alpha.example")],
        applications=[app_row(2, ig="https://instagram.com/Alpha.Example/"),
                      app_row(3, ig="@ALPHA.EXAMPLE")],
    )
    assert len(ps) == 1
    assert ps[0]["key"] == "ath-1"
    assert ps[0]["application_ids"] == [2, 3] or set(ps[0]["application_ids"]) == {2, 3}


def test_previous_username_links_an_old_application():
    ps = people(ambassadors=[amb(7, ig="renamed", prev="original_name")],
                applications=[app_row(8, ig="@original_name")])
    assert len(ps) == 1 and ps[0]["key"] == "amb-7"


def test_same_name_alone_never_merges():
    ps = people(athletes=[ath(1, "Sam Sample", ig="sam_one")],
                applications=[app_row(2, first="Sam", last="Sample", ig="sam_two"),
                              app_row(3, first="Sam", last="Sample")])
    assert len(ps) == 3


def test_duplicate_applications_with_one_handle_merge_newest_first():
    ps = people(applications=[
        app_row(1, ig="dup_handle", followers="1k", updated=T0),
        app_row(2, ig="Dup_Handle", followers="2k", updated=T0 + timedelta(days=3)),
    ])
    assert len(ps) == 1
    p = ps[0]
    assert p["key"] == "app-2"
    assert p["followers"] == 2000 and p["followers_self_reported"] is True
    assert p["status"] == "applicant"


def test_handle_match_never_joins_two_ambassadors_or_two_roster_rows():
    # Ambassador 2 once used the handle ambassador 1 holds now.
    ps = people(ambassadors=[amb(1, ig="shared"), amb(2, ig="other", prev="shared")],
                athletes=[ath(3, ig="dup"), ath(4, ig="dup2")],
                applications=[app_row(5, ig="shared")])
    keys = by_key(ps)
    assert set(keys) == {"amb-1", "amb-2", "ath-3", "ath-4"}
    assert "app-5" in keys["amb-1"]["member_keys"]


def test_foreign_key_beats_a_conflicting_handle():
    ps = people(ambassadors=[amb(1, ig="first_amb"), amb(2, ig="second_amb")],
                applications=[app_row(9, ig="second_amb", ambassador_id=1)])
    keys = by_key(ps)
    assert "app-9" in keys["amb-1"]["member_keys"]
    assert keys["amb-2"]["member_keys"] == ["amb-2"]


def test_junk_handles_do_not_merge_strangers():
    ps = people(applications=[app_row(1, ig="none"), app_row(2, ig="N/A"), app_row(3, ig="none")])
    assert len(ps) == 3


def test_status_and_roster_defaults():
    ps = by_key(people(athletes=[ath(1, ig="r1")], ambassadors=[amb(2, ig="c1", status="candidate")]))
    assert ps["ath-1"]["status"] == "roster"
    assert ps["ath-1"]["school"] == d.ROSTER_SCHOOL and ps["ath-1"]["campus"] == d.ROSTER_CAMPUS
    assert ps["amb-2"]["status"] == "ambassador_candidate"


def test_collab_stats_fall_back_to_posts_by_handle():
    ps = people(applications=[app_row(1, ig="poster")], posts={"poster": (3, 4500, 210)})
    assert (ps[0]["collab_posts"], ps[0]["collab_views"], ps[0]["collab_engagement"]) == (3, 4500, 210)


def test_resolve_key_accepts_any_member_key():
    ps = people(ambassadors=[amb(12, ig="x_handle")], applications=[app_row(40, ambassador_id=12)])
    assert d.resolve_key(ps, "app-40")["key"] == "amb-12"
    assert d.resolve_key(ps, "app-41") is None


# ── Filters and sort ──────────────────────────────────────────────────────────

def _sample():
    return people(
        athletes=[ath(1, "Zed Roster", ig="zed", sport="Soccer", followers=500, pulled=T0)],
        ambassadors=[amb(2, ig="amy", name="Amy Ambassador", sport="Lacrosse", school="Sample State",
                         campus="samplestate", followers=9000, posts=4, views=12000, pulled=T0)],
        applications=[
            app_row(3, ig="bea", first="Bea", last="Applicant", sport="lacrosse", school="Sample State",
                    followers="2.5k", consent=True, created=T0 + timedelta(days=5)),
            app_row(4, first="Cal", last="Nohandle", sport="Golf", school="Other U"),
        ],
    )


def _keys(ps, **kw):
    return [p["key"] for p in d.apply(ps, d.Query(**kw))]


def test_sorts():
    ps = _sample()
    assert _keys(ps, sort="followers") == ["amb-2", "app-3", "ath-1", "app-4"]
    assert _keys(ps, sort="collab_views")[0] == "amb-2"
    assert _keys(ps, sort="name") == ["amb-2", "app-3", "app-4", "ath-1"]
    assert _keys(ps, sort="newest")[0] == "app-3"


def test_filters():
    ps = _sample()
    assert _keys(ps, q="sample state", sort="name") == ["amb-2", "app-3"]
    assert _keys(ps, q="@zed") == ["ath-1"]
    assert _keys(ps, sport="LACROSSE", sort="name") == ["amb-2", "app-3"]
    assert _keys(ps, campus="samplestate") == ["amb-2"]
    assert _keys(ps, status="applicant", sort="name") == ["app-3", "app-4"]
    assert _keys(ps, source="athlete") == ["ath-1"]
    assert _keys(ps, partner_consent=True) == ["app-3"]
    assert _keys(ps, min_followers=1000, max_followers=5000) == ["app-3"]
    assert _keys(ps, has_content=True) == ["amb-2"]


def test_facets_fold_case():
    f = d.facets(_sample())
    assert {"value": "Lacrosse", "count": 2} in f["sport"]
    assert f["school"][0] == {"value": "Sample State", "count": 2}


def test_merge_speed_5k_rows():
    """5,000 synthetic records, about a third of them linked."""
    n = 1700
    athletes = [ath(i, f"Athlete {i}", ig=f"user{i}", followers=i, pulled=T0) for i in range(n)]
    ambassadors = [amb(i, ig=f"user{i}" if i % 2 else f"amb{i}", athlete_id=i if i % 3 == 0 else None,
                       followers=i * 2, pulled=T0) for i in range(n)]
    applications = [app_row(i, ig=f"user{i}" if i % 4 == 0 else f"app{i}",
                            ambassador_id=i if i % 5 == 0 else None, followers=f"{i}k") for i in range(1600)]
    start = time.perf_counter()
    ps = people(athletes, ambassadors, applications)
    d.apply(ps, d.Query(q="user1", sort="followers"))
    elapsed = time.perf_counter() - start
    assert 0 < len(ps) < n * 3
    assert elapsed < 1.0, f"merge took {elapsed * 1000:.0f} ms"


# ── API ───────────────────────────────────────────────────────────────────────

def _clean(db):
    db.query(NiltvNetworkPostSnapshot).delete()
    db.query(NiltvNetworkPost).delete()
    db.query(ApplicationEvent).delete()
    db.query(Application).delete()
    db.query(AmbassadorSnapshot).delete()
    db.query(Ambassador).delete()
    db.query(AthleteSnapshot).delete()
    db.query(AthletePost).delete()
    db.query(Athlete).delete()
    db.query(DashboardUser).filter(DashboardUser.email.like("%@directory.example.com")).delete(
        synchronize_session=False)
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    yield session
    _clean(session)
    session.close()


@pytest.fixture()
def seeded(db):
    roster = Athlete(name="Rory Roster", sport="Soccer", ig_handle="rory.roster", cached_ig_followers=4200,
                     cached_last_pulled=T0)
    db.add(roster)
    db.flush()
    ambassador = Ambassador(ig_username="amber.amb", display_name="Amber Ambassador", status="confirmed",
                            sport="Lacrosse", school="Sample State", campus="samplestate",
                            cached_followers=15000, cached_collab_posts=1, cached_collab_views=7000,
                            cached_last_pulled=T0)
    db.add(ambassador)
    db.flush()
    db.add(Application(email="amber@example.com", college_email="amber@school.example.edu", phone="555-0100",
                       first_name="Amber", last_name="Ambassador", instagram="@Amber.Amb",
                       instagram_followers="14k", description="Synthetic answer text", consent_partners=True,
                       ambassador_id=ambassador.id))
    db.add(Application(email="ivy@example.com", phone="555-0101", first_name="Ivy", last_name="Applicant",
                       university="Other U", sport="Golf", instagram="instagram.com/ivy.app",
                       instagram_followers="1.2k"))
    db.add_all([
        AthleteSnapshot(athlete_id=roster.id, pulled_at=T0 - timedelta(days=1), ig_followers=4100),
        AthleteSnapshot(athlete_id=roster.id, pulled_at=T0, ig_followers=4200),
        AmbassadorSnapshot(ambassador_id=ambassador.id, pulled_at=T0, followers=15000),
        NiltvNetworkPost(post_id="dir-1", account_username="amber.amb", ambassador_id=ambassador.id,
                         publish_time=T0, views=7000, likes=300),
        NiltvNetworkPost(post_id="dir-2", account_username="Rory.Roster", publish_time=T0, views=800, likes=20),
    ])
    db.commit()
    return {"roster": roster.id, "ambassador": ambassador.id}


def _as(db, role):
    user = DashboardUser(email=f"{role}@directory.example.com", name=role, role=role, password_hash="x")
    db.add(user)
    db.commit()
    return {**KEY, "X-Dashboard-User": str(user.id), "X-Dashboard-Session-Version": str(user.session_version)}


def test_role_policy_table():
    assert accounts.allowed("general", "GET", f"{BASE}/") is True
    assert accounts.allowed("general", "GET", f"{BASE}/amb-1") is True
    assert accounts.allowed("general", "GET", f"{BASE}/facets") is True
    assert accounts.allowed("general", "GET", f"{BASE}/export.csv") is False
    assert accounts.allowed("demo", "GET", f"{BASE}/") is False
    assert accounts.allowed("admin", "GET", f"{BASE}/export.csv") is True


def test_list_requires_key():
    assert client.get(f"{BASE}/").status_code == 401


def test_list_search_and_paging(db, seeded):
    r = client.get(f"{BASE}/", headers=KEY)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    names = [p["display_name"] for p in body["items"]]
    assert names == ["Amber Ambassador", "Rory Roster", "Ivy Applicant"]
    ivy = body["items"][2]
    assert ivy["followers"] == 1200 and ivy["followers_self_reported"] is True

    r = client.get(f"{BASE}/", headers=KEY, params={"q": "ivy", "limit": 1})
    assert r.json()["total"] == 1 and r.json()["items"][0]["ig_handle"] == "ivy.app"
    r = client.get(f"{BASE}/", headers=KEY, params={"sort": "name", "limit": 1, "offset": 1})
    assert [p["display_name"] for p in r.json()["items"]] == ["Ivy Applicant"]
    assert client.get(f"{BASE}/", headers=KEY, params={"sort": "bogus"}).status_code == 400
    assert client.get(f"{BASE}/", headers=KEY, params={"status": "bogus"}).status_code == 400


def test_list_never_carries_contact_fields(db, seeded):
    text = client.get(f"{BASE}/", headers=KEY).text
    for secret in ("amber@example.com", "555-0100", "Synthetic answer text", "email", "phone"):
        assert secret not in text


def test_facets(db, seeded):
    body = client.get(f"{BASE}/facets", headers=KEY).json()
    assert body["total"] == 3
    assert {"value": "Sample State", "count": 1} in body["school"]


def test_detail_history_and_posts(db, seeded):
    amb_key = f"amb-{seeded['ambassador']}"
    body = client.get(f"{BASE}/{amb_key}", headers=KEY).json()
    assert body["person"]["key"] == amb_key
    assert body["person"]["partner_consent"] is True
    assert [p["post_id"] for p in body["posts"]] == ["dir-1"]
    assert body["history"][0]["ig_followers"] == 15000

    roster = client.get(f"{BASE}/ath-{seeded['roster']}", headers=KEY).json()
    assert [h["ig_followers"] for h in roster["history"]] == [4200, 4100]
    assert [p["post_id"] for p in roster["posts"]] == ["dir-2"]  # matched by handle, case-insensitive
    assert client.get(f"{BASE}/amb-999999", headers=KEY).status_code == 404


def test_detail_by_application_key_resolves_to_the_person(db, seeded):
    app_id = db.query(Application.id).filter(Application.email == "amber@example.com").scalar()
    body = client.get(f"{BASE}/app-{app_id}", headers=KEY).json()
    assert body["person"]["key"] == f"amb-{seeded['ambassador']}"


def test_admin_sees_contact_fields(db, seeded):
    body = client.get(f"{BASE}/amb-{seeded['ambassador']}", headers=_as(db, "admin")).json()
    [a] = body["applications"]
    assert a["email"] == "amber@example.com"
    assert a["phone"] == "555-0100"
    assert a["college_email"] == "amber@school.example.edu"
    assert a["description"] == "Synthetic answer text"


def test_general_gets_no_contact_fields(db, seeded):
    headers = _as(db, "general")
    r = client.get(f"{BASE}/amb-{seeded['ambassador']}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["applications"] is None
    for secret in ("amber@example.com", "555-0100", "school.example.edu", "Synthetic answer text",
                   '"email"', '"phone"'):
        assert secret not in r.text
    assert client.get(f"{BASE}/", headers=headers).status_code == 200
    assert client.get(f"{BASE}/export.csv", headers=headers).status_code == 403


def test_demo_is_refused(db, seeded):
    headers = _as(db, "demo")
    for path in ("/", "/facets", f"/amb-{seeded['ambassador']}", "/export.csv"):
        assert client.get(f"{BASE}{path}", headers=headers).status_code == 403


def test_export_csv_admin(db, seeded):
    r = client.get(f"{BASE}/export.csv", headers=_as(db, "admin"), params={"source": "application"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("key,display_name,status")
    assert len(lines) == 3  # header + the two people with an application
    assert "amber@example.com" in r.text and "555-0101" in r.text


def test_export_neutralizes_formulas(db):
    db.add(Application(email="formula@example.com", first_name="=HYPERLINK(1)", last_name="Test"))
    db.commit()
    r = client.get(f"{BASE}/export.csv", headers=KEY)
    assert "'=HYPERLINK(1) Test" in r.text


def test_speed_against_postgres_5k_rows(db):
    """Times one list request over 5,000 seeded rows. Prints the number for
    the record; the bound is loose so a slow CI runner does not flake."""
    n = 1700
    db.bulk_insert_mappings(Athlete, [
        {"name": f"Bench Athlete {i}", "ig_handle": f"bench{i}", "cached_ig_followers": i, "active": True}
        for i in range(n)])
    db.bulk_insert_mappings(Ambassador, [
        {"ig_username": f"bench{i}" if i % 2 else f"benchamb{i}", "status": "confirmed",
         "cached_followers": i * 2} for i in range(n)])
    db.bulk_insert_mappings(Application, [
        {"email": f"bench{i}@example.com", "instagram": f"@bench{i}" if i % 4 == 0 else f"benchapp{i}",
         "instagram_followers": f"{i}k"} for i in range(1600)])
    db.commit()
    client.get("/api/health", headers=KEY)  # warm the app and connection pool

    def timed():
        start = time.perf_counter()
        r = client.get(f"{BASE}/", headers=KEY, params={"q": "bench1", "sort": "followers"})
        assert r.status_code == 200 and r.json()["total"] > 0
        return (time.perf_counter() - start) * 1000

    d.clear_cache()
    cold = timed()
    warm = min(timed() for _ in range(3))
    print(f"\nathlete directory, 5000 rows: first request {cold:.0f} ms, unchanged tables {warm:.0f} ms")
    assert cold < 3000 and warm < 1000


def test_cache_sees_changes(db, seeded):
    first = client.get(f"{BASE}/amb-{seeded['ambassador']}", headers=KEY).json()
    assert first["person"]["display_name"] == "Amber Ambassador"
    db.query(Ambassador).filter(Ambassador.id == seeded["ambassador"]).update({"display_name": "Amber Renamed"})
    db.commit()
    again = client.get(f"{BASE}/amb-{seeded['ambassador']}", headers=KEY).json()
    assert again["person"]["display_name"] == "Amber Renamed"
    db.add(Application(email="late@example.com", first_name="Late", last_name="Signup"))
    db.commit()
    assert client.get(f"{BASE}/", headers=KEY).json()["total"] == 4
