"""What a check trusts: the release keys and where the feed lives.

Only public keys belong here. Private release keys are maintained separately
and never enter the source repository or installer. If there are no trusted
public keys, the update path refuses to install anything.

Two slots, so a cold spare can be trusted by builds in the field before it
is ever used: rotating to it then needs no new build to be trusted first.

The endpoints are tried in order. GitHub Releases on the public repo comes
first; the estate's R2 bucket is the fallback. Only these hosts, and the
hosts GitHub redirects release downloads to, are ever fetched from.
"""

from __future__ import annotations

from .minisig import PublicKey, parse_public_key

APP = "goldwing"
CHANNEL = "stable"

#: minisign public key lines (base64 of ``Ed`` + key id + key). Paste the
#: line ``tools/wti_minisign.py keygen`` prints. Current key first, cold
#: spare second.
TRUSTED_PUBLIC_KEYS: tuple[str, ...] = (
    # Current release public key.
    "RWT45gj0dms1pn+/EcXvdcsp3FS3rpjSDgQ1QTBG4aMJnSeRpDF1W3M7",
    # Spare public key, trusted before rotation so existing builds accept it.
    "RWSuHWZXoyxOmitvRQxp1PdGnlNd92Opi8xZy/EOXeTa4GhqI0gjaCqd",
)

ENDPOINTS: tuple[str, ...] = (
    "https://github.com/playtabegg/goldwing-media-player/releases/latest/download/latest.json",
    "https://updates.wetheindies.com/apps/goldwing/stable/latest.json",
)

ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "updates.wetheindies.com",
    }
)

#: Where the release notes live, for the sentence that offers a download.
RELEASE_PAGE = "https://github.com/playtabegg/goldwing-media-player/releases/latest"


def trusted_keys(lines: tuple[str, ...] = TRUSTED_PUBLIC_KEYS) -> list[PublicKey]:
    """The keys that parse. A line that does not parse is not a key."""
    keys = []
    for line in lines:
        parsed = parse_public_key(line)
        if parsed is not None:
            keys.append(parsed)
    return keys
