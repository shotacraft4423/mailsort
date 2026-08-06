from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    accounts,
    ai,
    candidates,
    chat,
    companies,
    contacts,
    dashboard,
    deals,
    mail,
    meetings,
    plugins,
    prompts,
    rules,
    search,
    settings as settings_routes,
)
from app.api.routes.plugins import PLUGINS_DIR, load_enabled_plugin_configs
from app.api.routes.settings import apply_env_patch
from app.db import session as db_session
from app.db.session import init_db
from app.services.settings_service import load_persisted_settings


_QUEUE_POLL_IDLE_SECONDS = 2.0


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    _load_persisted_settings()
    _load_enabled_plugins()
    worker_task = asyncio.create_task(_run_queue_worker())
    try:
        yield
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


async def _run_queue_worker() -> None:
    """Drains services/queue.py's AnalysisQueueItem backlog — the
    classification+extraction ("analyze") job every mail sync enqueues.
    Before this, the only thing that ever called queue.process_next() was
    POST /ai/queue/process, a manual/test-only route nothing in the app
    called automatically, so every synced message's automatic
    classification, extraction, and (via analysis_service) meeting-link
    detection silently sat in "pending" forever — the message list looked
    unclassified and the meeting tab stayed empty until someone manually
    clicked "AI分類を実行" on each message individually."""
    from app.services import queue

    while True:
        db = db_session.SessionLocal()
        try:
            item = await queue.process_next(db)
        except Exception:  # noqa: BLE001 - the worker loop must never die
            item = None
        finally:
            db.close()
        await asyncio.sleep(0 if item is not None else _QUEUE_POLL_IDLE_SECONDS)


def _load_persisted_settings() -> None:
    """GUI-configured settings (AI provider, API keys, UI language) are
    saved to the DB on every PUT /settings, but os.environ (which
    core.config.Settings actually reads) is reset on every process
    restart. Without this, a restart would silently fall back to
    local_mock/no API key even though the user had configured a real
    provider — see services/settings_service.py."""
    db = db_session.SessionLocal()
    try:
        persisted = load_persisted_settings(db)
    finally:
        db.close()
    if persisted:
        apply_env_patch(persisted)


def _load_enabled_plugins() -> None:
    """plugin_manager's loaded-plugin registry is in-memory; without this,
    a plugin enabled via PUT /plugins/{key} before a restart would be
    persisted in PluginConfig but silently not fire again until someone
    re-toggled it through the API.

    Looks up `db_session.SessionLocal` dynamically (module attribute, not
    `from app.db.session import SessionLocal`) rather than binding it once
    at import time — this module is imported exactly once per process in
    production so it wouldn't matter there, but a `from ... import` copy
    would go stale in any context that rebinds the session factory after
    import (which the test suite's per-test DB isolation does)."""
    from app.services import plugin_manager

    db = db_session.SessionLocal()
    try:
        enabled_configs = load_enabled_plugin_configs(db)
    finally:
        db.close()
    plugin_manager.reload_plugins(PLUGINS_DIR, enabled_configs)


app = FastAPI(title="MailSort", description="AI-native email client backend for SES sales teams", lifespan=lifespan)

# The Tauri shell talks to this API over localhost; CORS is wide open here
# because the backend never listens on a non-loopback interface in the
# desktop build. A team/server deployment should restrict this.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    accounts.router,
    mail.router,
    ai.router,
    companies.router,
    contacts.router,
    deals.router,
    candidates.router,
    meetings.router,
    search.router,
    chat.router,
    settings_routes.router,
    prompts.router,
    rules.router,
    plugins.router,
    dashboard.router,
):
    app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
