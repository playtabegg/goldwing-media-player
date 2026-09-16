"""U2 (28 Aug 2026): the feed is trusted only when it verifies, and every
failure is one sentence. Negative controls for each rule.
"""

from __future__ import annotations

import json

import pytest

from tests.unit._sign import Signer
from wti_player.update import feed as feed_mod
from wti_player.update.feed import FeedProblem, FetchLog, fetch_release, parse_feed
from wti_player.update.keys import trusted_keys
from wti_player.update.minisig import parse_public_key, verify_bytes

ARTIFACT = b"MZ" + bytes(range(256)) * 10
URL = "https://github.com/playtabegg/goldwing-media-player/releases/download/v1.2.0/WeTheIndiesPlayer-Setup-1.2.0.exe"


def make_feed(signer: Signer, **over) -> dict:
    import hashlib

    base = {
        "schema": "wti.appcast/1",
        "app": "goldwing",
        "channel": "stable",
        "version": "1.2.0",
        "pub_date": "2026-09-16T14:03:00Z",
        "notes": "",
        "notes_url": "https://github.com/playtabegg/goldwing-media-player/releases/tag/v1.2.0",
        "min_upgradable_from": "1.0.0",
        "platforms": {
            "windows-x86_64": {
                "url": URL,
                "signature": signer.minisig(ARTIFACT),
                "sha256": hashlib.sha256(ARTIFACT).hexdigest(),
                "size": len(ARTIFACT),
                "installer": "inno",
                "args": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
            }
        },
    }
    base.update(over)
    return base


def signed(signer: Signer, feed: dict) -> tuple[bytes, str]:
    raw = (json.dumps(feed, indent=2, sort_keys=True) + "\n").encode()
    return raw, signer.minisig(raw)


@pytest.fixture
def signer() -> Signer:
    return Signer()


@pytest.fixture
def pubs(signer: Signer):
    key = parse_public_key(signer.pub_line)
    assert key is not None
    return [key]


class TestMinisig:
    def test_a_signature_verifies_and_a_flipped_byte_does_not(self, signer: Signer, pubs) -> None:
        sig = signer.minisig(ARTIFACT)
        assert verify_bytes(ARTIFACT, sig, pubs[0])
        assert not verify_bytes(ARTIFACT + b"x", sig, pubs[0])
        assert not verify_bytes(ARTIFACT, sig.replace("trusted comment: timestamp:0", "trusted comment: timestamp:1"), pubs[0])

    def test_the_legacy_unhashed_tag_is_refused(self, signer: Signer, pubs) -> None:
        assert not verify_bytes(ARTIFACT, signer.minisig(ARTIFACT, alg=b"Ed"), pubs[0])

    def test_another_key_id_is_refused_before_any_maths(self, signer: Signer) -> None:
        other = Signer(seed=signer.seed)  # same seed, different id
        key = parse_public_key(other.pub_line)
        assert key is not None
        assert not verify_bytes(ARTIFACT, signer.minisig(ARTIFACT), key)

    def test_malformed_never_raises(self, pubs) -> None:
        for text in ("", "one\ntwo", "a\nb\nc\nd", "x\n%%%\ntrusted comment: t\n%%%\n"):
            assert verify_bytes(ARTIFACT, text, pubs[0]) is False
        assert parse_public_key("nope") is None
        assert parse_public_key("") is None


class TestParseFeed:
    def test_a_signed_feed_becomes_a_release(self, signer: Signer, pubs) -> None:
        raw, sig = signed(signer, make_feed(signer))
        release = parse_feed(raw, sig, pubs)
        assert release.version == "1.2.0"
        assert release.url == URL
        assert release.size == len(ARTIFACT)
        assert release.args[0] == "/VERYSILENT"
        assert release.min_upgradable_from == "1.0.0"

    def test_no_keys_means_no_check(self, signer: Signer) -> None:
        raw, sig = signed(signer, make_feed(signer))
        with pytest.raises(FeedProblem, match="carries no release key"):
            parse_feed(raw, sig, [])

    def test_the_wrong_key_is_not_ours(self, signer: Signer) -> None:
        raw, sig = signed(signer, make_feed(signer))
        stranger = parse_public_key(Signer().pub_line)
        assert stranger is not None
        with pytest.raises(FeedProblem, match="not signed by We The Indies"):
            parse_feed(raw, sig, [stranger])

    def test_a_tampered_feed_fails_before_it_is_parsed(self, signer: Signer, pubs) -> None:
        raw, sig = signed(signer, make_feed(signer))
        raw = raw.replace(b'"1.2.0"', b'"9.9.9"')
        with pytest.raises(FeedProblem, match="not signed"):
            parse_feed(raw, sig, pubs)

    @pytest.mark.parametrize(
        ("over", "words"),
        [
            ({"schema": "wti.appcast/2"}, "shape"),
            ({"app": "rook"}, "different program"),
            ({"channel": "beta"}, "different program"),
            ({"version": "1.2"}, "version"),
            ({"version": "1.2.0-beta"}, "version"),
            ({"platforms": {}}, "nothing for Windows"),
        ],
    )
    def test_shape_rules_each_have_a_sentence(self, signer: Signer, pubs, over, words) -> None:
        raw, sig = signed(signer, make_feed(signer, **over))
        with pytest.raises(FeedProblem, match=words):
            parse_feed(raw, sig, pubs)

    @pytest.mark.parametrize(
        ("field", "value", "words"),
        [
            ("url", "http://github.com/x.exe", "does not fetch from"),
            ("url", "https://evil.example/x.exe", "does not fetch from"),
            ("sha256", "abc", "checksum"),
            ("sha256", "G" * 64, "checksum"),
            ("size", 0, "size"),
            ("size", "12", "size"),
            ("size", True, "size"),
            ("size", 10**12, "larger than Goldwing will fetch"),
            ("signature", "", "no signature"),
            ("args", ["/S", 3], "arguments"),
        ],
    )
    def test_platform_rules_each_have_a_sentence(self, signer: Signer, pubs, field, value, words) -> None:
        feed = make_feed(signer)
        feed["platforms"]["windows-x86_64"][field] = value
        raw, sig = signed(signer, feed)
        with pytest.raises(FeedProblem, match=words):
            parse_feed(raw, sig, pubs)


