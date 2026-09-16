"""How the Player looks.

One rule holds the rest of this file together: nothing in this interface
should be more interesting than what is on the disc. So there is one accent
colour, no gradients on chrome, no shadows except where something genuinely
floats, and no animation that is not a fade.

The typefaces are the site's: Playfair Display for the name of the thing,
Outfit for everything a person reads as interface. Both are bundled, so the
Player looks the same on a machine that has never seen them. If they will
not load, :func:`load_fonts` says so and the stacks below fall back to faces
Windows has always had.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


def _font_dir() -> Path:
    """Where the typefaces are, running from source or from the built EXE.

    PyInstaller lays package data out beside the frozen modules rather than
    inside them, so ``__file__`` finds nothing in a build. ``tools/build_exe``
    puts them at this path, and a test there fails if it ever stops.
    """
    beside = Path(__file__).with_name("fonts")
    if beside.is_dir():
        return beside
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "wti_player" / "ui" / "fonts"
    return beside


FONT_DIR = _font_dir()

#: The gold bird. Beside this module in a checkout; next to the frozen
#: fonts in a build, because PyInstaller lays package data out the same way.
def _mark_dir() -> Path:
    beside = Path(__file__).with_name("marks")
    if beside.is_dir():
        return beside
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "wti_player" / "ui" / "marks"
    return beside


MARK_DIR = _mark_dir()
MARK_FILE = MARK_DIR / "goldwing.png"


def window_icon():
    """The gold bird, for the title bar, the taskbar, and Alt-Tab.

    Running from source used to wear Python's own mark. That is why the
    window looked like it had no bird.
    """
    from PyQt6.QtGui import QIcon

    ico = Path(__file__).with_name("player.ico")
    if MARK_FILE.is_file():
        return QIcon(str(MARK_FILE))
    if ico.is_file():
        return QIcon(str(ico))
    return QIcon()


def mark_pixmap(size: int):
    """The gold bird at ``size`` pixels, or ``None`` if the file is missing."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap

    if not MARK_FILE.is_file():
        return None
    pixmap = QPixmap(str(MARK_FILE))
    if pixmap.isNull():
        return None
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

#: The window, and behind the film.
INK = "#0d0f14"
#: Panels, transport, dialogs — raised, not lighter for the sake of it.
RAISED = "#12151d"
#: One step further up: a row under the pointer, a field.
RAISED_HI = "#181c26"
#: Anything being read.
BONE = "#e8e2d6"
#: A shade below bone, for a row title that is not the one playing.
NEAR = "#cdc6b7"
#: Body copy set at length.
SOFT = "#a09889"
#: Secondary lines and metadata.
MUTED = "#8b8578"
#: Section labels and the small print under them.
DIM = "#6a6459"
#: Present but unavailable. Never used for anything a person must read.
FAINT = "#4f4a42"

#: One per screen — the thing to press.
BRASS = "#c9a961"
BRASS_HI = "#dcc07f"
BRASS_DIM = "#b9a877"
#: Brass at low alpha, for the row that is playing.
BRASS_WASH = "rgba(201, 169, 97, 0.10)"

#: A mode is on; nothing is wrong.
NOTICE = "#2d4a3e"
NOTICE_INK = "#cfe0d6"
NOTICE_EDGE = "#8fbfa4"

#: A disc could not be read.
PROBLEM = "#7a2e2e"
PROBLEM_INK = "#f0d6d6"

#: Every divider in the program, at 7 to 10 percent bone. Rules divide sections; rows
#: separate by a pixel and a colour, never by a rule.
HAIRLINE = "rgba(232, 226, 214, 0.08)"
HAIRLINE_STRONG = "rgba(232, 226, 214, 0.14)"

BLACK = "#000000"

# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------

#: The disc's own name, and only that.
DISPLAY = "Playfair Display"
#: Everything else a person reads.
UI = "Outfit"
#: Paths, PIDs, anything that is data rather than prose.
MONO = "Consolas"

#: Outfit's word space is tight: at 11px and below it rounds to two device
#: pixels and "3 chapters" reads as one word. Sentence-case interface text
#: never goes below this. Tracked-out uppercase can, because the tracking does
#: the separating, so section labels sit at 10px.
MIN_TEXT_PX = 12

