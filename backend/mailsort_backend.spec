# PyInstaller spec for the MailSort backend.
#
# Run from backend/, with the `build` extra installed:
#   pip install -e ".[build]"
#   pyinstaller mailsort_backend.spec
#
# Output: dist/mailsort-backend(.exe) — a single-file executable with no
# Python installation required on the machine that runs it. This is what
# build_installer.ps1 copies into frontend/src-tauri/binaries/ as the
# Tauri sidecar (see src-tauri/src/main.rs).
#
# Onefile (not onedir) specifically because Tauri's sidecar/externalBin
# mechanism expects a single binary at a fixed path — bundling a whole
# onedir folder as a Tauri sidecar needs a different (resource-bundle)
# wiring that isn't worth the extra complexity for a first working
# installer. The tradeoff is a few hundred ms of self-extraction on every
# launch, which is a one-time cost paid once per app open, not per request.
from PyInstaller.utils.hooks import collect_submodules

# uvicorn selects its event loop / HTTP protocol implementation via runtime
# importlib lookups (uvicorn.loops.auto, uvicorn.protocols.http.auto, ...)
# rather than static imports PyInstaller's analysis can follow on its own —
# collect_submodules pulls in the whole package so whichever implementation
# uvicorn picks at runtime is actually present in the frozen build.
hiddenimports = collect_submodules("uvicorn")

a = Analysis(
    ["run_server.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Test-only / dev-only dependencies that pull in nothing the running
    # app needs, and only bloat the installer if left in.
    excludes=["pytest", "pytest_asyncio", "aiosmtpd"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mailsort-backend",
    debug=False,
    strip=False,
    upx=False,
    # Keeps a console attached so uvicorn's own stdout/stderr (startup log,
    # tracebacks) are actually visible/pipeable — useful while validating
    # the packaging pipeline itself. Tauri's sidecar spawn captures this
    # output into its own log rather than flashing a visible window in
    # practice, but if a console briefly flashes on launch in an early
    # build, that's cosmetic; switching to console=False is a safe
    # follow-up once the packaged app has been confirmed working end to
    # end on a real Windows machine.
    console=True,
)
