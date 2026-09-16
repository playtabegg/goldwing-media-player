"""U2: one check, one sentence, and the version rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit._sign import Signer
from tests.unit.test_update_feed import ARTIFACT, make_feed
from wti_player.update._semver import vercmp
from wti_player.update.check import check_for_update
from wti_player.update.feed import FeedProblem
from wti_player.update.minisig import parse_public_key


@pytest.fixture(autouse=True)
def _isolated_floor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A check must not write the sequence floor into the real profile."""
    monkeypatch.setattr(
        "wti_player.update.floor.default_path",
        lambda: tmp_path / "last-seen-version",
    )


@pytest.fixture
def signer() -> Signer:
    return Signer()


def fetcher(signer: Signer, feed: dict):
    raw = (json.dumps(feed, indent=2, sort_keys=True) + "\n").encode()
    sig = signer.minisig(raw)

    def fetch(url: str, cap: int) -> bytes:
        return sig.encode() if url.endswith(".minisig") else raw

    return fetch


def pubs(signer: Signer):
    key = parse_public_key(signer.pub_line)
    assert key is not None
    return [key]


class TestVersionRule:
    def test_vercmp(self) -> None:
        assert vercmp("1.2.0", "1.0.0") == 1
        assert vercmp("1.0.0", "1.0.0") == 0
        assert vercmp("1.0", "1.0.0") == 0
        assert vercmp("0.9.9", "1.0.0") == -1

    def test_newer_offers_and_same_or_older_does_not(self, signer: Signer) -> None:
        ends = ("https://github.com/a/latest.json",)
        out = check_for_update("1.0.0", endpoints=ends, pubs=pubs(signer), fetch=fetcher(signer, make_feed(signer)))
        assert out.newer and out.release is not None and out.release.version == "1.2.0"
        assert "1.2.0 is out" in out.sentence and "You have 1.0.0" in out.sentence

        out = check_for_update("1.2.0", endpoints=ends, pubs=pubs(signer), fetch=fetcher(signer, make_feed(signer)))
        assert not out.newer and out.sentence == "You have the newest Goldwing, 1.2.0."

        out = check_for_update("2.0.0", endpoints=ends, pubs=pubs(signer), fetch=fetcher(signer, make_feed(signer)))
        assert not out.newer

    def test_a_build_below_the_floor_is_told_to_download_fresh(self, signer: Signer) -> None:
        feed = make_feed(signer, min_upgradable_from="1.1.0")
        out = check_for_update("1.0.0", endpoints=("https://github.com/a/latest.json",), pubs=pubs(signer), fetch=fetcher(signer, feed))
        assert not out.newer
        assert "older than 1.1.0" in out.sentence


class TestSequenceFloor:
    def test_a_signed_older_feed_is_refused_after_a_newer_one_was_seen(
        self, signer: Signer, tmp_path: Path
    ) -> None:
        ends = ("https://github.com/a/latest.json",)
        keys = pubs(signer)
        mark = tmp_path / "floor" / "last-seen-version"

        first = check_for_update(
            "1.0.0",
            endpoints=ends,
            pubs=keys,
            fetch=fetcher(signer, make_feed(signer, version="1.0.2")),
            floor_path=mark,
        )
        assert first.newer and first.release is not None and first.release.version == "1.0.2"
        assert mark.read_text(encoding="ascii").strip() == "1.0.2"

        out = check_for_update(
            "1.0.0",
            endpoints=ends,
            pubs=keys,
            fetch=fetcher(signer, make_feed(signer, version="1.0.1")),
            floor_path=mark,
        )
        assert not out.newer
        assert out.release is None
        assert "1.0.1" in out.sentence and "1.0.2" in out.sentence


class TestOneSentence:
    def test_no_key_never_fetches(self) -> None:
        def fetch(url: str, cap: int) -> bytes:
            raise AssertionError("fetched without a key")

        out = check_for_update("1.0.0", pubs=[], fetch=fetch)
        assert out.sentence.startswith("This build carries no release key")
        assert not out.newer

    def test_the_default_keys_hold_the_ceremony_key_so_the_default_check_fetches(self) -> None:
        from wti_player.update import keys

        asked: list[str] = []

        def fetch(url: str, cap: int) -> bytes:
            asked.append(url)
            raise FeedProblem("Could not reach the release server.")

        out = check_for_update("1.0.0", fetch=fetch)
        assert asked[0] == keys.ENDPOINTS[0]
        assert not out.newer
        assert not out.sentence.startswith("This build carries no release key")

    def test_an_outage_is_a_sentence(self, signer: Signer) -> None:
        def fetch(url: str, cap: int) -> bytes:
            raise FeedProblem("Could not reach the release server.")

        out = check_for_update("1.0.0", endpoints=("https://github.com/a/latest.json",), pubs=pubs(signer), fetch=fetch)
        assert out.sentence == "Could not reach the release server."

    def test_a_forged_feed_is_a_sentence(self, signer: Signer) -> None:
        forged = Signer()
        out = check_for_update("1.0.0", endpoints=("https://github.com/a/latest.json",), pubs=pubs(signer), fetch=fetcher(forged, make_feed(forged)))
        assert out.sentence == "The release feed is not signed by We The Indies."
        assert not out.newer

    def test_every_sentence_ends_with_a_full_stop(self, signer: Signer) -> None:
        cases = [
            check_for_update("1.0.0", pubs=[], fetch=lambda u, c: b""),
            check_for_update("1.0.0", endpoints=("https://github.com/a/latest.json",), pubs=pubs(signer), fetch=fetcher(signer, make_feed(signer))),
        ]
        for out in cases:
            assert out.sentence.endswith(".")
            assert "Traceback" not in out.sentence

    def test_the_artifact_bytes_are_never_fetched_by_a_check(self, signer: Signer) -> None:
        urls: list[str] = []
        inner = fetcher(signer, make_feed(signer))

        def fetch(url: str, cap: int) -> bytes:
            urls.append(url)
            return inner(url, cap)

        check_for_update("1.0.0", endpoints=("https://github.com/a/latest.json",), pubs=pubs(signer), fetch=fetch)
        assert not any(url.endswith(".exe") for url in urls)
        assert ARTIFACT  # the fixture exists; a check must not touch it
