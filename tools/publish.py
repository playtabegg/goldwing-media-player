"""Sign the installer, prove the signature, hash the result, say what to paste.

    python tools/publish.py --yes                # sign dist\\<installer>, verify, hash
    python tools/publish.py --skip-sign          # verify + hash an already-signed file
    python tools/publish.py                      # say what would happen; touch nothing

An authorized release operator runs this after `az login`. No build script imports or
calls it (a test holds that line): signing is a person in front of the
code signer, never a side effect of a build.

What it does, in order, and stops at the first thing that is not true:

1. finds the installer `tools/build_installer.py` wrote (or `--installer`);
2. signs it with Azure Trusted Signing through signtool and Microsoft's
   dlib, the same command `_Docs/AZURE-SIGNING-CONTEXT.md` documents and
   `rialto1.5/trusted_signing.py` runs (cribbed, not imported: this tool
   must work from a bare checkout);
3. `signtool verify /pa /v` and reads the subject back; anything other than
   `We The Indies, LLC` is a refusal, because a wrong certificate is the one
   mistake a person cannot see on the download page;
4. hashes the SIGNED file (signing changes the bytes; a pre-signing hash on
   the website is a hash nobody's download will match) and writes it beside
   the installer as `<installer>.sha256`;
5. prints the three `NEXT_PUBLIC_PLAYER_*` values, the sha lowercase, ready
   to paste into Vercel.

Nothing here downloads anything. The dlib is looked for in the sibling
checkouts' caches (`rialto2/tools/TrustedSigning`, `rialto1.5/tools/
TrustedSigning`) or `$WTI_SIGNING_DLIB`; getting it there is the operator's
one-time step and the message says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from wti_player.version import APP_NAME, PUBLISHER, VERSION  # noqa: E402

DIST = REPO / "dist"

#: The Trusted Signing account. Not secrets: the identity is proven by
#: `az login`, and these three only say which certificate to ask for.
ENDPOINT = os.environ.get("WTI_SIGNING_ENDPOINT", "https://eus.codesigning.azure.net")
ACCOUNT = os.environ.get("WTI_SIGNING_ACCOUNT", "wetheindies-signing")
PROFILE = os.environ.get("WTI_SIGNING_PROFILE", "wti-public-trust")
TIMESTAMP_URL = "http://timestamp.acs.microsoft.com"

#: What the certificate must say. Checked after signing, on the file.
EXPECTED_SUBJECT = PUBLISHER

#: GitHub Releases of the public repository hosts the installer and feed.
RELEASE_URL_TEMPLATE = "https://github.com/playtabegg/goldwing-media-player/releases/download/v{version}/{name}"

_KIT_ROOTS = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Kits" / "10" / "bin",
)
_DLIB_CACHES = (
    REPO.parent / "rialto2" / "tools" / "TrustedSigning",
    REPO.parent / "rialto1.5" / "tools" / "TrustedSigning",
)


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", name)


def default_installer() -> Path:
    return DIST / f"{slug(APP_NAME)}-Setup-{VERSION}.exe"


def find_signtool() -> Path | None:
    """A signtool.exe new enough for /dlib: the newest x64 one in the SDK."""
    found = shutil.which("signtool.exe")
    if found:
        return Path(found)
    for root in _KIT_ROOTS:
        if not root.is_dir():
            continue
        versions = sorted(
            (p for p in root.iterdir() if p.is_dir() and re.fullmatch(r"\d+(?:\.\d+)+", p.name)),
            key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split(".")],
            reverse=True,
        )
        for version in versions:
            candidate = version / "x64" / "signtool.exe"
            if candidate.is_file():
                return candidate
    return None


def find_dlib() -> Path | None:
    """Microsoft's Trusted Signing dlib, from an env override or a sibling cache."""
    named = (os.environ.get("WTI_SIGNING_DLIB") or "").strip()
    if named:
        path = Path(named)
        return path if path.is_file() else None
    for cache in _DLIB_CACHES:
        if not cache.is_dir():
            continue
        for path in cache.rglob("Azure.CodeSigning.Dlib.dll"):
            if "x64" in str(path.parent).lower():
                return path
    return None


def metadata() -> dict[str, str]:
    return {
        "Endpoint": ENDPOINT,
        "CodeSigningAccountName": ACCOUNT,
        "CertificateProfileName": PROFILE,
    }


def sign_command(signtool: Path, dlib: Path, metadata_path: Path, target: Path) -> list[str]:
    """The signtool invocation, as a list, so a test can read it without running it."""
    return [
        str(signtool),
        "sign",
        "/v",
        "/fd",
        "SHA256",
        "/tr",
        TIMESTAMP_URL,
        "/td",
        "SHA256",
        "/dlib",
        str(dlib),
        "/dmdf",
        str(metadata_path),
        str(target),
    ]


