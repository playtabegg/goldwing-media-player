"""Fetch the installer the feed named, and prove it is the one named."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .feed import FeedProblem, Fetch, Release, fetch_bytes
from .minisig import PublicKey, verify_any

INSTALLER_NAME = "wti-player-setup.exe"


class DownloadProblem(Exception):
    """``str(problem)`` is the sentence."""


def download_installer(
    release: Release,
    dest_dir: Path,
    pubs: list[PublicKey],
    *,
    fetch: Fetch = fetch_bytes,
) -> Path:
    """The installer on disk, verified by size, SHA-256 and signature, or
    :class:`DownloadProblem` and nothing left behind."""
    try:
        data = fetch(release.url, release.size)
    except FeedProblem as problem:
        raise DownloadProblem(str(problem)) from problem
    if len(data) != release.size:
        raise DownloadProblem("The download was not the size the release named.")
    if hashlib.sha256(data).hexdigest() != release.sha256:
        raise DownloadProblem("The download does not match the release's checksum.")
    if not verify_any(data, release.signature, pubs):
        raise DownloadProblem("The download is not signed by We The Indies.")
    if not release.url.lower().endswith(".exe"):
        raise DownloadProblem("The release named a file Goldwing will not run.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Our own name, never the feed's: the folder is fresh, and a name is
    # the one thing here that could reach the file system unverified.
    path = dest_dir / INSTALLER_NAME
    path.write_bytes(data)
    return path
