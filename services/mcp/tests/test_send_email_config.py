from app.send_email import smtp_config_from_env


def test_smtp_port_numeric_string(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_FROM", "MH Skills Coach <noreply@example.com>")

    config = smtp_config_from_env()

    assert config["port"] == 2525


def test_smtp_port_numeric_string_with_trailing_space(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
    monkeypatch.setenv("SMTP_PORT", "2525 ")
    monkeypatch.setenv("SMTP_FROM", "MH Skills Coach <noreply@example.com>")

    config = smtp_config_from_env()

    assert config["port"] == 2525