def verify_command(signtool: Path, target: Path) -> list[str]:
    return [str(signtool), "verify", "/pa", "/v", str(target)]


def subject_of(verify_output: str) -> str | None:
    """The signer's subject from `signtool verify /v`, or None when unsigned.

    signtool prints the signing chain root first and increasingly indented,
    so the LEAF, the certificate the file was signed with, is the last
    "Issued to:" inside the first "Signing Certificate Chain:" block. The
    timestamp chain that follows is another chain and is not read.
    """
    in_chain = False
    leaf: str | None = None
    for line in verify_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Signing Certificate Chain:"):
            if in_chain:
                break
            in_chain = True
            continue
        if not in_chain:
            continue
        if stripped.startswith(("The signature is timestamped", "Timestamp Verified", "Successfully verified")):
            break
        match = re.match(r"\s*Issued to:\s*(.+?)\s*$", line)
        if match:
            leaf = match.group(1)
    return leaf


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sha256(path: Path) -> tuple[Path, str]:
    """`<installer>.sha256` in the `sha256sum` shape, beside the file."""
    digest = sha256(path)
    sidecar = path.with_name(path.name + ".sha256")
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return sidecar, digest


def env_lines(url: str, digest: str, version: str = VERSION) -> list[str]:
    """The three Vercel values, the sha lowercase (lib/env.ts insists)."""
    return [
        f"NEXT_PUBLIC_PLAYER_DOWNLOAD_URL={url}",
        f"NEXT_PUBLIC_PLAYER_SHA256={digest.lower()}",
        f"NEXT_PUBLIC_PLAYER_VERSION={version}",
    ]


def run_signtool(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--installer", type=Path, default=None, help="the file to publish")
    parser.add_argument("--url", default=None, help="where the file will be downloadable from")
    parser.add_argument("--yes", action="store_true", help="actually sign (a person is at the keyboard)")
    parser.add_argument("--skip-sign", action="store_true", help="the file is already signed; verify and hash")
    args = parser.parse_args(argv)

    installer = args.installer or default_installer()
    if not installer.is_file():
        print(f"no installer at {installer}; run tools/build_installer.py first", file=sys.stderr)
        return 3
    url = args.url or RELEASE_URL_TEMPLATE.format(version=VERSION, name=installer.name)

    signtool = find_signtool()
    if signtool is None:
        print("signtool.exe not found: install the Windows 10/11 SDK signing tools", file=sys.stderr)
        return 4

    if not args.skip_sign:
        dlib = find_dlib()
        if dlib is None:
            print(
                "the Trusted Signing dlib is not here. Set $WTI_SIGNING_DLIB to "
                "Azure.CodeSigning.Dlib.dll, or run rialto2/tools/sign_with_azure.py once "
                "so its cache holds it.",
                file=sys.stderr,
            )
            return 5
        if not args.yes:
            print("Would sign, verify and hash:")
            print(f"  {installer}")
            print(f"  with {signtool}")
            print(f"  via {dlib}")
            print(f"  as {ACCOUNT} / {PROFILE} at {ENDPOINT}")
            print("Nothing was touched. Add --yes, after `az login`, to do it.")
            return 0
        fd, metadata_path = tempfile.mkstemp(suffix=".json", prefix="wti_publish_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata(), handle, indent=2)
            print(f"signing {installer.name} as {EXPECTED_SUBJECT}...")
            result = run_signtool(sign_command(signtool, dlib, Path(metadata_path), installer))
        finally:
            try:
                os.remove(metadata_path)
            except OSError:
                pass
        if result.returncode != 0:
            print(result.stdout[-2000:], file=sys.stderr)
            print(result.stderr[-2000:], file=sys.stderr)
            print("signing failed; nothing hashed, nothing to paste", file=sys.stderr)
            return 7

    verified = run_signtool(verify_command(signtool, installer))
    subject = subject_of(verified.stdout + verified.stderr)
    if verified.returncode != 0 or subject is None:
        print(verified.stdout[-2000:], file=sys.stderr)
        print(f"{installer.name} does not verify as signed; refusing to publish it", file=sys.stderr)
        return 8
    if subject != EXPECTED_SUBJECT:
        print(f"{installer.name} is signed by {subject!r}, not {EXPECTED_SUBJECT!r}; refusing", file=sys.stderr)
        return 9

    sidecar, digest = write_sha256(installer)
    print(f"signed by {subject}")
    print(f"sha256 {digest}  -> {sidecar.name}")
    print()
    print("Paste into Vercel (Production), then redeploy:")
    for line in env_lines(url, digest):
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