class TestFetchRelease:
    def test_falls_through_to_the_second_endpoint_when_the_first_is_down(self, signer: Signer, pubs) -> None:
        raw, sig = signed(signer, make_feed(signer))
        endpoints = ("https://github.com/a/latest.json", "https://updates.wetheindies.com/b/latest.json")

        def fetch(url: str, cap: int) -> bytes:
            if url.startswith(endpoints[0]):
                raise FeedProblem("Could not reach the release server.")
            return sig.encode() if url.endswith(".minisig") else raw

        log = FetchLog()
        release = fetch_release(endpoints, pubs, fetch=fetch, log=log)
        assert release.endpoint == endpoints[1]
        assert log.tried == list(endpoints)

    def test_a_bad_signature_is_an_answer_not_an_outage(self, signer: Signer, pubs) -> None:
        raw, _sig = signed(signer, make_feed(signer))
        bad = Signer().minisig(raw)
        endpoints = ("https://github.com/a/latest.json", "https://updates.wetheindies.com/b/latest.json")
        calls: list[str] = []

        def fetch(url: str, cap: int) -> bytes:
            calls.append(url)
            return bad.encode() if url.endswith(".minisig") else raw

        with pytest.raises(FeedProblem, match="not signed"):
            fetch_release(endpoints, pubs, fetch=fetch)
        assert all(url.startswith(endpoints[0]) for url in calls)

    def test_every_endpoint_down_is_one_sentence(self, pubs) -> None:
        def fetch(url: str, cap: int) -> bytes:
            raise FeedProblem("Could not reach the release server.")

        with pytest.raises(FeedProblem, match="Could not reach"):
            fetch_release(("https://github.com/a/latest.json",), pubs, fetch=fetch)

    def test_a_missing_feed_is_nothing_published_even_when_the_second_host_is_down(self, pubs) -> None:
        # TG-2 (15 Sep 2026): GitHub answers 404 before the release is out, and
        # the second host may not resolve yet. The person must not be told to
        # check their internet.
        endpoints = ("https://github.com/a/latest.json", "https://updates.wetheindies.com/b/latest.json")

        def fetch(url: str, cap: int) -> bytes:
            if url.startswith(endpoints[0]):
                raise FeedProblem("The release server does not have that file. Try again later.", missing=True)
            raise FeedProblem("Could not reach We The Indies. Check your internet, then try again.")

        with pytest.raises(FeedProblem) as caught:
            fetch_release(endpoints, pubs, fetch=fetch)
        assert str(caught.value) == feed_mod.NOTHING_PUBLISHED
        assert "internet" not in str(caught.value)

    def test_a_feed_whose_signature_is_missing_is_a_slip_not_up_to_date(self, signer: Signer, pubs) -> None:
        # TG-3: latest.json is there but its .minisig 404s. Saying "you have the
        # newest one" would hide a broken rollout from every Player.
        raw, _sig = signed(signer, make_feed(signer))

        def fetch(url: str, cap: int) -> bytes:
            if url.endswith(".minisig"):
                raise FeedProblem("The release server does not have that file. Try again later.", missing=True)
            return raw

        with pytest.raises(FeedProblem) as caught:
            fetch_release(("https://github.com/a/latest.json",), pubs, fetch=fetch)
        assert str(caught.value) != feed_mod.NOTHING_PUBLISHED
        assert "does not have that file" in str(caught.value)

    def test_the_cap_is_asked_for(self, signer: Signer, pubs) -> None:
        raw, sig = signed(signer, make_feed(signer))
        caps: list[int] = []

        def fetch(url: str, cap: int) -> bytes:
            caps.append(cap)
            return sig.encode() if url.endswith(".minisig") else raw

        fetch_release(("https://github.com/a/latest.json",), pubs, fetch=fetch)
        assert caps == [feed_mod.FEED_CAP, feed_mod.FEED_CAP]


