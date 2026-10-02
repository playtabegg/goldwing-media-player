"""1.0.3: a support address on screen, and a software decoding switch (his answers of 2 Oct 2026).

Both were asked for by the audit of 8 Sep 2026 and never answered until then. The switch is the fallback for a
graphics card that shows video wrong; it is remembered, and it takes hold from the next disc opened. The address is
in the Help menu, the About box, and the sentence a stuck person reads.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from wti_player import strings
from wti_player.engine.fake import FakeEngine, simple_disc
from wti_player.optical.drives import DriveWatcher, FakeScanner
from wti_player.optical.reader import ImmediateReader
from wti_player.ui.main_window import MainWindow
from wti_player.ui.prefs import MemoryPreferences


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


class _NoGamepad:
    available = False

    def read(self):
        return None


def _window(prefs: MemoryPreferences | None = None, engine: FakeEngine | None = None) -> MainWindow:
    watcher = DriveWatcher(FakeScanner())
    watcher.poll()
    return MainWindow(engine or FakeEngine(simple_disc()), watcher=watcher, gamepad=_NoGamepad(), reader=ImmediateReader(), prefs=prefs or MemoryPreferences())


class TestSoftwareDecoding:
    def test_it_is_off_until_asked_for(self, qt_app) -> None:
        window = _window()
        try:
            assert not window.software_action.isChecked()
            assert not window.engine.software_decoding
        finally:
            window.close()

    def test_the_view_menu_turns_it_on_remembers_it_and_says_when_it_takes_hold(self, qt_app) -> None:
        prefs = MemoryPreferences()
        window = _window(prefs)
        try:
            window.software_action.trigger()
            assert window.engine.software_decoding
            assert prefs.software_decoding()
            assert window.software_action.isChecked()
            assert window.banner._label.text() == strings.SOFTWARE_DECODING_ON
            window.software_action.trigger()
            assert not window.engine.software_decoding
            assert not prefs.software_decoding()
            assert window.banner._label.text() == strings.SOFTWARE_DECODING_OFF
        finally:
            window.close()

    def test_a_remembered_choice_is_on_from_the_start(self, qt_app) -> None:
        prefs = MemoryPreferences()
        prefs.set_software_decoding(True)
        window = _window(prefs)
        try:
            assert window.engine.software_decoding
            assert window.software_action.isChecked()
        finally:
            window.close()

    def test_started_in_software_it_shows_ticked_whatever_was_remembered(self, qt_app) -> None:
        engine = FakeEngine(simple_disc())
        engine.set_software_decoding(True)  # as --no-hardware-decoding starts it
        prefs = MemoryPreferences()
        window = _window(prefs, engine)
        try:
            assert window.software_action.isChecked()
            assert not prefs.software_decoding()  # one run's switch is not a remembered choice
        finally:
            window.close()

    def test_the_words_say_what_it_is_for_and_what_it_costs(self) -> None:
        assert "green" in strings.SOFTWARE_DECODING_TIP and "Slower" in strings.SOFTWARE_DECODING_TIP
        assert "next disc" in strings.SOFTWARE_DECODING_ON


class TestTheRealEnginesOption:
    """The option libvlc is given per disc: none for software, and "any" to bring hardware back on an instance that
    was started in software."""

    def _options(self, *, started_hardware: bool, software_now: bool) -> list[str]:
        from wti_player.engine import vlc_engine

        engine = vlc_engine.VlcEngine.__new__(vlc_engine.VlcEngine)
        engine._instance_hardware = started_hardware
        engine._hardware_decoding = started_hardware
        engine.set_software_decoding(software_now)
        options: list[str] = []
        if not engine._hardware_decoding:
            options.append(":avcodec-hw=none")
        elif not engine._instance_hardware:
            options.append(":avcodec-hw=any")
        assert engine.software_decoding is software_now
        return options

    def test_software_asks_for_no_hardware(self) -> None:
        assert self._options(started_hardware=True, software_now=True) == [":avcodec-hw=none"]

    def test_hardware_on_an_ordinary_start_says_nothing(self) -> None:
        assert self._options(started_hardware=True, software_now=False) == []

    def test_hardware_after_a_software_start_asks_for_it_back(self) -> None:
        assert self._options(started_hardware=False, software_now=False) == [":avcodec-hw=any"]

    def test_the_engine_opens_with_exactly_those_lines(self) -> None:
        import inspect

        from wti_player.engine import vlc_engine

        source = inspect.getsource(vlc_engine.VlcEngine.open)
        assert 'if not self._hardware_decoding:\n            media.add_option(":avcodec-hw=none")' in source
        assert 'elif not self._instance_hardware:\n            media.add_option(":avcodec-hw=any")' in source


class TestWritingToUs:
    def test_the_help_menu_opens_a_mail_to_the_address(self, qt_app, monkeypatch) -> None:
        from wti_player.ui import main_window as window_module

        opened: list[str] = []
        monkeypatch.setattr(window_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
        window = _window()
        try:
            window.write_to_us()
            assert opened == [f"mailto:{strings.SUPPORT_EMAIL}"]
        finally:
            window.close()

    def test_with_no_mail_program_the_address_is_said_in_words(self, qt_app, monkeypatch) -> None:
        from wti_player.ui import main_window as window_module

        monkeypatch.setattr(window_module.QDesktopServices, "openUrl", lambda _url: False)
        window = _window()
        try:
            window.write_to_us()
            assert window.banner._label.text() == strings.SUPPORT_NO_MAIL
            assert strings.SUPPORT_EMAIL in strings.SUPPORT_NO_MAIL
        finally:
            window.close()

    def test_the_address_is_in_the_menu_the_about_box_and_the_stuck_sentence(self, qt_app) -> None:
        window = _window()
        try:
            help_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&Help")
            assert any(strings.SUPPORT_EMAIL in a.text() for a in help_menu.actions())
        finally:
            window.close()
        assert strings.SUPPORT_EMAIL in strings.about_text()
        assert strings.SUPPORT_EMAIL in strings.UNEXPECTED_PROBLEM
        assert strings.SUPPORT_EMAIL == "support@wetheindies.com"
