"""Transactional email for the onboarding pipeline (SES v2 via boto3).

Same sender identity and configuration set as the niltv.com newsletter
confirm mail. An empty ``from_email`` disables sending (returns False), so
tests and local runs never touch SES. A send failure is logged and returned
as False; it never raises into the pipeline.
"""

from __future__ import annotations

import html
import logging

from backend.config import get_settings

log = logging.getLogger(__name__)

# Site palette: near-black ground, gold accent, cream text (assets/css on niltv.com).
_BTN = (
    "display:inline-block;background:#d9b25b;color:#060608;font-weight:700;font-size:15px;"
    "padding:13px 26px;border-radius:999px;text-decoration:none"
)
_WRAP = "font-family:Inter,Arial,sans-serif;font-size:16px;line-height:1.55;color:#111"
_MUTED = "font-size:13px;line-height:1.5;color:#555"
_LOGO_W = 150


def _logo_url() -> str:
    s = get_settings()
    return s.email_logo_url or f"{s.site_base.rstrip('/')}/assets/img/niltv-logo-email.png"


def _layout(inner: str, preheader: str = "") -> str:
    """Branded shell: dark header with the NIL TV logo, white card for the
    message, footer with the contact link. Table-based so Outlook renders it."""
    s = get_settings()
    site = s.site_base.rstrip("/")
    pre = (f'<div style="display:none;max-height:0;overflow:hidden;color:#f4f1ea">{html.escape(preheader)}</div>'
           if preheader else "")
    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#f4f1ea">' + pre +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f1ea">'
        '<tr><td align="center" style="padding:28px 12px">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%">'
        '<tr><td align="center" style="background:#060608;border-radius:14px 14px 0 0;padding:22px 24px">'
        f'<a href="{site}/" style="text-decoration:none"><img src="{html.escape(_logo_url())}" width="{_LOGO_W}" '
        f'alt="NIL TV" style="display:block;width:{_LOGO_W}px;height:auto;border:0"></a></td></tr>'
        '<tr><td style="background:#ffffff;padding:30px 32px 26px;border-radius:0 0 14px 14px;'
        f'border:1px solid #e6e0d2;border-top:0;{_WRAP}">{inner}</td></tr>'
        '<tr><td align="center" style="padding:18px 8px 0;font-family:Inter,Arial,sans-serif;font-size:12px;'
        'line-height:1.6;color:#7a7368">NIL TV, Durham, North Carolina<br>'
        f'<a href="{site}/contact/" style="color:#7a7368">Contact NIL TV</a> &middot; '
        f'<a href="{site}/" style="color:#7a7368">niltv.com</a></td></tr>'
        '</table></td></tr></table></body></html>'
    )


def _send(to: str, subject: str, text: str, html_body: str, preheader: str = "") -> bool:
    s = get_settings()
    if not s.from_email or not to:
        log.info("mailer: skipped (no from_email or recipient) subject=%s", subject)
        return False
    try:
        import boto3

        client = boto3.client("sesv2", region_name=s.aws_region)
        kwargs = {
            "FromEmailAddress": f"NIL TV <{s.from_email}>",
            "Destination": {"ToAddresses": [to]},
            "Content": {"Simple": {
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": text}, "Html": {"Data": _layout(html_body, preheader)}},
            }},
        }
        if s.reply_to_email:
            kwargs["ReplyToAddresses"] = [f"NIL TV <{s.reply_to_email}>"]
        if s.ses_configuration_set:
            kwargs["ConfigurationSetName"] = s.ses_configuration_set
        client.send_email(**kwargs)
        return True
    except Exception as e:  # noqa: BLE001 - mail must never kill the pipeline
        log.error("mailer: send failed to=%s subject=%s err=%s", to, subject, e)
        return False


def send_stripe_link(to: str, first_name: str, link: str) -> bool:
    name = first_name or "there"
    subject = "Your NIL TV agreement is signed. One more step: payouts"
    text = (
        f"Hi {name},\n\nYour NIL TV Ambassador Agreement is signed. To get paid, finish your "
        f"payout setup with Stripe, our payment provider:\n\n{link}\n\n"
        "Stripe verifies your identity and collects your bank details directly. NIL TV never "
        "sees them. This link is yours and does not expire. If Stripe ever says a page is "
        "out of date, open the link again for a fresh one.\n\nNIL TV\n"
    )
    body = (
        f'<p style="margin:0 0 14px">Hi {html.escape(name)},</p>'
        '<p style="margin:0 0 18px">Your NIL TV Ambassador Agreement is signed. To get paid, finish '
        "your payout setup with Stripe, our payment provider.</p>"
        f'<p style="margin:0 0 22px"><a href="{html.escape(link)}" style="{_BTN}">Set up payouts</a></p>'
        f'<p style="{_MUTED};margin:0 0 10px">Stripe verifies your identity and collects your bank '
        "details directly. NIL TV never sees them. This link is yours and does not expire. If Stripe "
        "ever says a page is out of date, open it again for a fresh one.</p>"
        f'<p style="{_MUTED};margin:0">NIL TV</p>'
    )
    return _send(to, subject, text, body, preheader="One more step: set up payouts with Stripe.")


