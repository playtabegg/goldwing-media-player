"""One check, one sentence.

After a signed feed parses, its version is kept if it is newer than the
last one this machine has seen. A signed feed older than that mark is
not offered, even when it is newer than the running build. First run
has no mark: that feed is accepted and written as today's.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..version import VERSION
from . import keys as trust
from ._semver import vercmp
from .feed import FeedProblem, Fetch, FetchLog, Release, fetch_bytes, fetch_release
from .floor import default_path, raise_floor
from .minisig import PublicKey


@dataclass(frozen=True)
class Outcome:
    #: What the person is told. Always a sentence.
    sentence: str
    #: The verified release, when there is a newer one.
    release: Release | None = None

    @property
    def newer(self) -> bool:
        return self.release is not None


def no_key_sentence() -> str:
    return (
        "This build carries no release key, so it cannot check for a new one. "
        "A fresh Goldwing is at wetheindies.com/player."
    )


def up_to_date_sentence(version: str) -> str:
    return f"You have the newest Goldwing, {version}."


def newer_sentence(version: str, running: str) -> str:
    return f"Goldwing {version} is out. You have {running}."


def too_old_sentence(version: str, floor: str) -> str:
    return (
        f"Goldwing {version} is out, but this build is older than {floor} and "
        "cannot step to it. Download it fresh from the website."
    )


def rolled_back_sentence(version: str, seen: str) -> str:
    return (
        f"The release feed names {version}, but this Player has already "
        f"seen {seen}."
    )


def check_for_update(
    running: str = VERSION,
    *,
    endpoints: tuple[str, ...] = trust.ENDPOINTS,
    pubs: list[PublicKey] | None = None,
    fetch: Fetch = fetch_bytes,
    log: FetchLog | None = None,
    floor_path: Path | None = None,
) -> Outcome:
    keys = trust.trusted_keys() if pubs is None else pubs
    if not keys:
        return Outcome(no_key_sentence())
    try:
        release = fetch_release(endpoints, keys, fetch=fetch, log=log)
    except FeedProblem as problem:
        return Outcome(str(problem))
    mark = floor_path if floor_path is not None else default_path()
    seen = raise_floor(mark, release.version)
    # A still-validly-signed older feed must not be offered, even when it
    # is newer than the running build. First run has no mark: raise_floor
    # writes today's version and we continue.
    if seen is not None and vercmp(release.version, seen) < 0:
        return Outcome(rolled_back_sentence(release.version, seen))
    if vercmp(release.version, running) <= 0:
        return Outcome(up_to_date_sentence(running))
    floor = release.min_upgradable_from
    if floor and vercmp(running, floor) < 0:
        return Outcome(too_old_sentence(release.version, floor))
    return Outcome(newer_sentence(release.version, running), release)
