from __future__ import annotations

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
from app.db.session import init_db

app = FastAPI(title="MailSort", description="AI-native email client backend for SES sales teams")

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


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
