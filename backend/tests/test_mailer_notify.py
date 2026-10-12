"""Staff new-applicant notice: one address or a comma-separated list."""

from backend.config import get_settings
from backend.onboarding import mailer


def _capture(monkeypatch, notify: str) -> list:
    sent = []
    monkeypatch.setattr(get_settings(), "applications_notify_email", notify)
    monkeypatch.setattr(mailer, "_send", lambda to, *a, **k: sent.append(to) or True)
    mailer.notify_staff_new_applicant("Jane Doe", "https://dashboard.niltv.com/niltv-onboarding?id=1")
    return sent


def test_notice_goes_to_every_listed_address(monkeypatch):
    assert _capture(monkeypatch, "a@niltv.com, b@niltv.com ,") == [["a@niltv.com", "b@niltv.com"]]
    assert _capture(monkeypatch, "a@niltv.com") == [["a@niltv.com"]]


def test_no_address_means_no_notice(monkeypatch):
    assert _capture(monkeypatch, "  ") == []