DISPLAY_STACK = f"'{DISPLAY}', Georgia, 'Times New Roman', serif"
UI_STACK = f"'{UI}', 'Segoe UI', system-ui, sans-serif"
MONO_STACK = f"'{MONO}', 'Cascadia Mono', monospace"

# ---------------------------------------------------------------------------
# Rhythm
# ---------------------------------------------------------------------------

#: Distance from the window's edge to anything in it.
EDGE = 44
#: Distance from a panel's edge to its contents.
PANEL_EDGE = 28
#: A list row: 11px above and below, 12px either side.
ROW_Y = 11
ROW_X = 12
#: Controls are 40px tall with a 6px radius, everywhere, without exception.
CONTROL_H = 40
RADIUS = 6
#: The side panel's width. Wide enough for a chapter name and a duration on
#: one line, which is what decided it.
PANEL_W = 430


@dataclass(frozen=True)
class FontReport:
    """What actually loaded, so a build can be checked rather than hoped at."""

    families: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing

    def describe(self) -> str:
        if self.complete:
            return "Typefaces loaded: " + ", ".join(sorted(set(self.families)))
        return "Typefaces missing: " + ", ".join(self.missing)


def load_fonts() -> FontReport:
    """Register the bundled typefaces with Qt.

    Called once, before the first widget exists. Returns what happened
    rather than raising: a Player that is set in Segoe UI is a Player that
    still plays discs, and a font file is not worth a failed launch.
    """
    from PyQt6.QtGui import QFontDatabase

    families: list[str] = []
    missing: list[str] = []
    for path in sorted(FONT_DIR.glob("*.ttf")):
        identifier = QFontDatabase.addApplicationFont(str(path))
        if identifier == -1:
            missing.append(path.name)
            continue
        families.extend(QFontDatabase.applicationFontFamilies(identifier))
    if not FONT_DIR.is_dir():
        missing.append(str(FONT_DIR))
    return FontReport(tuple(families), tuple(missing))


def display_font(size: int, *, italic: bool = True, weight: int = 400):
    """Playfair, for the name of the thing. Italic unless told otherwise."""
    from PyQt6.QtGui import QFont

    font = QFont(DISPLAY)
    font.setPixelSize(size)
    font.setItalic(italic)
    font.setWeight(QFont.Weight(weight))
    return font


def ui_font(size: int, *, weight: int = 400, tracking: float = 0.0):
    """Outfit, for interface. ``tracking`` is in percent of the em."""
    from PyQt6.QtGui import QFont

    font = QFont(UI)
    font.setPixelSize(size)
    font.setWeight(QFont.Weight(weight))
    if tracking:
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + tracking)
    return font


