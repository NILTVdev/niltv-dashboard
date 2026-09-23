"""Focused date-window and snapshot-delta tests for dashboard analytics."""

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import NiltvNetworkPost, NiltvNetworkPostSnapshot
from backend.routers.campus_channels import CAMPUS_CHANNELS, _growth, campus_channels_summary
from backend.routers.network_screen import _prev_week_bounds, _week_bounds


def test_week_bounds_are_rolling_seven_calendar_days() -> None:
    now = datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc)

    assert _week_bounds(now) == (
        datetime(2026, 9, 17, tzinfo=timezone.utc),
        datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    assert _prev_week_bounds(now) == (
        datetime(2026, 9, 10, tzinfo=timezone.utc),
        datetime(2026, 9, 17, tzinfo=timezone.utc),
    )


def test_growth_counts_new_posts_and_reports_missing_baselines() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    posts = [
        SimpleNamespace(id=1, publish_time=datetime(2026, 7, 1, tzinfo=timezone.utc), views=160),
        SimpleNamespace(id=2, publish_time=datetime(2026, 8, 15, tzinfo=timezone.utc), views=50),
        SimpleNamespace(id=3, publish_time=datetime(2026, 7, 1, tzinfo=timezone.utc), views=200),
        SimpleNamespace(id=4, publish_time=datetime(2026, 7, 1, tzinfo=timezone.utc), views=90),
    ]
    captures = {
        1: [(start, 100), (end, 160)],
        2: [(datetime(2026, 8, 16, tzinfo=timezone.utc), 50)],
        # Old post with no start capture: excluded rather than assumed to be zero.
        3: [(datetime(2026, 8, 20, tzinfo=timezone.utc), 200)],
        # A source regression is reported and contributes zero, never negative growth.
        4: [(start, 100), (end, 90)],
    }

    result = _growth(posts, captures, start, end, now)

    assert result.views_gained == 110
    assert result.posts_measured == 3
    assert result.posts_missing_baseline == 1
    assert result.regressed_posts == 1
    assert result.coverage_pct == 75.0


def test_brazos_is_always_an_explicit_channel() -> None:
    assert ("brazostv", "Brazos TV") in CAMPUS_CHANNELS


def test_brazos_matches_only_the_exact_collab_token() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    NiltvNetworkPost.__table__.create(engine)
    NiltvNetworkPostSnapshot.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    published = datetime.now(timezone.utc).replace(microsecond=0)

    with Session() as db:
        db.add_all([
            NiltvNetworkPost(
                post_id="brazos-exact",
                collab_accounts="niltv, brazostv",
                publish_time=published,
                views=125,
                views_source="graph",
            ),
            NiltvNetworkPost(
                post_id="brazos-decoy",
                collab_accounts="brazostvextra",
                publish_time=published,
                views=999_999,
                views_source="graph",
            ),
        ])
        db.commit()

        result = campus_channels_summary(db)

    brazos = next(channel for channel in result.channels if channel.channel == "brazostv")
    assert brazos.all_time.posts == 1
    assert brazos.all_time.views == 125
