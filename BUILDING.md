# Building Goldwing Media Player from source

These instructions are for contributors. The released Windows installer
already includes the Player and its playback libraries; normal users do not
need Python, a separate VLC installation or these commands.

## Run from source

```powershell
python -m pip install -e ".[dev]"
python tools/fetch_vlc.py
python Player.pyw
```

The VLC fetch checks the pinned version/hash and prepares the Player's
permitted runtime. A standard system VLC containing CSS-enabled DVD plugins
is refused; use the prepared runtime.

## Check and build

```powershell
python tools/make_fixtures.py
python -m pytest tests/unit -q
python -m ruff check .
python tools/build_exe.py --clean
python tools/build_installer.py
python tools/licence_notice.py --check
```

Media fixtures are generated locally and excluded from Git. Tests requiring
unavailable media/runtime skip with instructions; check the skip summary.
If testing alongside a website worktree, set `WTI_TEST_WEB_ROOT` to that
checkout's root to cross-check its public source link against the update feed.
Otherwise this optional cross-project check uses a sibling `wetheindies-web`.

Inno Setup 6 is required to build the Windows installer. Builds are unsigned
until the separate signing step in [RELEASING.md](RELEASING.md). Optional
showcase tools may need Pillow, OpenCV, FFmpeg or tsMuxeR; these are not Player
runtime dependencies.
