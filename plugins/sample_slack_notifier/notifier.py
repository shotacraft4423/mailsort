"""Reference plugin: posts to a Slack Incoming Webhook when a message is
classified as 重要 or 要返信. This is the pattern every plugin follows —
implement the hooks you care about, read config from the dict passed to
__init__ (populated from PluginConfig.config_json_encrypted by
plugin_manager.reload_plugins), and never import anything from `app.db` /
`app.services` (plugins only ever see plain dicts, per DESIGN.md section 7).
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any


class SlackNotifierPlugin:
    NOTIFY_LABELS = {"重要", "要返信"}

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.webhook_url = (config or {}).get("webhook_url", "")

    def on_message_classified(self, message: dict[str, Any], classification: dict[str, Any]) -> None:
        if not self.webhook_url:
            return
        labels = {c["label"] for c in classification.get("categories", [])}
        if not labels & self.NOTIFY_LABELS:
            return

        payload = {
            "text": (
                f"[MailSort] {classification.get('mail_type', '')} "
                f"「{message.get('subject', '(件名なし)')}」({message.get('sender_address', '')})"
            )
        }
        request = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request, timeout=5)  # noqa: S310 - fixed https webhook URL from plugin config

    def on_meeting_extracted(self, meeting: dict[str, Any]) -> None:
        pass
