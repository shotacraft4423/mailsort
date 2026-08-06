from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmailAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A connected mailbox. protocol distinguishes the connector implementation
    used by services/mail/*_client.py (IMAP/SMTP, Gmail API, Microsoft Graph)."""

    __tablename__ = "email_accounts"

    display_name: Mapped[str] = mapped_column(String(255))
    email_address: Mapped[str] = mapped_column(String(255), index=True)
    protocol: Mapped[str] = mapped_column(String(32))  # imap_smtp | gmail_api | ms_graph
    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    # Encrypted via app.core.security.encrypt_secret before storage.
    credential_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Privacy: allow pinning an account (e.g. a highly sensitive client) to a
    # local-only LLM provider regardless of the global default.
    forced_llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    messages: Mapped[list["Message"]] = relationship(back_populates="account")


class Thread(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "threads"

    subject_normalized: Mapped[str] = mapped_column(String(998), index=True)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_accounts.id"))

    messages: Mapped[list["Message"]] = relationship(back_populates="thread")


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Core mail entity. Deliberately AI-independent: every AI-derived field
    lives in AIAnalysis (1:1, nullable FK) so the mailbox is fully usable
    with AI disabled or unreachable."""

    __tablename__ = "messages"

    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_accounts.id"), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("threads.id"), nullable=True, index=True)

    message_uid: Mapped[str] = mapped_column(String(255), index=True)  # protocol-native id (IMAP UID, Graph id, ...)
    folder: Mapped[str] = mapped_column(String(255), default="INBOX")

    subject: Mapped[str] = mapped_column(String(998), default="")
    sender_name: Mapped[str] = mapped_column(String(255), default="")
    sender_address: Mapped[str] = mapped_column(String(255), default="", index=True)
    to_addresses: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    cc_addresses: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_html: Mapped[str] = mapped_column(Text, default="")
    signature_text: Mapped[str] = mapped_column(Text, default="")

    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)

    account: Mapped[EmailAccount] = relationship(back_populates="messages")
    thread: Mapped[Thread | None] = relationship(back_populates="messages")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="message", cascade="all, delete-orphan")

    @property
    def account_email_address(self) -> str:
        """Which of the user's configured mailboxes this message belongs
        to — with only one account this was never ambiguous, but adding a
        second (or third) makes "which address did this arrive at" a real
        question the mail list/detail views had no way to answer."""
        return self.account.email_address if self.account else ""


class Attachment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "attachments"

    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Populated by services/attachment_analysis (Phase 2): resume/skill-sheet/
    # project-brief/invoice/contract classification + OCR text.
    classified_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped[Message] = relationship(back_populates="attachments")
