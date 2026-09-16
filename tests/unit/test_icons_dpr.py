"""P10 (28 Aug 2026): icons are drawn at the screen's ratio, not stretched to it."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from wti_player.ui import icons


def test_a_two_hundred_percent_icon_has_twice_the_pixels(qapp) -> None:
    one = icons.pixmap("disc", 16, "#ffffff", dpr=1.0)
    two = icons.pixmap("disc", 16, "#ffffff", dpr=2.0)
    assert one.width() == 16
    assert two.width() == 32
    assert two.devicePixelRatio() == 2.0
    # And the logical size, which layout uses, is the same.
    assert two.deviceIndependentSize().width() == pytest.approx(16.0)


def test_the_cache_keeps_the_ratios_apart(qapp) -> None:
    assert icons.pixmap("disc", 16, "#ffffff", dpr=1.0) is not icons.pixmap("disc", 16, "#ffffff", dpr=2.0)
    assert icons.pixmap("disc", 16, "#ffffff", dpr=2.0) is icons.pixmap("disc", 16, "#ffffff", dpr=2.0)


def test_no_screen_means_one_to_one() -> None:
    assert icons.device_pixel_ratio() >= 1.0
