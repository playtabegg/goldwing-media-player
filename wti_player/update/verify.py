"""The second, independent chain: Authenticode.

A downloaded installer already carries a minisign signature the Player
checked. Before it is run it must also be Authenticode-signed by We The
Indies, LLC through Azure Artifact Signing (the chain every installer has).
Two chains, both required, so a leaked release key alone cannot put a
program on a machine through this path.

Read only through PowerShell's ``Get-AuthenticodeSignature``, called by its
full path under SystemRoot so a file dropped beside the Player cannot stand
in for it; nothing here runs the downloaded file.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from ..version import PUBLISHER

EXPECTED_SUBJECT_CN = PUBLISHER
#: Azure Artifact Signing public-trust leaves are issued by the
#: "Microsoft ID Verified CS ..." CAs. A certificate with our CN from any
#: other issuer is not ours.
EXPECTED_ISSUER_PREFIX = "Microsoft ID Verified"


def powershell_path() -> Path:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def authenticode_names(path: Path) -> tuple[str, str] | None:
    """(subject CN, issuer CN) when the signature is valid, else None."""
    if sys.platform != "win32":
        return None
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath '" + str(path).replace("'", "''") + "'; "
        "if ($s.Status -ne 'Valid') { exit 3 }; "
        "$s.SignerCertificate.Subject; $s.SignerCertificate.Issuer"
    )
    try:
        # Windows PowerShell must load its own security module, even when
        # the Player was started from PowerShell 7 or another host.
        environment = {k: v for k, v in os.environ.items() if k.casefold() != "psmodulepath"}
        result = subprocess.run(
            [str(powershell_path()), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    subject, issuer = cn_of(lines[0]), cn_of(lines[1])
    if subject is None or issuer is None:
        return None
    return subject, issuer


def authenticode_subject(path: Path) -> str | None:
    names = authenticode_names(path)
    return names[0] if names else None


def cn_of(subject: str) -> str | None:
    """The CN of an X.500 name; quoted values may hold commas."""
    match = re.search(r'(?:^|,)\s*CN=("(?P<quoted>[^"]*)"|(?P<bare>[^,]*))', subject, re.IGNORECASE)
    if not match:
        return None
    value = match.group("quoted") if match.group("quoted") is not None else match.group("bare")
    return value.strip() or None


def is_ours(path: Path) -> bool:
    names = authenticode_names(path)
    if names is None:
        return False
    subject, issuer = names
    return subject == EXPECTED_SUBJECT_CN and issuer.startswith(EXPECTED_ISSUER_PREFIX)
