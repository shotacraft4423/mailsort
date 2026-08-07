"""Standalone entrypoint for the PyInstaller-frozen backend.

Not used by the normal dev workflow (`uvicorn app.main:app --reload`, see
README) — a frozen executable can't shell out to the `uvicorn` console
script the way a `pip install`'d environment can, so this starts the
server programmatically instead. This exact script is what
`build_installer.spec` freezes, and what the Tauri desktop shell spawns as
a sidecar process in the packaged build (see src-tauri/src/main.rs).
"""
from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> None:
    # PyInstaller sets sys.frozen=True on the frozen executable; nothing
    # else in the codebase needs to branch on it directly (all the paths
    # that matter — data_dir, database_url, secret.key — already resolve
    # through app.core.config.Settings regardless of how the process was
    # launched), but uvicorn's own import-string reload/multi-worker
    # machinery assumes a real source tree on disk, which a frozen build
    # doesn't have. Passing the app object directly (rather than the
    # "app.main:app" import string used in dev) sidesteps that, and
    # reload/workers are dev-only conveniences we don't want in a shipped
    # desktop app regardless.
    from app.main import app

    port = int(os.environ.get("MAILSORT_PORT", "8000"))

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    # Required on Windows before any other multiprocessing-using import
    # runs in a frozen executable, or launching the exe re-spawns itself
    # into an infinite loop of new processes instead of starting once.
    multiprocessing.freeze_support()
    # Tauri pipes the sidecar's stdout for its own log window; without
    # line buffering, uvicorn's startup log ("Uvicorn running on ...") can
    # sit in a block buffer and never show up there.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    main()
