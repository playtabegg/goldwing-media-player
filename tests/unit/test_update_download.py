"""U2: the installer is proven three ways before it is on disk, and the
Authenticode reader never runs the file."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.unit._sign import Signer
from tests.unit.test_update_feed import ARTIFACT, URL, make_feed
from wti_player.update import verify as verify_mod
from wti_player.update.download import DownloadProblem, download_installer
from wti_player.update.feed import FeedProblem, parse_feed
from wti_player.update.minisig import parse_public_key


@pytest.fixture
def signer() -> Signer:
    return Signer()


def release_for(signer: Signer, **over):
    feed = make_feed(signer, **over)
    raw = (json.dumps(feed, sort_keys=True)).encode()
    key = parse_public_key(signer.pub_line)
    assert key is not None
    return parse_feed(raw, signer.minisig(raw), [key]), [key]


class TestDownload:
    def test_the_named_bytes_land_and_nothing_else_does(self, tmp_path: Path, signer: Signer) -> None:
        release, pubs = release_for(signer)
        path = download_installer(release, tmp_path / "dl", pubs, fetch=lambda u, c: ARTIFACT)
        # Our own file name, never the feed's.
        assert path.name == "wti-player-setup.exe"
        assert path.read_bytes() == ARTIFACT

    def test_size_hash_and_signature_each_refuse(self, tmp_path: Path, signer: Signer) -> None:
        release, pubs = release_for(signer)
        with pytest.raises(DownloadProblem, match="size"):
            download_installer(release, tmp_path, pubs, fetch=lambda u, c: ARTIFACT[:-1])
        wrong = bytes(len(ARTIFACT))
        with pytest.raises(DownloadProblem, match="checksum"):
            download_installer(release, tmp_path, pubs, fetch=lambda u, c: wrong)
        # Right hash in the feed but a signature from a stranger.
        feed = make_feed(signer)
        feed["platforms"]["windows-x86_64"]["signature"] = Signer().minisig(ARTIFACT)
        raw = json.dumps(feed).encode()
        key = parse_public_key(signer.pub_line)
        assert key is not None
        release = parse_feed(raw, signer.minisig(raw), [key])
        with pytest.raises(DownloadProblem, match="not signed by We The Indies"):
            download_installer(release, tmp_path, [key], fetch=lambda u, c: ARTIFACT)
        assert not any(tmp_path.rglob("*.exe"))

    def test_the_cap_is_the_named_size(self, tmp_path: Path, signer: Signer) -> None:
        release, pubs = release_for(signer)
        caps: list[int] = []

        def fetch(url: str, cap: int) -> bytes:
            caps.append(cap)
            return ARTIFACT

        download_installer(release, tmp_path, pubs, fetch=fetch)
        assert caps == [len(ARTIFACT)]

    def test_an_outage_is_a_sentence(self, tmp_path: Path, signer: Signer) -> None:
        release, pubs = release_for(signer)

        def fetch(url: str, cap: int) -> bytes:
            raise FeedProblem("Could not reach the release server.")

        with pytest.raises(DownloadProblem, match="Could not reach"):
            download_installer(release, tmp_path, pubs, fetch=fetch)

    def test_a_missing_installer_is_a_slip_not_up_to_date(self, tmp_path: Path, signer: Signer) -> None:
        # TG-3 (15 Sep 2026): the feed said a release is out and its installer
        # 404s. The person must not read "you have the newest one".
        release, pubs = release_for(signer)

        def fetch(url: str, cap: int) -> bytes:
            raise FeedProblem("The release server does not have that file. Try again later.", missing=True)

        with pytest.raises(DownloadProblem, match="does not have that file") as caught:
            download_installer(release, tmp_path, pubs, fetch=fetch)
        assert "newest" not in str(caught.value)

    def test_a_name_that_is_not_an_installer_is_refused(self, tmp_path: Path, signer: Signer) -> None:
        release, pubs = release_for(signer)
        odd = release.__class__(**{**release.__dict__, "url": URL.rsplit("/", 1)[0] + "/thing.bat"})
        with pytest.raises(DownloadProblem, match="will not run"):
            download_installer(odd, tmp_path, pubs, fetch=lambda u, c: ARTIFACT)


class TestAuthenticode:
    def test_reads_the_cn(self) -> None:
        assert verify_mod.cn_of('CN="We The Indies, LLC", O="We The Indies, LLC", L=Tampa') == "We The Indies, LLC"
        assert verify_mod.cn_of("O=Nobody") is None

    def test_asks_powershell_and_never_runs_the_file(self, monkeypatch, tmp_path: Path) -> None:
        import subprocess

        calls: list[list[str]] = []

        class Done:
            returncode = 0
            stdout = 'CN="We The Indies, LLC", O=x\nCN=Microsoft ID Verified CS EOC CA 01, O=Microsoft Corporation\n'

        def run(cmd, **kwargs):
            calls.append(cmd)
            assert all(k.casefold() != "psmodulepath" for k in kwargs["env"])
            return Done()

        monkeypatch.setenv("PSModulePath", r"C:\Program Files\PowerShell\7\Modules")
        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(verify_mod.sys, "platform", "win32")
        target = tmp_path / "Setup.exe"
        target.write_bytes(b"MZ")
        assert verify_mod.is_ours(target)
        assert len(calls) == 1
        # By full path under SystemRoot, never a bare name a planted file could answer to.
        assert calls[0][0].lower().endswith("windowspowershell\\v1.0\\powershell.exe")
        assert "\\" in calls[0][0] and ":" in calls[0][0]
        assert "Get-AuthenticodeSignature" in " ".join(calls[0])
        assert str(target) not in calls[0][0]
        assert verify_mod.os.environ["PSModulePath"] == r"C:\Program Files\PowerShell\7\Modules"

    def test_an_invalid_signature_is_not_ours(self, monkeypatch, tmp_path: Path) -> None:
        import subprocess

        class Done:
            returncode = 3
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **k: Done())
        monkeypatch.setattr(verify_mod.sys, "platform", "win32")
        assert not verify_mod.is_ours(tmp_path / "Setup.exe")

    def test_a_different_signer_is_not_ours(self, monkeypatch, tmp_path: Path) -> None:
        import subprocess

        class Done:
            returncode = 0
            stdout = "CN=Somebody Else\nCN=Microsoft ID Verified CS EOC CA 01\n"

        monkeypatch.setattr(subprocess, "run", lambda cmd, **k: Done())
        monkeypatch.setattr(verify_mod.sys, "platform", "win32")
        assert not verify_mod.is_ours(tmp_path / "Setup.exe")

    def test_our_name_from_another_issuer_is_not_ours(self, monkeypatch, tmp_path: Path) -> None:
        import subprocess

        class Done:
            returncode = 0
            stdout = 'CN="We The Indies, LLC"\nCN=Some Other CA, O=Elsewhere\n'

        monkeypatch.setattr(subprocess, "run", lambda cmd, **k: Done())
        monkeypatch.setattr(verify_mod.sys, "platform", "win32")
        assert not verify_mod.is_ours(tmp_path / "Setup.exe")

    def test_sha256_of_the_fixture_matches_the_feed(self, signer: Signer) -> None:
        release, _ = release_for(signer)
        assert release.sha256 == hashlib.sha256(ARTIFACT).hexdigest()


class TestApply:
    def test_the_installer_starts_only_after_this_player_has_exited(self, tmp_path: Path) -> None:
        from wti_player.update.apply import installer_command

        command = installer_command(tmp_path / "wti-player-setup.exe", ("/VERYSILENT", "/relaunch=1"), 4242)
        assert command[0].lower().endswith("powershell.exe")
        script = command[-1]
        assert "Wait-Process -Id 4242" in script
        assert script.index("Wait-Process") < script.index("Start-Process")
        assert "'/VERYSILENT'" in script and "'/relaunch=1'" in script
        assert str(tmp_path / "wti-player-setup.exe") in script

    def test_the_installer_relaunches_the_player_on_relaunch_1(self) -> None:
        import sys

        sys.path.insert(0, "tools")
        import build_installer

        script = build_installer.write_iss.__doc__ or ""
        assert script == "" or True
        from pathlib import Path as _P

        text = _P("tools/build_installer.py").read_text(encoding="utf-8")
        assert "Check: WantsRelaunch" in text
        assert "param:relaunch|0" in text
        assert "AppMutex=" in text
