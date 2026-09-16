# Goldwing Media Player

**One player for We The Indies discs, Rialto discs and the supported discs you already own.**

Goldwing Media Player brings your disc's title, chapters and artwork together
with playback. Use it with discs made and distributed through We The Indies,
including compatible discs built with Rialto 1.5, and with supported unprotected
discs you already own. No account, telemetry or update nag.

## What you can use it for

- **We The Indies and Rialto movie and music discs:** play supported content and see the title,
  chapters, case and disc artwork supplied with the disc.
- **We The Indies and Rialto game discs:** open the disc's launcher/menu to install or start its
  game. The game runs through Windows; Goldwing is not a game emulator.
- **Unprotected DVD-Video:** watch titles, use supported disc menus and select
  chapters. DVD navigation is handled without a CSS descrambler.
- **Unprotected Blu-ray:** watch titles, use supported HDMV menus and select
  chapters. Java-based BD-J menus are not included; available titles can still
  be selected directly on supported discs.
- **Audio CDs:** play tracks and show CD-TEXT names when the disc supplies them.
- **Disc images and folders:** open supported ISO images, BDMV and VIDEO_TS
  folders from your computer.
- **Data and M-Disc archives:** browse the files on the disc.

Playback depends on a supported disc format, readable media and compatible
content. A Blu-ray drive is required for physical Blu-rays; other discs need
the appropriate drive. Games keep their own Windows/system requirements.

## Download and run

Windows 10 (1809 or later) or Windows 11, 64-bit. Get the installer from
[GitHub Releases](https://github.com/playtabegg/goldwing-media-player/releases).
The released installer is signed by **We The Indies, LLC**. Install for your
Windows user without an administrator prompt; it does not take over file
associations. Open a disc, image or folder from the Player.

**Mac and Linux versions are coming soon.** The current download is for Windows.

## Updates

Use **Help > Check for a new Goldwing** when you want to check. Goldwing verifies
the signed update feed, installer signature and hash before offering an update.
It asks before downloading/installing; it does not update on its own.
New versions use the same public release/feed addresses, so installed Players
can find future releases without reinstalling manually.

Maintainers: see [the release guide](RELEASING.md) for version bumps, tests,
signing, feed preparation and the separate publication checkpoints.

## Protected commercial discs and the roadmap

**CSS-protected DVDs and AACS-protected Blu-rays do not play in this release.**
Goldwing does not include a descrambler or claim licensed protected playback.
Installer code signing identifies the software publisher; it does not grant
DVD or Blu-ray content-protection licences.

Our plan is to add officially licensed playback for protected DVDs and
Blu-rays through the appropriate licensing and compliance processes. This
depends on obtaining licences, meeting their requirements and releasing an
update. No availability date or universal disc compatibility is promised.
See [DVD CCA](https://www.dvdcca.org/) and
[AACS licensing](https://aacsla.com/license-aacs/) for the respective processes.

## Build from source

```powershell
python -m pip install -e ".[dev]"
python tools/fetch_vlc.py
python Player.pyw
```

The VLC fetch checks the pinned version/hash and prepares the Player's
permitted runtime. A standard system VLC containing CSS-enabled DVD plugins
is refused; it is not a substitute for the prepared runtime.

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
Inno Setup 6 is required to build the installer. Builds are unsigned until the
separate signing step. Optional showcase tools may need Pillow, OpenCV,
FFmpeg or tsMuxeR; these are not Player runtime dependencies.

## Licence

Goldwing is free software under the **GNU General Public License, version 3
or later**. See [LICENSE](LICENSE). The installer carries the generated
third-party notice and licence texts; the release's source tag identifies the
corresponding Player source. Vendored runtime binaries, signing keys and
private disc libraries are excluded from this repository.
