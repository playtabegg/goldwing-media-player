"""The menu preview panel.

What is on the disc, read from its own files, beside the menu actually
playing. This is the half of the Player that is a tool for us: when a menu
Rialto generated does not come up, the answer is almost always on this panel —
no interactive-graphics stream in the playlist, a Top Menu pointing at a movie
object that is not there, BD-J where HDMV was meant.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import strings
from ..optical.inspect import Line, Report, inspect_bdmv
from .theme import BONE, BRASS, MUTED

_TONES = {"ok": BONE, "note": BRASS, "problem": "#d98080"}


class PreviewPanel(QWidget):
    """A tree of what the disc's files say, with the problems called out."""

    copy_report = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._heading = QLabel(strings.PREVIEW_TITLE)
        self._heading.setObjectName("panelHeading")
        layout.addWidget(self._heading)

        self._verdict = QLabel("")
        self._verdict.setObjectName("panelNote")
        self._verdict.setWordWrap(True)
        layout.addWidget(self._verdict)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        layout.addWidget(self._tree, 1)

        buttons = QHBoxLayout()
        copy = QPushButton("Copy report")
        copy.clicked.connect(self._copy)
        buttons.addWidget(copy)
        self.reload_button = QPushButton(strings.RELOAD_FOLDER)
        self.reload_button.setToolTip("Read the folder again after changing files in it.")
        self.reload_button.clicked.connect(self.reload)
        self.reload_button.setEnabled(False)
        buttons.addWidget(self.reload_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._report: Report | None = None
        self._folder: Path | None = None

    def show_folder(self, folder: Path) -> Report:
        report = inspect_bdmv(folder)
        self._report = report
        self._folder = folder
        self.reload_button.setEnabled(True)
        self._heading.setText(f"{strings.PREVIEW_TITLE} · {folder.name}")
        if report.healthy:
            self._verdict.setText(
                "Nothing on this disc's structure would stop a menu coming up."
            )
        else:
            self._verdict.setText("\n".join(f"• {problem}" for problem in report.problems))

        self._tree.clear()
        for line in report.lines:
            self._tree.addTopLevelItem(_item(line))
        self._tree.expandToDepth(0)
        return report

    def reload(self) -> Report | None:
        """Read the same folder again. A designer changes a file and looks."""
        if self._folder is None:
            return None
        return self.show_folder(self._folder)

    def _copy(self) -> None:
        if self._report is None:
            return
        text = self._report.as_text()
        self.copy_report.emit(text)
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)


def _item(line: Line) -> QTreeWidgetItem:
    item = QTreeWidgetItem([line.text, line.detail])
    colour = QBrush(QColor(_TONES.get(line.tone, BONE)))
    item.setForeground(0, colour)
    item.setForeground(1, QBrush(QColor(MUTED if line.tone == "ok" else _TONES[line.tone])))
    item.setData(0, Qt.ItemDataRole.UserRole, line.tone)
    for child in line.children:
        item.addChild(_item(child))
    return item
