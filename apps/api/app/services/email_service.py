"""Transactional email via SMTP (docs/04 §12). Runs in the worker."""

from __future__ import annotations

from email.message import EmailMessage
from html import escape

import aiosmtplib

from app.core.config import get_settings

TEMPLATES: dict[str, tuple[str, str]] = {
    "reset_password": (
        "Reset your NOVA AI password",
        "Hi {name},\n\nReset your password using this link:\n\n{link}\n\n"
        "This link expires in 60 minutes. If you didn't request this, ignore this email.",
    ),
}


# Button label per template for the HTML part (the plain-text part stays for text-only clients).
BUTTONS: dict[str, str] = {"reset_password": "Reset password"}


_WRAP = (
    "max-width:480px;margin:0 auto;padding:32px 24px;color:#1f2330;"
    "font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif"
)
_BUTTON = (
    "background:#5b5bd6;color:#fff;text-decoration:none;padding:12px 22px;"
    "border-radius:8px;font-weight:600;display:inline-block"
)


def _paragraphs(text: str, params: dict[str, str]) -> str:
    parts = [p.strip().format(**params) for p in text.split("\n\n") if p.strip()]
    return "".join(f'<p style="margin:0 0 16px">{escape(p)}</p>' for p in parts)


def _html(template: str, params: dict[str, str]) -> str | None:
    label, link = BUTTONS.get(template), params.get("link")
    if not label or not link:
        return None
    subject, body = TEMPLATES[template]
    intro, _, outro = body.partition("{link}")
    href = escape(link, quote=True)
    return (
        f'<!doctype html><html><body style="margin:0;background:#f4f4f7"><div style="{_WRAP}">'
        f'<h1 style="font-size:20px;margin:0 0 20px">{escape(subject)}</h1>'
        f"{_paragraphs(intro, params)}"
        f'<p style="margin:24px 0"><a href="{href}" style="{_BUTTON}">{label}</a></p>'
        f"{_paragraphs(outro, params)}"
        '<p style="font-size:12px;color:#6b6f80;word-break:break-all">'
        f"Button not working? Paste this link into your browser:<br>{href}</p>"
        "</div></body></html>"
    )


async def send_template(to: str, template: str, **params: str) -> None:
    s = get_settings()
    subject, body = TEMPLATES[template]
    msg = EmailMessage()
    msg["From"] = s.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body.format(**params))
    if html := _html(template, params):
        msg.add_alternative(html, subtype="html")
    await aiosmtplib.send(
        msg,
        hostname=s.SMTP_HOST,
        port=s.SMTP_PORT,
        username=s.SMTP_USERNAME,
        password=s.SMTP_PASSWORD.get_secret_value() if s.SMTP_PASSWORD else None,
        # Port 465 speaks TLS from the first byte; 587 upgrades with STARTTLS.
        use_tls=s.SMTP_USE_TLS and s.SMTP_PORT == 465,
        start_tls=s.SMTP_USE_TLS and s.SMTP_PORT != 465,
        timeout=15,
    )
