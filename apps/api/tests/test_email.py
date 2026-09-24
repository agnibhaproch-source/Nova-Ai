from app.services.email_service import _html


def test_reset_email_html_has_escaped_button_link() -> None:
    html = _html(
        "reset_password", {"name": "<Ana>", "link": "https://nova.test/reset-password?token=a&b=1"}
    )
    assert html is not None
    assert '<a href="https://nova.test/reset-password?token=a&amp;b=1"' in html
    assert ">Reset password</a>" in html
    assert "&lt;Ana&gt;" in html and "<Ana>" not in html


def test_templates_without_a_link_are_text_only() -> None:
    assert _html("reset_password", {"name": "Ana"}) is None