def send_powerform_agreement(to: str, first_name: str, url: str) -> bool:
    """Fallback when the DocuSign API is not configured: send the standing
    PowerForm link instead of a per-person envelope."""
    name = first_name or "there"
    subject = "You're in. Sign your NIL TV Ambassador Agreement"
    text = (
        f"Hi {name},\n\nWelcome to NIL TV. Please sign your Ambassador Agreement here:\n\n{url}\n\n"
        "Once it is signed you will get your payout setup link.\n\nNIL TV\n"
    )
    body = (
        f'<p style="margin:0 0 14px">Hi {html.escape(name)},</p>'
        '<p style="margin:0 0 18px">Welcome to NIL TV. Please sign your Ambassador Agreement.</p>'
        f'<p style="margin:0 0 22px"><a href="{html.escape(url)}" style="{_BTN}">Sign the agreement</a></p>'
        f'<p style="{_MUTED};margin:0 0 10px">Once it is signed you will get your payout setup link.</p>'
        f'<p style="{_MUTED};margin:0">NIL TV</p>'
    )
    return _send(to, subject, text, body, preheader="Welcome to NIL TV. Your Ambassador Agreement is ready to sign.")


def send_application_received(to: str, first_name: str) -> bool:
    name = first_name or "there"
    subject = "NIL TV: we have your application"
    text = (
        f"Hi {name},\n\nThanks for applying to the NIL TV athlete program. We have your application "
        "and every update comes to this address.\n\nWhat happens next:\n"
        "1. NIL TV reviews your application.\n"
        "2. If you are accepted, you get the NIL TV Ambassador Agreement to sign electronically.\n"
        "3. After you sign, you get a link to set up payouts with Stripe.\n\n"
        "Questions? Reach us at https://niltv.com/contact/\n\nNIL TV\n"
    )
    body = (
        f'<p style="margin:0 0 14px">Hi {html.escape(name)},</p>'
        '<p style="margin:0 0 14px">Thanks for applying to the NIL TV athlete program. We have your '
        "application and every update comes to this address.</p>"
        '<p style="margin:0 0 6px;font-weight:700">What happens next</p>'
        '<ol style="margin:0 0 18px;padding-left:22px"><li style="margin:0 0 6px">NIL TV reviews your application.</li>'
        '<li style="margin:0 0 6px">If you are accepted, you get the NIL TV Ambassador Agreement to sign electronically.</li>'
        '<li style="margin:0">After you sign, you get a link to set up payouts with Stripe.</li></ol>'
        f'<p style="{_MUTED};margin:0 0 10px">Questions? <a href="https://niltv.com/contact/" style="color:#111">Contact NIL TV</a>.</p>'
        f'<p style="{_MUTED};margin:0">NIL TV</p>'
    )
    return _send(to, subject, text, body, preheader="We have your application. Here is what happens next.")


def send_declined(to: str, first_name: str) -> bool:
    name = first_name or "there"
    subject = "Your NIL TV application"
    text = (
        f"Hi {name},\n\nThank you for applying to the NIL TV ambassador program. We are not able "
        "to bring you on right now. We keep applications on file and will reach out if that "
        "changes.\n\nNIL TV\n"
    )
    body = (
        f'<p style="margin:0 0 14px">Hi {html.escape(name)},</p>'
        '<p style="margin:0 0 18px">Thank you for applying to the NIL TV ambassador program. We are not '
        "able to bring you on right now. We keep applications on file and will reach out if that changes.</p>"
        f'<p style="{_MUTED};margin:0">NIL TV</p>'
    )
    return _send(to, subject, text, body)


def notify_staff_new_applicant(summary: str, dashboard_url: str) -> bool:
    to = get_settings().applications_notify_email
    if not to:
        return False
    text = f"New athlete application:\n\n{summary}\n\nReview: {dashboard_url}\n"
    body = (
        '<p style="margin:0 0 12px;font-weight:700">New athlete application</p>'
        f'<pre style="font-size:13px;line-height:1.5;white-space:pre-wrap;margin:0 0 20px">{html.escape(summary)}</pre>'
        f'<p style="margin:0"><a href="{html.escape(dashboard_url)}" style="{_BTN}">Review in the dashboard</a></p>'
    )
    return _send(to, "New NIL TV athlete application", text, body)