def mono_font(size: int):
    from PyQt6.QtGui import QFont

    font = QFont(MONO)
    font.setPixelSize(size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def tabular(font):
    """Fix the digits to one width, so a running timecode does not shuffle."""
    from PyQt6.QtGui import QFont

    font.setStyleStrategy(QFont.StyleStrategy.PreferDefault)
    features = getattr(font, "setFeature", None)
    if features is not None:  # Qt 6.7+
        try:
            font.setFeature("tnum", 1)
        except Exception:  # a font without the feature is not an error
            pass
    return font


STYLESHEET = f"""
* {{
    font-family: {UI_STACK};
}}

QWidget {{
    background: {INK};
    color: {BONE};
    font-size: 13px;
    font-weight: 400;
}}

/* A label paints its own background by default, which on a raised panel
   means every piece of text sits in a dark rectangle of its own. */
QLabel {{
    background: transparent;
}}

QWidget#panel {{
    background: {RAISED};
    border-left: 1px solid {HAIRLINE};
}}

QWidget#stage {{
    background: {BLACK};
}}

/* -- type roles --------------------------------------------------------- */

/* A volume label is a filename, not a name somebody chose. It is set in the
   interface face, because setting BACKUP_2004 in Playfair italic dresses a
   machine string up as a title. */
QLabel#discLabel {{
    font-family: {UI_STACK};
    font-style: normal;
    font-size: 25px;
    font-weight: 300;
    color: {BONE};
}}

QLabel#discName {{
    font-family: {DISPLAY_STACK};
    font-style: italic;
    font-size: 31px;
    color: {BONE};
}}

QLabel#discNameLarge {{
    font-family: {DISPLAY_STACK};
    font-style: italic;
    font-size: 44px;
    color: {BONE};
}}

QLabel#discBy {{
    font-size: 13px;
    font-weight: 300;
    color: {SOFT};
}}

QLabel#sectionLabel {{
    font-size: 10px;
    font-weight: 500;
    color: {DIM};
    letter-spacing: 2px;
}}

QLabel#body {{
    font-size: 14px;
    font-weight: 300;
    color: {SOFT};
}}

QLabel#note {{
    font-size: 12px;
    font-weight: 300;
    color: {MUTED};
}}

QLabel#smallPrint {{
    font-size: 12px;
    font-weight: 300;
    color: {FAINT};
}}

QLabel#pathLabel {{
    font-family: {MONO_STACK};
    font-size: 12px;
    color: {SOFT};
}}

QLabel#timecode {{
    font-size: 12px;
    color: {BONE};
    min-width: 46px;
}}

QLabel#timecodeMuted {{
    font-size: 12px;
    color: {MUTED};
    min-width: 46px;
}}

/* -- controls ----------------------------------------------------------- */

QPushButton {{
    background: transparent;
    border: 1px solid {HAIRLINE_STRONG};
    border-radius: {RADIUS}px;
    padding: 0 22px;
    min-height: {CONTROL_H}px;
    max-height: {CONTROL_H}px;
    font-size: 13px;
    font-weight: 300;
    color: {BONE};
}}
QPushButton:hover {{ background: {RAISED_HI}; border-color: rgba(232, 226, 214, 0.28); }}
QPushButton:pressed {{ background: {RAISED}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: rgba(232, 226, 214, 0.07); }}
QPushButton:focus {{ border-color: {BRASS}; }}

QPushButton#primary {{
    background: {BRASS};
    color: {INK};
    border: none;
    font-weight: 500;
}}
QPushButton#primary:hover {{ background: {BRASS_HI}; }}
QPushButton#primary:pressed {{ background: {BRASS_DIM}; }}
QPushButton#primary:disabled {{ background: rgba(201, 169, 97, 0.25); color: rgba(13, 15, 20, 0.5); }}

QPushButton#quiet {{
    border: none;
    padding: 0 10px;
    min-height: 30px;
    max-height: 30px;
    font-size: 12px;
    color: {MUTED};
}}
QPushButton#quiet:hover {{ color: {BONE}; background: transparent; }}
QPushButton#quiet:focus {{ color: {BRASS}; }}

/* Same height as the brass one beside it. Two buttons in a row at two
   heights is the kind of thing nobody can name and everybody notices. */
QPushButton#compact {{
    padding: 0 16px;
    font-size: 13px;
    color: {NEAR};
}}

/* -- lists -------------------------------------------------------------- */

QListWidget, QTreeWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{
    padding: {ROW_Y}px {ROW_X}px;
    border-radius: 5px;
    color: {NEAR};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {RAISED_HI}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {BRASS_WASH};
    color: {BONE};
}}

QHeaderView::section {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {HAIRLINE};
    padding: 0 {ROW_X}px 10px {ROW_X}px;
    color: {DIM};
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 2px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(232, 226, 214, 0.14);
    border-radius: 5px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(232, 226, 214, 0.24); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
    height: 0;
    width: 0;
}}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: rgba(232, 226, 214, 0.14);
    border-radius: 5px;
    min-width: 32px;
}}

/* -- fields ------------------------------------------------------------- */

QComboBox {{
    background: transparent;
    border: 1px solid {HAIRLINE_STRONG};
    border-radius: 5px;
    padding: 0 10px;
    min-height: 30px;
    max-height: 30px;
    font-size: 12px;
    font-weight: 300;
    color: {NEAR};
}}
QComboBox:hover {{ border-color: rgba(232, 226, 214, 0.28); }}
QComboBox:focus {{ border-color: {BRASS}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {RAISED};
    border: 1px solid {HAIRLINE_STRONG};
    selection-background-color: {BRASS_WASH};
    selection-color: {BONE};
    padding: 4px;
    outline: none;
}}

/* -- chrome ------------------------------------------------------------- */

QWidget#transport {{
    background: {RAISED};
    border-top: 1px solid {HAIRLINE};
}}
QWidget#transport QPushButton#playOrb {{
    min-height: 0;
    max-height: none;
    padding: 0;
    border: none;
    background: transparent;
}}
QWidget#transport QPushButton#playOrb:hover {{
    background: transparent;
    border: none;
}}

QLabel#goldwingMark {{
    background: transparent;
}}

QWidget#topBar {{
    background: {INK};
    border-bottom: 1px solid rgba(232, 226, 214, 0.06);
}}

QFrame#banner {{
    background: {PROBLEM};
    border: none;
}}
QFrame#banner[tone="notice"] {{ background: rgba(45, 74, 62, 0.55); }}
QFrame#banner QLabel {{
    background: transparent;
    font-size: 12px;
    font-weight: 300;
    color: {PROBLEM_INK};
}}
QFrame#banner[tone="notice"] QLabel {{ color: {NOTICE_INK}; }}
QPushButton#bannerButton {{
    background: transparent;
    border: none;
    padding: 0 8px;
    min-height: 26px;
    max-height: 26px;
    font-size: 12px;
    font-weight: 300;
    color: rgba(232, 226, 214, 0.55);
}}
QPushButton#bannerButton:hover {{ color: {BONE}; }}

QFrame#verdict {{
    background: rgba(45, 74, 62, 0.40);
    border: 1px solid rgba(143, 191, 164, 0.22);
    border-radius: {RADIUS}px;
}}
QFrame#verdict[tone="problem"] {{
    background: rgba(122, 46, 46, 0.35);
    border-color: rgba(200, 130, 130, 0.25);
}}
QFrame#verdict QLabel {{
    background: transparent;
    font-size: 12px;
    font-weight: 300;
    color: {NOTICE_INK};
}}
QFrame#verdict[tone="problem"] QLabel {{ color: {PROBLEM_INK}; }}

QFrame#rule {{
    background: {HAIRLINE};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

QMenuBar {{ background: {INK}; padding: 4px 8px; }}
QMenuBar::item {{
    padding: 5px 12px;
    color: {MUTED};
    font-size: 12px;
    background: transparent;
}}
QMenuBar::item:selected {{ color: {BONE}; }}
QMenu {{
    background: {RAISED};
    border: 1px solid {HAIRLINE_STRONG};
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 300;
    color: {NEAR};
}}
QMenu::item:selected {{ background: {BRASS_WASH}; color: {BONE}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {HAIRLINE}; margin: 6px 10px; }}

QStatusBar {{ background: {INK}; color: {DIM}; font-size: 12px; }}
QStatusBar::item {{ border: none; }}

QMessageBox {{
    background: {RAISED};
}}
QMessageBox QLabel {{
    background: transparent;
    color: {BONE};
    font-size: 13px;
    font-weight: 300;
}}
QMessageBox QPushButton {{
    background: transparent;
    border: 1px solid {HAIRLINE_STRONG};
    border-radius: {RADIUS}px;
    padding: 0 22px;
    min-height: {CONTROL_H}px;
    max-height: {CONTROL_H}px;
    font-size: 13px;
    font-weight: 300;
    color: {BONE};
}}
QMessageBox QPushButton:hover {{ background: {RAISED_HI}; }}
QMessageBox QPushButton:default {{
    background: {BRASS};
    color: {INK};
    border: none;
    font-weight: 500;
}}

QSplitter::handle {{ background: transparent; width: 1px; }}
QSplitter::handle:hover {{ background: {HAIRLINE_STRONG}; }}

QToolTip {{
    background: {RAISED};
    color: {NEAR};
    border: 1px solid {HAIRLINE_STRONG};
    padding: 5px 8px;
    font-size: 12px;
    font-weight: 300;
}}

/* Focus has to be visible from across a room, because the whole thing has
   to work from a gamepad. */
QWidget:focus {{ outline: none; }}
/* Enough to find from across a room, not so much that a list looks
   boxed in whenever it happens to hold the keyboard. */
QListWidget:focus {{
    border: 1px solid rgba(201, 169, 97, 0.20);
    border-radius: {RADIUS}px;
}}
"""
