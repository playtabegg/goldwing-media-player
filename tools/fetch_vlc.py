"""Fetch the pinned VLC runtime into ``vendor/vlc``.

The Player links libvlc at run time. We do not commit 80 MB of VideoLAN's
binaries; we pin the version and the SHA-256 here and let this script put
them in place. Run it once after cloning::

    python tools/fetch_vlc.py

The layout it produces is the one ``wti_player.engine.libvlc_loader``
looks for first::

    vendor/vlc/libvlc.dll
    vendor/vlc/libvlccore.dll
    vendor/vlc/plugins/...

Options:
  --zip PATH   use an already-downloaded archive instead of the network
  --force      re-extract even if vendor/vlc already looks complete
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VLC_VERSION = "3.0.23"
VLC_ARCHIVE = f"vlc-{VLC_VERSION}-win64.zip"
VLC_URL = f"https://get.videolan.org/vlc/{VLC_VERSION}/win64/{VLC_ARCHIVE}"
VLC_SHA256 = "992d19dbd0b8a7cde9167d2f7780b1ef6f92acc8a71acfa736101a21f35181e1"

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "vendor"
TARGET = VENDOR / "vlc"
CACHE = VENDOR / "_cache"

#: What "already installed" means. Checked before and after extraction.
REQUIRED = ("libvlc.dll", "libvlccore.dll", "plugins")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_installed(target: Path = TARGET) -> bool:
    return all((target / name).exists() for name in REQUIRED)


def download(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {VLC_URL}")
    with urllib.request.urlopen(VLC_URL, timeout=120) as response:
        with dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    return dest


def verify(archive: Path) -> None:
    actual = _sha256(archive)
    if actual != VLC_SHA256:
        raise SystemExit(
            f"checksum mismatch for {archive.name}\n  expected {VLC_SHA256}\n  got      {actual}"
        )
    print(f"sha256 ok  {actual}")


def extract(archive: Path, target: Path) -> None:
    """Unpack ``vlc-<version>/`` from the archive straight into ``target``."""
    prefix = f"vlc-{VLC_VERSION}/"
    if target.exists():
        shutil.rmtree(target)
    with tempfile.TemporaryDirectory(dir=str(target.parent)) as staging_name:
        staging = Path(staging_name)
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.namelist() if m.startswith(prefix)]
            if not members:
                raise SystemExit(f"{archive.name} does not contain {prefix}")
            zf.extractall(staging, members)
        (staging / f"vlc-{VLC_VERSION}").rename(target)
    removed = strip_descrambler(target)
    print(f"extracted -> {target}")
    if removed:
        print("  removed the DVD plugins: " + ", ".join(removed))


def strip_descrambler(target: Path) -> list[str]:
    """Delete VideoLAN's DVD plugins from the vendored runtime.

    They have libdvdcss compiled into them. The build already refuses to
    package them, so a shipped Player has never had one — but a source
    checkout did, which meant a developer's Player could descramble a
    commercial DVD and a customer's could not.

    Two things wrong with that. It is a difference between what we test and
    what we ship, in exactly the place where being wrong is expensive. And a
    working copy of this repository should not contain a lock-breaker at all,
    which is a simpler thing to be able to say.
    """
    removed: list[str] = []
    plugins = target / "plugins"
    if not plugins.is_dir():
        return removed
    for name in ("libdvdread_plugin.dll", "libdvdnav_plugin.dll"):
        for found in plugins.rglob(name):
            try:
                found.unlink()
                removed.append(name)
            except OSError as error:
                print(f"  could not remove {found}: {error}")
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, help="use this archive instead of downloading")
    parser.add_argument("--force", action="store_true", help="re-extract even if present")
    args = parser.parse_args(argv)

    if is_installed() and not args.force:
        print(f"vendor/vlc already has VLC (use --force to replace it): {TARGET}")
        return 0

    archive = args.zip or (CACHE / VLC_ARCHIVE)
    if not archive.exists():
        download(archive)
    verify(archive)
    VENDOR.mkdir(parents=True, exist_ok=True)
    extract(archive, TARGET)

    if not is_installed():
        missing = [n for n in REQUIRED if not (TARGET / n).exists()]
        raise SystemExit(f"extraction incomplete, missing: {', '.join(missing)}")
    (VENDOR / "VLC-VERSION.txt").write_text(f"{VLC_VERSION}\n{VLC_SHA256}\n", encoding="utf-8")
    print(f"VLC {VLC_VERSION} ready at {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
