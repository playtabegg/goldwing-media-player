"""Every wrapped line of words shows, on any window width (found in the built 1.0.3, 30 Oct 2026).

1.0.3 added rows under a game's explanation (what the disc carries, the key, the note under the key). With the
text column a bare layout, a wide window gave the column more width than its 560 px labels take; their height was
worked out for that wider line, and the last line of each wrapped label was cut off: "The game itself is what"
with "plays." gone, and the last of what a disc carries. 1.0.2 showed all of it. The Welcome screen had the same
fault since 1.0.2 (its buttons' stretch widened the column), and its second line was cut in half at 1920 px.
"""

from __future__ import annotations

import pytest

from wti_player import strings

WIDTHS = (900, 1100, 1280, 1600, 1920)


def _cut_lines(qapp, stack, labels) -> list[str]:
    cut = []
    for width in WIDTHS:
        stack.resize(width, 760)
        stack.show()
        stack.currentWidget().layout().activate()
        for _ in range(5):
            qapp.processEvents()
        for name, label in labels:
            if label.isHidden():
                continue
            needs = label.heightForWidth(label.width()) if label.wordWrap() else label.sizeHint().height()
            if label.height() < needs:
                cut.append(f"{name} at {width} px: given {label.height()}, needs {needs}")
    return cut


@pytest.fixture
def page(qapp):
    from PyQt6.QtWidgets import QStackedWidget

    from wti_player.ui.theme import STYLESHEET
    from wti_player.ui.views import GameView

    stack = QStackedWidget()
    stack.setStyleSheet(STYLESHEET)
    view = GameView()
    stack.addWidget(view)
    view.kind.setText(strings.KIND_OURS_GAME.upper())
    view.name.setText("GIRAFFE TOWN")
    view.cover.hide()
    view._tree.hide()
    view._tail.show()
    yield stack, view
    stack.close()


def _labels(view):
    return [(name, getattr(view, name)) for name in ("body", "carries", "key_note", "name")]


def _with_carries(view) -> None:
    view.body.setText(strings.game_note(ours=True, image=False))
    view.carries.setText(
        "\n".join(
            strings.game_carries(
                online_updates=True,
                cloud_saves=True,
                soundtrack=("An Original Soundtrack", 12),
                has_key=True,
                key_on_disc=True,
            )
        )
    )
    view.carries.show()
    view._key = "TEXT-KEY4-DUMJ"
    view._key_signed = False
    view.key_button.show()


def test_a_disc_image_shows_its_whole_explanation(qapp, page) -> None:
    stack, view = page
    view.body.setText(strings.game_note(ours=True, image=True))
    view.carries.hide()
    view.forget()
    assert _cut_lines(qapp, stack, _labels(view)) == []


def test_what_a_disc_carries_shows_every_line_with_the_key_hidden(qapp, page) -> None:
    stack, view = page
    view.forget()
    _with_carries(view)
    assert not view.carries.isHidden()
    assert _cut_lines(qapp, stack, _labels(view)) == []


def test_every_line_shows_with_the_key_on_the_screen(qapp, page) -> None:
    stack, view = page
    view.forget()
    _with_carries(view)
    view.toggle_key()
    assert not view.key_text.isHidden()
    assert not view.carries.isHidden()
    assert not view.key_note.isHidden()
    assert _cut_lines(qapp, stack, _labels(view)) == []


def test_every_line_shows_beside_the_case(qapp, page, tmp_path) -> None:
    from PyQt6.QtGui import QColor, QImage

    stack, view = page
    cover = tmp_path / "cover.jpg"
    image = QImage(300, 420, QImage.Format.Format_RGB32)
    image.fill(QColor("#335577"))
    assert image.save(str(cover))
    view.forget()
    _with_carries(view)
    view.cover.set_cover(cover, "GIRAFFE TOWN")
    view.cover.show()
    view.toggle_key()
    assert _cut_lines(qapp, stack, _labels(view)) == []


def test_the_welcome_shows_its_whole_words(qapp) -> None:
    from PyQt6.QtWidgets import QLabel, QStackedWidget

    from wti_player.ui.theme import STYLESHEET
    from wti_player.ui.views import WelcomeView

    stack = QStackedWidget()
    stack.setStyleSheet(STYLESHEET)
    view = WelcomeView()
    stack.addWidget(view)
    try:
        view.set_drives([])
        view.set_shelf([])
        # Every label with words, wrapped or not: the 44 pt title was squeezed too (36 of 59 px at 1920 in 1.0.2).
        words = [(label.text()[:30], label) for label in view.findChildren(QLabel) if label.text()]
        assert any(label.text() == strings.WELCOME_BODY for _, label in words)
        assert any(label.text() == strings.WELCOME_TITLE for _, label in words)
        assert _cut_lines(qapp, stack, words) == []
    finally:
        stack.close()
