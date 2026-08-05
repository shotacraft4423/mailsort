"""Anonymization / masking helpers used before any content leaves the
process toward an external LLM API, plus at-rest encryption for stored
secrets (account passwords, plugin tokens) via `cryptography`'s Fernet
(AES-128-CBC + HMAC, authenticated encryption).

Key management: if `MAILSORT_SECRET_KEY` is set (e.g. injected by a secret
manager in a team/server deployment), it is used directly. Otherwise a key
is generated on first use and persisted to `<data_dir>/secret.key` with
owner-only permissions — appropriate for the local-first desktop use case,
where "at rest" means "on this machine's disk" rather than a shared server.
Production hardening (OS keychain / DPAPI / libsecret integration so the
key itself isn't a plain file) is tracked as a Phase 3 item in DESIGN.md.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-\s]?)?(?:\(?\d{2,4}\)?[-\s]?){2,4}\d{3,4}")
_URL_RE = re.compile(r"https?://\S+")


def mask_text(text: str, *, mask_emails: bool = True, mask_phones: bool = True, mask_urls: bool = False) -> str:
    """Replace PII-ish substrings with stable placeholder tokens.

    Placeholders are stable per-value (hash-derived) so an LLM can still
    reason about "the same email appears twice in this thread" without ever
    seeing the real value.
    """
    result = text
    if mask_emails:
        result = _EMAIL_RE.sub(lambda m: f"[EMAIL_{_short_hash(m.group())}]", result)
    if mask_phones:
        result = _PHONE_RE.sub(lambda m: f"[PHONE_{_short_hash(m.group())}]" if len(re.sub(r"\D", "", m.group())) >= 8 else m.group(), result)
    if mask_urls:
        result = _URL_RE.sub(lambda m: f"[URL_{_short_hash(m.group())}]", result)
    return result


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def content_hash(*parts: str) -> str:
    """Stable hash used to key the AI analysis cache (see AIAnalysis.content_hash)."""
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _key_file_path() -> Path:
    # Imported lazily to avoid a security.py <-> config.py import cycle at
    # module load time (config.py has no reason to import security.py, but
    # keeping the dependency one-directional and lazy here is cheap safety).
    from app.core.config import get_settings

    return get_settings().ensure_data_dir() / "secret.key"


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("MAILSORT_SECRET_KEY")
    if env_key:
        return env_key.encode("ascii")

    key_path = _key_file_path()
    if key_path.exists():
        return key_path.read_bytes()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600; best-effort, no-op semantics differ on Windows
    except OSError:
        pass
    return key


def _get_fernet() -> Fernet:
    # Deliberately not cached at module scope: key material can change
    # between calls in tests (isolated data_dir per test) and the cost of
    # re-reading a 44-byte key file is negligible next to an LLM round trip.
    return Fernet(_load_or_create_key())


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("stored secret could not be decrypted with the current key") from exc


def verify_hmac(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
