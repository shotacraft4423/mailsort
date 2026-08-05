"""Regression coverage: plugin_manager's loaded-plugin registry is an
in-memory module global. Before this fix, a plugin enabled via
PUT /plugins/{key} would persist in PluginConfig but the in-memory registry
reset to empty on every process restart — dispatch_message_classified would
silently do nothing until someone re-toggled the plugin through the API.
main.py's lifespan now reloads enabled plugins from PluginConfig on
startup; this simulates a restart by resetting plugin_manager's module
state and re-running that startup step directly.
"""
from __future__ import annotations

import json
import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_enabled_plugin_survives_a_simulated_restart(monkeypatch):
    # The plugin is loaded dynamically via importlib.util (see
    # plugin_manager._load_entrypoint) under a synthetic module name, so it
    # can't be patched by its source-tree dotted path — patch the stdlib
    # call it makes instead (urllib.request.urlopen), which is the same
    # module object regardless of how the caller was imported.
    calls: list[bytes] = []

    def _fake_urlopen(request, timeout=5):
        calls.append(request.data)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    with _make_client() as client:
        resp = client.put(
            "/plugins/sample_slack_notifier",
            json={"is_enabled": True, "config": {"webhook_url": "https://example.com/hook"}},
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is True

    # Simulate a process restart: plugin_manager's in-memory registry is a
    # module global, so wipe it exactly like a fresh interpreter would, then
    # re-run the same startup step main.py's lifespan performs.
    from app.services import plugin_manager
    from app.main import _load_enabled_plugins

    plugin_manager._registry = plugin_manager.PluginRegistry()
    assert plugin_manager.get_registry().instances == {}

    _load_enabled_plugins()

    assert "sample_slack_notifier" in plugin_manager.get_registry().instances

    plugin_manager.dispatch_message_classified(
        {"id": "m1", "subject": "重要な案件", "sender_address": "a@b.com"},
        {"categories": [{"label": "重要", "confidence": 0.9}]},
    )
    assert len(calls) == 1
    assert "重要な案件" in json.loads(calls[0])["text"]
