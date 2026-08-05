"""Anonymization / masking helpers used before any content leaves the
process toward an external LLM API, plus a tiny symmetric-encryption helper
for at-rest secrets (account passwords, plugin tokens).

This is intentionally dependency-light (stdlib regex + hashlib) so the
scaffold runs offline without extra packages. A production build should
swap `mask_text` for a proper NER-based redactor and `encrypt_secret` for an
OS-keychain-backed key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

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


def _get_key() -> bytes:
    # Placeholder key material. Production: derive from OS keychain /
    # DPAPI (Windows) / libsecret (Linux), never a hardcoded env default.
    secret = os.environ.get("MAILSORT_SECRET_KEY", "dev-only-insecure-key").encode("utf-8")
    return hashlib.sha256(secret).digest()


def encrypt_secret(plaintext: str) -> str:
    """XOR-with-keystream placeholder encryption (NOT for production use).

    Kept dependency-free for the scaffold; swap for `cryptography`'s Fernet
    before storing real account credentials.
    """
    key = _get_key()
    keystream = hashlib.sha256(key).digest() * (len(plaintext.encode()) // 32 + 1)
    data = plaintext.encode("utf-8")
    xored = bytes(a ^ b for a, b in zip(data, keystream))
    return base64.urlsafe_b64encode(xored).decode("ascii")


def decrypt_secret(token: str) -> str:
    key = _get_key()
    data = base64.urlsafe_b64decode(token.encode("ascii"))
    keystream = hashlib.sha256(key).digest() * (len(data) // 32 + 1)
    xored = bytes(a ^ b for a, b in zip(data, keystream))
    return xored.decode("utf-8")


def verify_hmac(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
