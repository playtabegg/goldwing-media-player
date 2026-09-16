"""C9 (29 Aug 2026): the repo goes public on launch Wednesday.

Two things a public reader sees first: the README, and the GPL notice's
"corresponding source" address. The README carried three em-dashes (a
house rule: none in anything We The Indies ships). ``SOURCE_URL`` names the
website's /player/source page, which the web repo built for exactly this
and pins to this string; that page links the public repository, and the
repository it links has to be the one the update feed is published from.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _feed_repo() -> str:
    """``owner/name`` from the first update endpoint, which is the public repo."""
    from wti_player.update import keys

    first = keys.ENDPOINTS[0]
    assert first.startswith("https://github.com/"), first
    owner, name = first.removeprefix("https://github.com/").split("/")[:2]
    return f"{owner}/{name}"


WEB_ROOT = Path(os.environ.get("WTI_TEST_WEB_ROOT", str(REPO.parent / "wetheindies-web")))
WEB_PLAYER_COPY = WEB_ROOT / "lib" / "storefront" / "player-copy.ts"


class TestTheSourceAddress:
    def test_source_url_is_the_websites_source_page(self) -> None:
        sys.path.insert(0, str(REPO / "tools"))
        import licence_notice

        assert licence_notice.SOURCE_URL == "https://wetheindies.com/player/source"

    def test_the_page_links_the_repo_the_feed_is_published_from(self) -> None:
        """Cross-repo: skips when the web repo is not beside this one."""
        if not WEB_PLAYER_COPY.is_file():
            import pytest

            pytest.skip("wetheindies-web is not beside this repo")
        text = WEB_PLAYER_COPY.read_text(encoding="utf-8")
        match = re.search(r"repoUrl:\s*'([^']+)'", text)
        assert match is not None, "player-copy.ts has no repoUrl"
        assert match.group(1) == f"https://github.com/{_feed_repo()}"

    def test_the_notice_carries_it(self) -> None:
        sys.path.insert(0, str(REPO / "tools"))
        import licence_notice

        flat = " ".join(licence_notice.notice().split())
        assert licence_notice.SOURCE_URL in flat


class TestTheReadme:
    def test_no_em_dash(self) -> None:
        text = (REPO / "README.md").read_text(encoding="utf-8")
        offenders = [n for n, line in enumerate(text.splitlines(), 1) if "—" in line]
        assert offenders == [], f"em-dash on README line(s) {offenders}"

    def test_it_points_at_the_licence(self) -> None:
        text = (REPO / "README.md").read_text(encoding="utf-8")
        assert "LICENSE" in text