class TestTheRealFetcher:
    def test_refuses_a_host_that_is_not_ours_without_opening_a_socket(self, monkeypatch) -> None:
        import urllib.request

        def boom(*args, **kwargs):
            raise AssertionError("a socket was opened")

        monkeypatch.setattr(urllib.request, "urlopen", boom)
        with pytest.raises(FeedProblem, match="not one Goldwing fetches from"):
            feed_mod.fetch_bytes("https://evil.example/latest.json", 10)
        with pytest.raises(FeedProblem):
            feed_mod.fetch_bytes("http://github.com/latest.json", 10)

    def test_a_redirect_off_our_hosts_is_refused(self, monkeypatch) -> None:
        import urllib.request

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def geturl(self):
                return "https://evil.example/latest.json"

            def read(self, n):
                return b"{}"

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response())
        with pytest.raises(FeedProblem, match="sent somewhere"):
            feed_mod.fetch_bytes("https://github.com/x/latest.json", 10)

    def test_more_than_the_cap_is_refused(self, monkeypatch) -> None:
        import urllib.request

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def geturl(self):
                return "https://github.com/x/latest.json"

            def read(self, n):
                return b"x" * n

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response())
        with pytest.raises(FeedProblem, match="more than Goldwing will read"):
            feed_mod.fetch_bytes("https://github.com/x/latest.json", 10)

    def test_the_request_carries_no_identifier(self, monkeypatch) -> None:
        import urllib.request

        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def geturl(self):
                return "https://github.com/x/latest.json"

            def read(self, n):
                return b"{}"

        def urlopen(request, timeout):
            seen["headers"] = dict(request.header_items())
            return Response()

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        feed_mod.fetch_bytes("https://github.com/x/latest.json", 10)
        assert set(seen["headers"]) == {"User-agent"}
        assert seen["headers"]["User-agent"] == feed_mod.USER_AGENT

    def test_a_missing_release_is_not_blamed_on_the_internet(self, monkeypatch) -> None:
        # GW-9 (15 Sep 2026): before the first release is published the feed
        # answers 404, and "check your internet" blamed the person.
        import urllib.error
        import urllib.request

        def urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        with pytest.raises(FeedProblem, match="does not have that file") as caught:
            feed_mod.fetch_bytes("https://github.com/x/latest.json", 10)
        assert "internet" not in str(caught.value)
        # Neutral at this layer (TG-3): only fetch_release may say "nothing published".
        assert caught.value.missing is True
        assert "newest" not in str(caught.value)

    def test_a_server_error_is_not_blamed_on_the_internet_either(self, monkeypatch) -> None:
        import urllib.error
        import urllib.request

        def urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        with pytest.raises(FeedProblem, match="did not answer properly"):
            feed_mod.fetch_bytes("https://github.com/x/latest.json", 10)


class TestKeys:
    def test_this_build_carries_the_ceremony_key_and_its_cold_spare(self) -> None:
        # The ceremony happened on 29 Aug 2026 (key id F8E608F4766B35A6) and
        # the cold spare was minted on 28 Aug (AE1D6657A32C4E9A). Both slots
        # are full, in that order, so a rotation to the spare needs no new
        # build to be trusted first.
        from wti_player.update import keys

        assert len(keys.TRUSTED_PUBLIC_KEYS) == 2
        parsed = trusted_keys()
        assert len(parsed) == 2
        assert parsed[0].key_id.hex().upper() == "F8E608F4766B35A6"
        assert parsed[1].key_id.hex().upper() == "AE1D6657A32C4E9A"
        assert parsed[0].key_id != parsed[1].key_id
        assert parsed[0].raw != parsed[1].raw

    def test_a_pasted_key_line_parses(self, signer: Signer) -> None:
        assert len(trusted_keys((signer.pub_line, "garbage"))) == 1

    def test_the_endpoints_are_ours_and_in_order(self) -> None:
        from wti_player.update import keys

        assert keys.ENDPOINTS[0].startswith("https://github.com/playtabegg/goldwing-media-player/releases/latest/download/")
        assert keys.ENDPOINTS[1].startswith("https://updates.wetheindies.com/apps/goldwing/stable/")
        assert all(feed_mod.host_allowed(url) for url in keys.ENDPOINTS)


class TestNotesUrl:
    def test_a_notes_url_off_our_hosts_is_dropped_before_it_reaches_a_browser(self, signer: Signer, pubs) -> None:
        for bad in ("file:///C:/Windows/System32/cmd.exe", "https://evil.example/notes", "http://github.com/x"):
            raw, sig = signed(signer, make_feed(signer, notes_url=bad))
            assert parse_feed(raw, sig, pubs).notes_url == ""
        raw, sig = signed(signer, make_feed(signer))
        assert parse_feed(raw, sig, pubs).notes_url.startswith("https://github.com/")
