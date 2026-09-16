"""Build and sign a ``wti.appcast/1`` feed for an app release.

    python tools/release_feed.py publish --app goldwing --version 1.0.0 \
        --artifact dist/GoldwingMediaPlayer-Setup-1.0.0.exe --channel stable \
        --key <dir>/wti-app-release.key --out dist/release \
        --url https://github.com/playtabegg/goldwing-media-player/releases/download/v1.0.0/GoldwingMediaPlayer-Setup-1.0.0.exe

What it does, in order, and it stops at the first thing that is wrong:

1. Refuses an artifact that is not Authenticode-signed by We The Indies, LLC
   (``signtool verify /pa``), unless ``--no-authenticode`` is passed, which
   is for the round-trip test and prints a warning you cannot miss.
2. Computes the SHA-256 of the artifact as it is now, after signing. This is
   the hash the clients check and the one the website's
   ``NEXT_PUBLIC_PLAYER_SHA256`` must carry.
3. Signs the artifact (``<artifact>.sig``, minisign prehashed).
4. Writes ``latest.json`` with the schema, app, channel, version, date, the
   platform block (url, signature, sha256, size, installer, args).
5. Signs it (``latest.json.minisig``).
6. Reads everything back from disk and verifies it with the public key:
   a missing or stale signature is a hard abort, never a warning.
7. Prints the upload order: signature files first, then the feed, then the
   installer, so no client ever sees a feed it cannot verify.

Uploads are a person's act (``gh release upload`` or the R2 console); this
tool writes a folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wti_minisign

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wti_player.update.keys import trusted_keys

SCHEMA = "wti.appcast/1"
APPS = ("goldwing",)

RELEASE_REPOS = {
    "goldwing": "playtabegg/goldwing-media-player",
}

CLIENT_ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "updates.wetheindies.com",
    }
)
CHANNELS = ("stable",)
PLATFORM = "windows-x86_64"
PUBLISHER_SUBJECT = "We The Indies, LLC"
INNO_SILENT_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/relaunch=1"]


class PublishError(Exception):
    """Something about the release is wrong; nothing was published."""


def release_page(app: str, version: str) -> str | None:
    """The GitHub release page for this version, or None for an app with no repo."""
    repo = RELEASE_REPOS.get(app)
    return f"https://github.com/{repo}/releases/tag/v{version}" if repo else None


def notes_url_for(app: str, version: str, requested: str) -> str:
    """The ``notes_url`` the feed will carry: the release page by default.

    A URL on a host the clients do not allow is refused rather than
    published: every client drops it on the way to the browser, and a feed
    whose notes link goes nowhere is the bug this exists to stop.
    """
    url = requested.strip() or (release_page(app, version) or "")
    if not url:
        raise PublishError(f"{app} has no release repo on file; pass --notes-url explicitly")
    if not url.startswith("https://"):
        raise PublishError("notes_url must be https")
    host = url.split("/", 3)[2].lower()
    if host not in CLIENT_ALLOWED_HOSTS:
        raise PublishError(
            f"notes_url host {host!r} is not one the clients allow ({', '.join(sorted(CLIENT_ALLOWED_HOSTS))}); "
            f"they would drop it silently. Use the release page: {release_page(app, version) or 'n/a'}"
        )
    return url


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_signtool() -> Path | None:
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if not kits.is_dir():
        return None
    hits = sorted(kits.glob("*/x64/signtool.exe"))
    return hits[-1] if hits else None


def authenticode_subject(artifact: Path, signtool: Path | None = None) -> str | None:
    """The leaf subject of the artifact's Authenticode signature, or None."""
    tool = signtool or find_signtool()
    if tool is None:
        raise PublishError("signtool.exe not found; install the Windows SDK or pass --no-authenticode for a test")
    result = subprocess.run(
        [str(tool), "verify", "/pa", "/v", str(artifact)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    in_chain = False
    subject = None
    for line in result.stdout.splitlines():
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
        if stripped.startswith("Issued to:"):
            subject = stripped[len("Issued to:"):].strip()
    return subject


def valid_version(version: str) -> bool:
    parts = version.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def build_feed(
    *,
    app: str,
    channel: str,
    version: str,
    url: str,
    artifact_sig_text: str,
    sha256: str,
    size: int,
    pub_date: str,
    notes: str,
    notes_url: str,
    min_upgradable_from: str,
) -> dict:
    return {
        "schema": SCHEMA,
        "app": app,
        "channel": channel,
        "version": version,
        "pub_date": pub_date,
        "notes": notes,
        "notes_url": notes_url,
        "min_upgradable_from": min_upgradable_from,
        "platforms": {
            PLATFORM: {
                "url": url,
                "signature": artifact_sig_text,
                "sha256": sha256,
                "size": size,
                "installer": "inno",
                "args": list(INNO_SILENT_ARGS),
            }
        },
    }


def feed_bytes(feed: dict) -> bytes:
    """One canonical serialisation, so the signed bytes are the file bytes."""
    return (json.dumps(feed, indent=2, sort_keys=True) + "\n").encode("utf-8")


def publish(
    *,
    app: str,
    channel: str,
    version: str,
    artifact: Path,
    url: str,
    key_path: Path,
    out_dir: Path,
    notes: str = "",
    notes_url: str = "",
    min_upgradable_from: str = "",
    require_authenticode: bool = True,
    now: datetime | None = None,
) -> dict[str, Path]:
    if app not in APPS:
        raise PublishError(f"app must be one of {APPS}")
    if channel not in CHANNELS:
        raise PublishError(f"channel must be one of {CHANNELS}")
    if not valid_version(version):
        raise PublishError("version must be plain X.Y.Z integers")
    if not artifact.is_file():
        raise PublishError(f"no artifact at {artifact}")
    if not url.startswith("https://"):
        raise PublishError("the download URL must be https")
    parsed_url = urlparse(url)
    if parsed_url.hostname not in CLIENT_ALLOWED_HOSTS or parsed_url.username or parsed_url.password or parsed_url.fragment:
        raise PublishError("download URL is not permitted by the Player")
    if not url.endswith(artifact.name):
        raise PublishError(f"the download URL must end with the artifact's file name {artifact.name}")
    notes_url = notes_url_for(app, version, notes_url)

    if require_authenticode:
        subject = authenticode_subject(artifact)
        if subject != PUBLISHER_SUBJECT:
            raise PublishError(
                f"{artifact.name} is not Authenticode-signed by {PUBLISHER_SUBJECT} "
                f"(found {subject!r}). Sign it first; the hash below must be post-signing."
            )
    else:
        print("WARNING: --no-authenticode. This feed is for a test, not for people.", file=sys.stderr)

    key_id, seed = wti_minisign.load_key(key_path)
    pub = wti_minisign.PublicKey(key_id, wti_minisign.wti_ed25519.public_key(seed))
    if not any(key.key_id == pub.key_id and key.raw == pub.raw for key in trusted_keys()):
        raise PublishError("release key is not trusted by this Player; nothing staged")

    out_dir.mkdir(parents=True, exist_ok=True)

    staged = out_dir / artifact.name
    if staged.resolve() != artifact.resolve():
        shutil.copyfile(artifact, staged)
    digest = sha256_file(staged)
    size = staged.stat().st_size
    hash_path = out_dir / f"{staged.name}.sha256"
    hash_path.write_text(f"{digest}  {staged.name}\n", encoding="utf-8")

    artifact_sig = wti_minisign.sign_bytes(
        staged.read_bytes(), key_id, seed, f"timestamp:0\tfile:{staged.name}"
    )
    sig_path = out_dir / f"{staged.name}.sig"
    sig_path.write_text(artifact_sig, encoding="utf-8")

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    feed = build_feed(
        app=app,
        channel=channel,
        version=version,
        url=url,
        artifact_sig_text=artifact_sig,
        sha256=digest,
        size=size,
        pub_date=stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        notes=notes,
        notes_url=notes_url,
        # Empty means no floor. Stamping the new version here would tell every
        # older build it cannot step up, which is the opposite of a release.
        min_upgradable_from=min_upgradable_from,
    )
    feed_path = out_dir / "latest.json"
    feed_path.write_bytes(feed_bytes(feed))
    feed_sig_path = out_dir / "latest.json.minisig"
    feed_sig_path.write_text(
        wti_minisign.sign_bytes(feed_path.read_bytes(), key_id, seed, "timestamp:0\tfile:latest.json"),
        encoding="utf-8",
    )
    extra: dict[str, Path] = {}

    # Read back from disk and verify, as a client would. A signature that
    # does not match what is on disk is the one failure this tool exists to
    # make impossible to ship.
    problems = check_folder(out_dir, pub, expect_sha256=digest)
    if problems:
        raise PublishError("refusing to publish: " + "; ".join(problems))

    return {"artifact": staged, "hash": hash_path, "artifact_sig": sig_path, "feed": feed_path, "feed_sig": feed_sig_path, **extra}


def check_folder(out_dir: Path, pub: wti_minisign.PublicKey, *, expect_sha256: str | None = None) -> list[str]:
    """Every reason this folder is not publishable. Empty means go."""
    problems: list[str] = []
    feed_path = out_dir / "latest.json"
    feed_sig_path = out_dir / "latest.json.minisig"
    if not feed_path.is_file():
        return ["latest.json is missing"]
    if not feed_sig_path.is_file():
        return ["latest.json.minisig is missing"]
    raw = feed_path.read_bytes()
    if not wti_minisign.verify_bytes(raw, feed_sig_path.read_text(encoding="utf-8"), pub):
        problems.append("latest.json.minisig does not verify against latest.json (stale or wrong key)")
    try:
        feed = json.loads(raw)
    except json.JSONDecodeError:
        return [*problems, "latest.json is not JSON"]
    if feed.get("schema") != SCHEMA:
        problems.append(f"schema is {feed.get('schema')!r}, not {SCHEMA}")
    block = (feed.get("platforms") or {}).get(PLATFORM) or {}
    name = block.get("url", "").rsplit("/", 1)[-1]
    artifact = out_dir / name
    if not name or not artifact.is_file():
        problems.append(f"artifact {name!r} named in the feed is not in {out_dir}")
        return problems
    digest = sha256_file(artifact)
    if block.get("sha256") != digest:
        problems.append("sha256 in the feed is not the artifact's (stale feed)")
    if expect_sha256 and digest != expect_sha256:
        problems.append("artifact changed after hashing")
    if block.get("size") != artifact.stat().st_size:
        problems.append("size in the feed is not the artifact's")
    sig_text = block.get("signature", "")
    if not wti_minisign.verify_bytes(artifact.read_bytes(), sig_text, pub):
        problems.append("the artifact signature in the feed does not verify")
    sig_file = out_dir / f"{name}.sig"
    if not sig_file.is_file() or sig_file.read_text(encoding="utf-8") != sig_text:
        problems.append(f"{name}.sig is missing or differs from the signature in the feed")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("--app", choices=APPS, required=True)
    p.add_argument("--channel", choices=CHANNELS, default="stable")
    p.add_argument("--version", required=True)
    p.add_argument("--artifact", type=Path, required=True)
    p.add_argument("--url", required=True, help="where the artifact will live, ending in its file name")
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--notes", default="")
    p.add_argument("--notes-url", default="", help="defaults to the GitHub release page for this version")
    p.add_argument("--min-upgradable-from", default="")
    p.add_argument("--no-authenticode", action="store_true", help="tests only")
    c = sub.add_parser("check", help="verify a folder as a client would")
    c.add_argument("--dir", type=Path, required=True)
    c.add_argument("--pub", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.cmd == "check":
            problems = check_folder(args.dir, wti_minisign.load_public_key(args.pub))
            for problem in problems:
                print(f"BAD: {problem}")
            print("OK" if not problems else f"{len(problems)} problem(s)")
            return 0 if not problems else 1
        paths = publish(
            app=args.app,
            channel=args.channel,
            version=args.version,
            artifact=args.artifact,
            url=args.url,
            key_path=args.key,
            out_dir=args.out,
            notes=args.notes,
            notes_url=args.notes_url,
            min_upgradable_from=args.min_upgradable_from,
            require_authenticode=not args.no_authenticode,
        )
    except PublishError as error:
        print(f"ABORT: {error}", file=sys.stderr)
        return 1
    digest = sha256_file(paths["artifact"])
    print(f"feed      {paths['feed']}")
    print(f"sha256    {digest}")
    print("\nUpload in this order (signatures first, installer last):")
    # The installer signature is embedded in latest.json. Its .sig file is
    # local verification material, not a fifth public release asset.
    order = ["feed_sig", "feed", "hash", "artifact"]
    for key in order:
        print(f"  {paths[key].name}")
    env_name = "NEXT_PUBLIC_PLAYER_SHA256"
    if env_name:
        print(f"\nWebsite: {env_name}={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
