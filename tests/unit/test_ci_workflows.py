"""Supply-chain invariants for `.github/workflows/` (ported from rialto2, C10).

The workflows are the one place in this repo where somebody else's code
runs with write permission on our repository and on the installer people
run. Pinned in a test rather than in a reviewer's memory:

* every third-party action is pinned to a commit SHA, because a tag is
  mutable and the account that owns it can move it;
* nothing on the signing path reads a client secret: Trusted Signing is
  federated, and a secret would mean a signing key exists to be stolen;
* a `workflow_run` job that downloads artifacts names the run it is
  reaching into, or it silently downloads nothing;
* the signer sits behind the `release` environment, the one gate a tag
  carrying its own edited workflow cannot remove;
* the release is a DRAFT: Chandler publishes it after the appcast files are
  beside the installer, so no client sees a feed it cannot verify.

Parsed as text on purpose: no YAML dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO / ".github" / "workflows"

_FIRST_PARTY_PREFIXES = ("actions/", "azure/", "github/")
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.MULTILINE)
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _workflows() -> list[Path]:
    files = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
    assert files, f"no workflows found under {WORKFLOW_DIR}"
    return files


@pytest.mark.parametrize("workflow", _workflows(), ids=lambda p: p.name)
def test_third_party_actions_are_pinned_to_a_sha(workflow: Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    for reference in _USES.findall(text):
        action, _, version = reference.partition("@")
        if action.startswith(_FIRST_PARTY_PREFIXES):
            continue
        assert _SHA.match(version), (
            f"{workflow.name}: {reference} is a third-party action pinned to {version!r}. "
            "Pin it to a 40-character commit SHA; a tag can be moved under us."
        )


def test_no_client_secret_anywhere_on_the_signing_path() -> None:
    for workflow in _workflows():
        lowered = workflow.read_text(encoding="utf-8").lower()
        for forbidden in ("client-secret", "client_secret", "azure_client_secret"):
            assert forbidden not in lowered, f"{workflow.name} references {forbidden}"


def test_a_workflow_run_download_names_the_run_it_reaches_into() -> None:
    for workflow in _workflows():
        text = workflow.read_text(encoding="utf-8")
        if "workflow_run:" not in text or "download-artifact" not in text:
            continue
        assert "run-id:" in text, f"{workflow.name}: download-artifact has no run-id"
        assert "github-token:" in text, f"{workflow.name}: download-artifact has no github-token"
        assert "actions: read" in text, f"{workflow.name}: a cross-run download needs `actions: read`"


def test_the_release_is_a_draft_and_refuses_to_publish_nothing() -> None:
    text = (WORKFLOW_DIR / "release-on-tag.yml").read_text(encoding="utf-8")
    assert "fail_on_unmatched_files: true" in text
    assert "draft: true" in text, "Chandler publishes the release after the appcast files are up"
    assert "GoldwingMediaPlayer-Setup-*.exe" in text
    assert ".sha256" in text, "the website's hash rides with the installer"


def test_the_build_job_is_gated_verified_and_on_master() -> None:
    build = (WORKFLOW_DIR / "build-on-tag.yml").read_text(encoding="utf-8")
    assert "environment: release" in build, "the signer must sit behind the release environment"
    assert "id-token: write" in build, "OIDC federation needs id-token: write"
    assert "origin/master" in build, "the Player's default branch is master, not main"
    assert "tools/publish.py --yes" in build, "publish.py is what signs, verifies the subject and hashes"
    assert "wti_player/version.py" in build, "the tag must match the version the code carries"
    assert "tools/fetch_vlc.py" in build, "the pinned VLC has to be beside the EXE"


def test_codeowners_names_the_owner_of_the_workflows() -> None:
    text = (REPO / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    assert "/.github/workflows/ @playtabegg" in text
    assert "/CHECKSUMS.md @playtabegg" in text
