"""P9 (28 Aug 2026): tools/publish.py signs, proves, hashes, and says what to paste.

Only the pure parts run here. Signing needs a person at the keyboard with
`az login`, and no test and no build script ever calls it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, "tools")
import publish

from wti_player.version import PUBLISHER, VERSION


class TestWhatItWouldRun:
    def test_finds_newest_versioned_x64_sdk_tool(self, tmp_path, monkeypatch):
        older = tmp_path / "10.0.19041.0" / "x64" / "signtool.exe"
        newer = tmp_path / "10.0.22621.0" / "x64" / "signtool.exe"
        for tool in (older, newer):
            tool.parent.mkdir(parents=True)
            tool.write_bytes(b"sdk fixture")
        (tmp_path / "x64").mkdir()
        monkeypatch.setattr(publish.shutil, "which", lambda _: None)
        monkeypatch.setattr(publish, "_KIT_ROOTS", (tmp_path,))
        assert publish.find_signtool() == newer

    def test_the_sign_command_is_the_documented_one(self, tmp_path: Path) -> None:
        command = publish.sign_command(
            Path("signtool.exe"), Path("Azure.CodeSigning.Dlib.dll"), tmp_path / "m.json", tmp_path / "x.exe"
        )
        text = " ".join(command)
        assert command[1] == "sign"
        assert "/fd SHA256" in text
        assert "/tr http://timestamp.acs.microsoft.com" in text
        assert "/td SHA256" in text
        assert "/dlib" in command and "/dmdf" in command
        assert command[-1].endswith("x.exe")

    def test_the_metadata_names_the_account_and_profile_and_nothing_secret(self) -> None:
        data = publish.metadata()
        assert set(data) == {"Endpoint", "CodeSigningAccountName", "CertificateProfileName"}
        assert data["Endpoint"].endswith(".codesigning.azure.net")
        assert data["CodeSigningAccountName"] == "wetheindies-signing"
        assert data["CertificateProfileName"] == "wti-public-trust"

    def test_verify_asks_for_the_public_authenticode_policy(self) -> None:
        assert publish.verify_command(Path("signtool.exe"), Path("x.exe"))[1:4] == ["verify", "/pa", "/v"]


class TestReadingTheSubject:
    """signtool prints the signing chain root first; the leaf is the last line of it."""

    REAL_SHAPE = (
        "Verifying: WeTheIndiesPlayer-Setup-1.0.0.exe\n"
        "Signature Index: 0 (Primary Signature)\n"
        "Hash of file (sha256): ABC\n"
        "\n"
        "Signing Certificate Chain:\n"
        "    Issued to: Microsoft Identity Verification Root Certificate Authority 2020\n"
        "    Issued by: Microsoft Identity Verification Root Certificate Authority 2020\n"
        "    Expires:   Sun Apr 16 19:44:40 2045\n"
        "\n"
        "        Issued to: Microsoft ID Verified CS EOC CA 01\n"
        "        Issued by: Microsoft Identity Verification Root Certificate Authority 2020\n"
        "\n"
        "            Issued to: We The Indies, LLC\n"
        "            Issued by: Microsoft ID Verified CS EOC CA 01\n"
        "\n"
        "The signature is timestamped: Mon Sep 14 12:00:00 2026\n"
        "Timestamp Verified by:\n"
        "    Issued to: Microsoft Identity Verification Root Certificate Authority 2020\n"
        "        Issued to: Microsoft Public RSA Timestamping CA 2020\n"
        "\n"
        "Successfully verified: WeTheIndiesPlayer-Setup-1.0.0.exe\n"
    )

    def test_the_leaf_is_read_from_the_signing_chain_not_the_timestamp_chain(self) -> None:
        assert publish.subject_of(self.REAL_SHAPE) == "We The Indies, LLC"

    def test_a_chain_signed_by_somebody_else_reads_as_them(self) -> None:
        other = self.REAL_SHAPE.replace("Issued to: We The Indies, LLC", "Issued to: Somebody Else")
        assert publish.subject_of(other) == "Somebody Else"

    def test_an_unsigned_file_has_no_subject(self) -> None:
        assert publish.subject_of("SignTool Error: No signature found.") is None

    def test_the_expected_subject_is_the_publisher(self) -> None:
        assert publish.EXPECTED_SUBJECT == PUBLISHER == "We The Indies, LLC"


class TestTheHashAndTheEnv:
    def test_the_sidecar_is_sha256sum_shaped_and_matches(self, tmp_path: Path) -> None:
        installer = tmp_path / "WeTheIndiesPlayer-Setup-1.0.0.exe"
        installer.write_bytes(b"signed bytes")
        sidecar, digest = publish.write_sha256(installer)
        assert sidecar.name == installer.name + ".sha256"
        assert sidecar.read_text(encoding="utf-8") == f"{digest}  {installer.name}\n"
        assert digest == publish.sha256(installer)
        assert digest == digest.lower() and len(digest) == 64

    def test_the_three_values_are_what_the_website_reads(self) -> None:
        lines = publish.env_lines("https://example/x.exe", "ABCDEF" + "0" * 58)
        assert lines[0] == "NEXT_PUBLIC_PLAYER_DOWNLOAD_URL=https://example/x.exe"
        assert lines[1] == "NEXT_PUBLIC_PLAYER_SHA256=abcdef" + "0" * 58
        assert lines[2] == f"NEXT_PUBLIC_PLAYER_VERSION={VERSION}"

    def test_the_default_release_url_is_the_public_repo(self) -> None:
        url = publish.RELEASE_URL_TEMPLATE.format(version=VERSION, name="x.exe")
        assert url.startswith("https://github.com/playtabegg/goldwing-media-player/releases/download/v1.0.0/")


class TestItNeverRunsInsideABuild:
    def test_no_build_script_imports_or_calls_it(self) -> None:
        for name in ("build_exe.py", "build_installer.py", "fetch_vlc.py", "fetch_fonts.py"):
            text = Path("tools", name).read_text(encoding="utf-8")
            for forbidden in ("import publish", "from publish", "publish.py", "publish.main"):
                assert forbidden not in text, (name, forbidden)

    def test_without_yes_it_touches_nothing(self, tmp_path: Path, monkeypatch, capsys) -> None:
        installer = tmp_path / "WeTheIndiesPlayer-Setup-1.0.0.exe"
        installer.write_bytes(b"unsigned")
        before = installer.read_bytes()
        monkeypatch.setattr(publish, "find_signtool", lambda: Path("signtool.exe"))
        monkeypatch.setattr(publish, "find_dlib", lambda: Path("Azure.CodeSigning.Dlib.dll"))
        monkeypatch.setattr(publish, "run_signtool", lambda command: pytest.fail("signtool ran"))
        assert publish.main(["--installer", str(installer)]) == 0
        assert installer.read_bytes() == before
        assert not installer.with_name(installer.name + ".sha256").exists()
        assert "Nothing was touched" in capsys.readouterr().out

    def test_a_wrong_signer_is_refused_before_anything_is_hashed(self, tmp_path: Path, monkeypatch) -> None:
        import subprocess

        installer = tmp_path / "WeTheIndiesPlayer-Setup-1.0.0.exe"
        installer.write_bytes(b"signed by somebody else")
        monkeypatch.setattr(publish, "find_signtool", lambda: Path("signtool.exe"))

        def fake_verify(command):
            return subprocess.CompletedProcess(
                command, 0, stdout="Signing Certificate Chain:\n    Issued to: Somebody Else\n", stderr=""
            )

        monkeypatch.setattr(publish, "run_signtool", fake_verify)
        assert publish.main(["--installer", str(installer), "--skip-sign"]) == 9
        assert not installer.with_name(installer.name + ".sha256").exists()

    def test_the_right_signer_gets_hashed_and_the_values_printed(self, tmp_path: Path, monkeypatch, capsys) -> None:
        import subprocess

        installer = tmp_path / "WeTheIndiesPlayer-Setup-1.0.0.exe"
        installer.write_bytes(b"signed by us")
        monkeypatch.setattr(publish, "find_signtool", lambda: Path("signtool.exe"))

        def fake_verify(command):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Signing Certificate Chain:\n    Issued to: Root CA\n        Issued to: We The Indies, LLC\n",
                stderr="",
            )

        monkeypatch.setattr(publish, "run_signtool", fake_verify)
        assert publish.main(["--installer", str(installer), "--skip-sign"]) == 0
        out = capsys.readouterr().out
        assert "NEXT_PUBLIC_PLAYER_SHA256=" + publish.sha256(installer) in out
        assert installer.with_name(installer.name + ".sha256").is_file()
