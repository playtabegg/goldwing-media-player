"""P10 (28 Aug 2026): ``supports_dvd`` answers, it does not throw."""

from __future__ import annotations

import pytest

from wti_player.engine import libvlc_loader, vlc_engine


def test_a_refused_runtime_reads_as_no_dvd_support(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(name: str) -> bool:
        raise libvlc_loader.RuntimeRefused("a VLC we will not use")

    monkeypatch.setattr(vlc_engine, "has_plugin", refuse)
    engine = vlc_engine.VlcEngine.__new__(vlc_engine.VlcEngine)
    assert engine.supports_dvd is False


def test_a_present_plugin_reads_as_support(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vlc_engine, "has_plugin", lambda name: name == "libdvdnav_plugin.dll")
    engine = vlc_engine.VlcEngine.__new__(vlc_engine.VlcEngine)
    assert engine.supports_dvd is True
