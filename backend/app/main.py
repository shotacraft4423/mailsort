from __future__ import annotations

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
from app.db import session as db_session
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    _load_enabled_plugins()
    yield


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
