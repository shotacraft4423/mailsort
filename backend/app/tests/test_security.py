from __future__ import annotations

from app.core.security import decrypt_secret, encrypt_secret, mask_text


def test_encrypt_decrypt_round_trip():
    token = encrypt_secret("super-secret-imap-password")
    assert token != "super-secret-imap-password"
    assert decrypt_secret(token) == "super-secret-imap-password"


def test_encrypted_token_is_not_trivially_reversible():
    token = encrypt_secret("hunter2")
    assert "hunter2" not in token


def test_key_file_is_created_and_reused_across_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("MAILSORT_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()

    token_a = encrypt_secret("value-a")
    key_path = tmp_path / "secret.key"
    assert key_path.exists()
    first_key = key_path.read_bytes()

    token_b = encrypt_secret("value-b")
    assert key_path.read_bytes() == first_key  # key wasn't regenerated on the second call

    assert decrypt_secret(token_a) == "value-a"
    assert decrypt_secret(token_b) == "value-b"


def test_mask_text_replaces_email_and_long_phone_numbers():
    masked = mask_text("連絡先は tanaka@example.com / 03-1234-5678 です。")
    assert "tanaka@example.com" not in masked
    assert "03-1234-5678" not in masked
    assert "[EMAIL_" in masked
    assert "[PHONE_" in masked
