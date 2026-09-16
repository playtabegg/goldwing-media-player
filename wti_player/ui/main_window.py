"""The Player's one window.

It owns the engine, the drive watcher and the gamepad, and it is the only
place where those three meet. The rule it keeps: **a person never sees a
traceback**. Every path that can fail ends in :meth:`MainWindow.report`, which
takes a sentence.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import shelf, strings
from ..dvd import menu as menu_reader
from ..dvd.navigator import PLAY_CHAPTER, PLAY_TITLE, RESUME, SHOW_MENU, STOP, UNSUPPORTED
from ..dvd.session import MenuSession
from ..engine.base import (
    AudioCdInfo,
    EngineEvent,
    MediaTarget,
    PlaybackEngine,
    PlaybackState,
)
from ..formats import ifo
from ..inputs.actions import SKIP_MS, VOLUME_STEP, PlayerAction
from ..inputs.gamepad import GamepadSource, XInputReader
from ..inputs.keymap import action_for
from ..optical.drives import DriveEventKind, DriveWatcher
from ..optical.identify import DiscKind, DiscProfile
from ..optical.reader import DiscReader, ThreadedReader
from ..version import window_title
from . import artwork, theme, views
from .menu_surface import MenuSurface
from .prefs import IMAGE_SUFFIXES, Preferences, QtPreferences, remember
from .preview import PreviewPanel
from .transport import Mode, TransportBar
from .views import (
    AudioCdView,
    Banner,
    BrowserView,
    GameView,
    TitleListView,
    TopBar,
    VideoSurface,
    WelcomeView,
)

#: How often to look for a disc going in. A drive takes longer than this to
#: spin up, so nothing is gained by looking harder.
DRIVE_POLL_MS = 1500
#: The position readout only has to be right to the second.
TICK_MS = 250
#: A gamepad has to feel immediate, so it is read every frame-ish.
PAD_POLL_MS = 33
#: How long the chrome stays up in full screen once the mouse stops. Three
#: seconds: long enough to find a control, short enough to get out of the way.
CHROME_IDLE_MS = 3000

#: How far a pressed chapter mark may sit from the time the document names
#: and still be the same chapter. An encoder snaps a mark to the nearest
#: keyframe, so a second or two of drift is normal and expected; ten seconds
#: is a different chapter.
CHAPTER_MATCH_MS = 4000


def _name_for(mark_ms: int, chapters) -> str:
    """The document's name for a mark, matched on time.

    Empty when no chapter is close enough. An unnamed mark is honest; a mark
    wearing the next chapter's name is not.
    """
    best = ""
    closest = CHAPTER_MATCH_MS + 1
    for chapter in chapters:
        distance = abs(chapter.start_ms - mark_ms)
        if distance < closest:
            best, closest = chapter.title, distance
    return best


class MainWindow(QMainWindow):
    #: libvlc calls its listeners from its own threads. Touching a widget from
    #: one of those is how a player ends up frozen with the video still
    #: running, so every engine event crosses back onto the GUI thread here
    #: before anything looks at it.
    engine_event = pyqtSignal(object)

    def __init__(
        self,
        engine: PlaybackEngine,
        *,
        watcher: DriveWatcher | None = None,
        gamepad: GamepadSource | None = None,
        reader: DiscReader | None = None,
        auto_play: bool = True,
        prefs: Preferences | None = None,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.watcher = watcher or DriveWatcher()
        # Reading a disc touches an optical drive, which can take seconds. It
        # happens on a worker so the window keeps painting.
        self.reader: DiscReader = reader or ThreadedReader()
        self.profile: DiscProfile | None = None
        self.preview_mode = False
        self.auto_play = auto_play
        #: What the Player remembers between runs: window, volume, recent.
        self.prefs: Preferences = prefs if prefs is not None else QtPreferences()
        self._elapsed_ms = 0
        #: The DVD title playing, when one is. DVDs carry their structure in
        #: their IFOs, not in anything the engine can tell us.
        self._dvd_title: ifo.Title | None = None
        self._pending_seek_ms = 0
        self._volume = 100
        self._volume_before_mute = 100
        #: The title we asked for. libbluray reports First Play as the
        #: current title for the whole run of a feature, so what we chose is
        #: the only reliable answer to "what is playing".
        self._chosen_title: int | None = None
        #: The length the transport was last told about, so a disc that
        #: discovers its own duration late gets its chapter marks redrawn.
        self._known_duration_ms = 0
        #: A DVD menu, when one is up. Its own widget and its own video sink,
        #: so that if this path has a bad day, films still play.
        self._dvd_menu: MenuSession | None = None
        #: Where the film was when the menu was called for.
        self._resume_ms = 0
        #: Whether the side panel was showing before full screen took it away.
        self._panel_wanted = True
        #: Whether anything has actually played off the disc now in the
        #: drive. Cleared on every open, set on the first PLAYING.
        self._playing_started = False
        #: The audio CD track playing, when one is. A CD has no chapters
        #: and no titles the engine will talk about, so this is the only
        #: record of where on the disc we are.
        self._track = 0
        #: Set in closeEvent. A worker's answer can still be queued when
        #: the window goes, and acting on it means driving a released
        #: engine.
        self._closing = False
        #: The update check, made the first time the Help menu asks for one
        #: and never before. The update package is not imported until then,
        #: so a disc plays whether or not that package works.
        self._update_check = None
        self._update_box = None

        self.setWindowTitle(window_title())
        self.setWindowIcon(theme.window_icon())
        self.resize(1180, 720)
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menus()
        remembered = self.prefs.geometry()
        if remembered:
            # After the UI, so a layout's minimum size cannot undo it. A
            # saved shape from a monitor that is gone is Qt's problem to
            # clamp; a shape that does not restore leaves the default.
            self.restoreGeometry(remembered)
        # Every label in the window, told not to render markup. A disc
        # supplies its own title, author and chapter names, and a QLabel
        # left on AutoText turns those into a document that fetches files.
        views.keep_labels_plain(self)

        self.engine_event.connect(self._on_engine_event, Qt.ConnectionType.QueuedConnection)
        self.engine.add_listener(self.engine_event.emit)
        saved_volume = self.prefs.volume()
        self._set_volume(saved_volume if saved_volume is not None else 100)

        self._gamepad = gamepad if gamepad is not None else GamepadSource()
        self._pad_reader = XInputReader()

        self._drive_timer = QTimer(self)
        self._drive_timer.timeout.connect(self.poll_drives)
        self._drive_timer.start(DRIVE_POLL_MS)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(TICK_MS)

        if self._gamepad.available:
            self._pad_timer = QTimer(self)
            self._pad_timer.timeout.connect(self._poll_gamepad)
            self._pad_timer.start(PAD_POLL_MS)

        self.poll_drives()

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.top_bar = TopBar()
        self.top_bar.toggle_panel.connect(self.toggle_panel)
        self.top_bar.go_home.connect(self.show_welcome)
        layout.addWidget(self.top_bar)

        self.banner = Banner()
        layout.addWidget(self.banner)

        self.stack = QStackedWidget()
        self.welcome = WelcomeView()
        self.welcome.open_folder.connect(self.choose_folder)
        self.welcome.open_image.connect(self.choose_image)
        self.welcome.open_drive.connect(lambda mount: self.open_path(Path(mount)))
        self.welcome.add_to_shelf.connect(self.choose_shelf_folder)
        self.welcome.open_shelf_entry.connect(lambda root: self.open_shelf_entry(Path(root)))

        self.video = VideoSurface()
        self.video.double_clicked.connect(self.toggle_fullscreen)

        self.titles = TitleListView()
        self.titles.play_title.connect(self.play_title)
        self.titles.play_main_feature.connect(self.play_main_feature)
        self.titles.open_menu.connect(lambda: self.do(PlayerAction.TOP_MENU))

        self.preview = PreviewPanel()
        self.preview.hide()

        self.player_page = QSplitter(Qt.Orientation.Horizontal)
        self.player_page.setHandleWidth(1)
        self.player_page.setChildrenCollapsible(False)
        self.player_page.addWidget(self.video)

        # The panel can leave. A film should be able to have the whole window
        # without going full screen, and a film is the point.
        self.panel = QWidget()
        self.panel.setObjectName("panel")
        self.panel.setMinimumWidth(360)
        side_layout = QVBoxLayout(self.panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(0)
        side_layout.addWidget(self.titles)
        side_layout.addWidget(self.preview)
        self.player_page.addWidget(self.panel)
        self.player_page.setStretchFactor(0, 1)
        self.player_page.setStretchFactor(1, 0)
        self.player_page.setSizes([1010, theme.PANEL_W])

        # A DVD menu draws itself: the surface owns the queued connection
        # that gets a frame from libvlc's thread onto this one.
        self.menu_surface = MenuSurface()
        self.menu_surface.button_clicked.connect(self._on_menu_click)
        self.menu_surface.cursor_moved.connect(self._on_menu_pointer)

        self.browser = BrowserView()
        self.browser.open_file.connect(self.open_from_browser)
        self.game = GameView()
        self.game.go_home.connect(self.show_welcome)
        self.game.open_menu.connect(self.open_game_menu_now)
        self.game.open_file.connect(self.open_from_browser)
        self.audio_cd = AudioCdView()
        self.audio_cd.play_track.connect(self.play_track)

        for widget in (
            self.welcome,
            self.player_page,
            self.browser,
            self.game,
            self.audio_cd,
            self.menu_surface,
        ):
            self.stack.addWidget(widget)
        layout.addWidget(self.stack, 1)

        self.transport = TransportBar()
        self.transport.play_pause.connect(lambda: self.do(PlayerAction.PLAY_PAUSE))
        self.transport.stop.connect(self.stop)
        self.transport.seek.connect(self.engine.seek)
        self.transport.step.connect(
            lambda direction: self.do(
                PlayerAction.SKIP_FORWARD if direction > 0 else PlayerAction.SKIP_BACK
            )
        )
        self.transport.previous_chapter.connect(
            lambda: self.do(PlayerAction.PREVIOUS_CHAPTER)
        )
        self.transport.next_chapter.connect(lambda: self.do(PlayerAction.NEXT_CHAPTER))
        self.transport.top_menu.connect(lambda: self.do(PlayerAction.TOP_MENU))
        self.transport.volume_changed.connect(self._set_volume)
        self.transport.mute_toggled.connect(self.toggle_mute)
        self.transport.audio_track_chosen.connect(self.engine.select_audio_track)
        self.transport.subtitle_track_chosen.connect(self.engine.select_subtitle_track)
        self.transport.fullscreen.connect(self.toggle_fullscreen)
        self.transport.eject.connect(self.eject)
        self.transport.hide()
        layout.addWidget(self.transport)

        self.setCentralWidget(central)
        # The transport is the footer. A status bar under it was a second
        # strip of chrome, and with the play button it read as a doubled bar.
        self.statusBar().hide()

        # Full screen: the chrome fades once the pointer has been still for a
        # few seconds, and comes back on the first movement.
        self._chrome_timer = QTimer(self)
        self._chrome_timer.setSingleShot(True)
        self._chrome_timer.timeout.connect(self._hide_chrome)
        self.setMouseTracking(True)
        central.setMouseTracking(True)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        disc_menu = bar.addMenu("&Disc")
        self._add(disc_menu, "Open a &folder…", self.choose_folder, "Ctrl+O")
        self._add(disc_menu, "Open a disc &image…", self.choose_image, "Ctrl+I")
        self.recent_menu = disc_menu.addMenu(strings.OPEN_RECENT)
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        self._fill_recent_menu()
        disc_menu.addSeparator()
        # W2: the shelf, and a game's own menu, by path and nothing else.
        add_shelf = self._add(disc_menu, strings.ADD_TO_SHELF, self.choose_shelf_folder)
        add_shelf.setToolTip(strings.ADD_TO_SHELF_TIP)
        add_shelf.setStatusTip(strings.ADD_TO_SHELF_TIP)
        self.game_menu_action = self._add(disc_menu, strings.OPEN_GAME_MENU, self.open_game_menu_now)
        self.game_menu_action.setEnabled(False)
        disc_menu.addSeparator()
        self._add(disc_menu, strings.GO_HOME, self.show_welcome)
        self._add(disc_menu, "&Eject", self.eject, "Ctrl+E")
        disc_menu.addSeparator()
        self._add(disc_menu, "E&xit", self.close, "Ctrl+Q")

        play_menu = bar.addMenu("&Play")
        self._add(play_menu, strings.PLAY_MAIN_FEATURE, self.play_main_feature)
        self._add(play_menu, "Play / pause", lambda: self.do(PlayerAction.PLAY_PAUSE), "Space")
        self._add(play_menu, "Stop", self.stop)
        play_menu.addSeparator()
        self._add(play_menu, "Top menu", lambda: self.do(PlayerAction.TOP_MENU), "M")
        self._add(play_menu, "Pop-up menu", lambda: self.do(PlayerAction.POPUP_MENU), "P")
        play_menu.addSeparator()
        self._add(
            play_menu, "Previous chapter", lambda: self.do(PlayerAction.PREVIOUS_CHAPTER), "B"
        )
        self._add(play_menu, "Next chapter", lambda: self.do(PlayerAction.NEXT_CHAPTER), "N")

        view_menu = bar.addMenu("&View")
        self._add(view_menu, "Full screen", self.toggle_fullscreen, "F")
        view_menu.addSeparator()
        self.preview_action = QAction(strings.PREVIEW_TITLE, self, checkable=True)
        self.preview_action.triggered.connect(self.set_preview_mode)
        view_menu.addAction(self.preview_action)

        help_menu = bar.addMenu("&Help")
        self._add(help_menu, strings.UPDATE_MENU, self.check_for_updates)
        help_menu.addSeparator()
        self._add(help_menu, strings.ABOUT_TITLE, self.show_about)

    def _fill_recent_menu(self) -> None:
        """The last few folders and images opened by hand, newest first."""
        menu = self.recent_menu
        menu.clear()
        recent = self.prefs.recent()
        if not recent:
            empty = menu.addAction(strings.RECENT_EMPTY)
            empty.setEnabled(False)
            return
        for path in recent:
            action = menu.addAction(str(path))
            action.triggered.connect(lambda _checked=False, p=path: self.open_path(p))
        menu.addSeparator()
        menu.addAction(strings.CLEAR_RECENT, self._forget_recent)

    def _forget_recent(self) -> None:
        self.prefs.set_recent([])
        self.prefs.sync()
        self._fill_recent_menu()

    def _remember(self, path: Path) -> None:
        """Only what a person chose: a folder or an image, never a drive,
        and nothing that lives on a drive a disc can leave."""
        known = self.watcher.drives
        drives = known() if callable(known) else known
        roots = {d.mount for d in drives}
        updated = remember(self.prefs.recent(), path, drive_roots=roots)
        if updated != self.prefs.recent():
            self.prefs.set_recent(updated)
            self.prefs.sync()

    # -- drag and drop -----------------------------------------------------

    @staticmethod
    def _dropped_path(event) -> Path | None:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_dir() or path.suffix.lower() in IMAGE_SUFFIXES:
                return path
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        path = self._dropped_path(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.open_path(path)

    def _add(self, menu, text: str, slot, shortcut: str = "") -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # -- opening things ----------------------------------------------------

    def poll_drives(self) -> None:
        try:
            events = self.watcher.poll()
        except OSError:
            return
        self.welcome.set_drives(self.watcher.drives)
        for event in events:
            if event.kind is DriveEventKind.INSERTED:
                self.on_disc_inserted(event.drive)
            elif event.kind in (DriveEventKind.EJECTED, DriveEventKind.REMOVED):
                if self.profile is not None and self.profile.root == event.drive.root:
                    self.stop()
                    self.show_welcome()

    def on_disc_inserted(self, drive) -> None:
        if self.auto_play:
            self.open_path(drive.root, label=drive.label)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open a disc folder")
        if folder:
            self.open_path(Path(folder))

    def choose_image(self) -> None:
        image, _ = QFileDialog.getOpenFileName(
            self, "Open a disc image", "", "Disc images (*.iso *.img *.bin);;All files (*)"
        )
        if image:
            self.open_path(Path(image))

    def open_from_browser(self, path: Path) -> None:
        """Somebody double-clicked a file in the disc's file listing.

        Not every file on a data disc is a disc. Handing a README to the disc
        reader threw the listing away, put the welcome screen up and said
        "That is a file, not a disc" — for doing the one obvious thing the
        listing invites. A file goes to whatever opens it on this machine;
        the listing stays where it is.
        """
        if path.is_dir() or path.suffix.lower() in (".iso", ".img", ".bin"):
            self.open_path(path)
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.report(strings.cannot_open_file(path.name), tone="notice")

    def open_path(self, path: Path, *, label: str = "", preview: bool = False) -> None:
        """Look at what is there, then hand the right thing to the engine.

        The looking happens on a worker: an optical drive can spin up, seek
        and retry for seconds, and a window that stops painting while it does
        looks broken.
        """
        if (
            not preview
            and self.profile is not None
            and self.profile.root == path
            and self.engine.state.is_active
        ):
            # Opening what is already open used to restart it from the
            # beginning without a word, which is not what anyone means by it.
            return
        # Whatever was on before is over: its menu session holds the engine's
        # frame callback, and leaving it running means the arrow keys go on
        # driving a menu that is no longer on the screen.
        self.leave_dvd_menu(resume=False)
        if self.preview_mode and not preview:
            self.set_preview_mode(False)
        self._playing_started = False
        self.banner.hide()
        self.top_bar.set_where(strings.READING_DISC)
        self.top_bar.set_home_visible(True)
        # Something has to say the drive is being read. It is the one moment
        # the Player can look like it has stopped working.
        self.transport.set_mode(Mode.READING)
        self.transport.show()
        self._chosen_title = None
        artwork.forget()
        self.reader.read(path, label, lambda profile: self._on_disc_read(path, profile))

    def _on_disc_read(self, path: Path, profile: DiscProfile) -> None:
        if self._closing:
            return
        self.profile = profile
        self.transport.set_mode(Mode.PLAYBACK)
        # The disc's name is on the page and in the window title. Putting it
        # in the top bar as well was a second header next to the bird.
        self.top_bar.set_where("")
        self.top_bar.set_home_visible(True)

        # A disc somebody paid for deserves the whole reason, not a shrug.
        if profile.protection == "aacs":
            self.explain(strings.PROTECTED_BLU_RAY_TITLE, strings.PROTECTED_BLU_RAY, offer_eject=True)
            self.show_welcome()
            return
        if profile.problem:
            self.report(profile.problem)
            # A refusal is not advice. Saying "the Player will not open it" and
            # then opening it is worse than either on its own, and on a damaged
            # seek index it is the crash the message exists to prevent.
            if profile.refuses or not profile.titles:
                self.show_welcome(keep_message=True)
                return

        if profile.kind is DiscKind.EMPTY:
            self.report(strings.DRIVE_EMPTY, tone="notice")
            self.show_welcome(keep_message=True)
            return
        if profile.kind is DiscKind.UNREADABLE:
            self.show_welcome()
            return
        # A disc that read as a disc, chosen by hand: worth a place in Recent.
        self._remember(path)
        if profile.kind is DiscKind.AUDIO_CD:
            self.open_audio_cd(profile)
            return
        # W2: a game disc in the drive can open its own menu from the Disc menu.
        self.game_menu_action.setEnabled(
            profile.kind is DiscKind.GAME_DISC
            and profile.ours
            and shelf.menu_executable(profile.root) is not None
        )
        if profile.kind is DiscKind.GAME_DISC:
            self.game.show_disc(profile)
            self.stack.setCurrentWidget(self.game)
            self.transport.hide()
            self.top_bar.set_panel_available(False)
            self.setWindowTitle(window_title(profile.display_name))
            return
        if profile.browsable:
            self.browser.show_disc(profile)
            self.stack.setCurrentWidget(self.browser)
            self.transport.hide()
            self.top_bar.set_panel_available(False)
            self.setWindowTitle(window_title(profile.display_name))
            return

        if profile.kind is DiscKind.DVD_VIDEO:
            if profile.root.is_file():
                self.start(MediaTarget.dvd(profile.root), profile)
                return
            self.start_dvd(profile)
            return
        self.start(MediaTarget.blu_ray(profile.root), profile)

    def open_audio_cd(self, profile: DiscProfile) -> None:
        info = self._audio_cd_info(profile)
        album = info.album or profile.display_name
        self.audio_cd.show_disc(
            profile, info.names(), album=album, artist=info.artist
        )
        self.stack.setCurrentWidget(self.audio_cd)
        self.transport.set_chapters([])
        # A CD has tracks, not chapters, and the skip buttons hide themselves
        # when there are no chapters. On a CD they are the whole interaction,
        # so they are asked for by name.
        self.transport.set_skip_available(len(profile.titles) > 1)
        self.transport.set_mode(Mode.PLAYBACK)
        self.top_bar.set_panel_available(False)
        self.transport.show()
        self.setWindowTitle(window_title(album if info.album else strings.AUDIO_CD))
        self.play_track(0)

    def _audio_cd_info(self, profile: DiscProfile) -> AudioCdInfo:
        """What the disc says about itself, when the engine can ask it.

        A disc that will not tell us its track names is not an error; it is a
        disc with no CD-TEXT, and it gets numbered tracks and a drawn face.
        """
        reader = getattr(self.engine, "audio_cd_info", None)
        if not callable(reader):
            return AudioCdInfo()
        try:
            return reader(MediaTarget.audio_cd(str(profile.root)))
        except Exception:
            return AudioCdInfo()

    def play_track(self, index: int) -> None:
        if self.profile is None:
            return
        if not 0 <= index < max(1, len(self.profile.titles)):
            return
        self._track = index
        self._playing_started = False
        self.audio_cd.set_playing(index)
        self.engine.open(MediaTarget.audio_cd(str(self.profile.root), track=index))

    def _step_track(self, direction: int) -> bool:
        """Next or previous track. False when there is no such track.

        Back goes to the start of this one first, then to the one before, the
        way it does on every CD player anyone has ever used.
        """
        if self.profile is None or self.profile.kind is not DiscKind.AUDIO_CD:
            return False
        if direction < 0 and self.engine.position_ms > 3000:
            self.engine.seek(0)
            return True
        target = self._track + direction
        if not 0 <= target < len(self.profile.titles):
            return False
        self.play_track(target)
        return True

    def _play_next_track(self) -> bool:
        return self._step_track(1)

    def start(self, target: MediaTarget, profile: DiscProfile) -> None:
        self.stack.setCurrentWidget(self.player_page)
        self.top_bar.set_panel_available(True)
        self.transport.show()
        self.titles.show_profile(profile)
        self.transport.set_menu_available(profile.has_menu)
        self.setWindowTitle(window_title(profile.display_name))
        self.engine.set_video_window(self.video.native_handle())
        self.engine.open(target)
        self.video.setFocus()

    def start_dvd(self, profile: DiscProfile) -> None:
        """Show a DVD's titles, then start whichever one is the feature."""
        self.stack.setCurrentWidget(self.player_page)
        self.top_bar.set_panel_available(True)
        self.transport.show()
        self.titles.show_profile(profile)
        self.transport.set_menu_available(profile.has_menu)
        self.setWindowTitle(window_title(profile.display_name))
        self.engine.set_video_window(self.video.native_handle())
        self.video.setFocus()
        if profile.main_feature is not None:
            self.play_title(profile.main_feature)

    def _publish_chapters(self) -> None:
        """Put the disc's chapter marks on the scrub bar, named where we can.

        The marks come from the disc; the names come from the document the
        factory wrote. They are matched **by time**, not by position, and
        that is the whole point of this method.

        Position looks right and is wrong. The factory always presses a mark
        at zero, whether or not the author put a chapter there — a playlist
        with no marks is not seekable at all — and it drops any mark that
        falls past the end of the film. So the two lists are different
        lengths on most discs, and pairing them by index shifts every name
        onto the chapter before it. On a film whose author did not type a
        chapter at 0:00, which is most of them, every single name was wrong.
        """
        marks = self._chapter_marks()
        chapters = self.profile.meta.movie.chapters if self._has_named_chapters else ()
        self.transport.set_chapters(
            [(mark, _name_for(mark, chapters)) for mark in marks]
        )

    @property
    def _has_named_chapters(self) -> bool:
        return (
            self.profile is not None
            and self.profile.meta is not None
            and self.profile.meta.movie is not None
            and bool(self.profile.meta.movie.chapters)
        )

    def _play_dvd_title(self, number: int) -> bool:
        """Open one DVD title: its own VOBs, seeked to where the title starts."""
        if self.profile is None:
            return False
        try:
            disc = ifo.read(self.profile.root)
        except ifo.IfoError:
            self.report(strings.CANNOT_READ_DISC)
            return False
        title = disc.title(number)
        if title is None:
            self.report(strings.NOTHING_TO_PLAY)
            return False
        vobs = disc.vob_files(title)
        if not vobs:
            self.report(strings.NOTHING_TO_PLAY)
            return False

        self._dvd_title = title
        self.engine.open(MediaTarget.dvd_title(vobs))
        # Several titles can share one title set's stream, so a title that is
        # not the first one starts partway in.
        self._pending_seek_ms = title.start_ms if title.start_ms else 0
        return True

    # -- DVD menus ---------------------------------------------------------
    #
    # A DVD menu is the one thing in the Player that does not go through the
    # ordinary playback path, and it is kept that way on purpose. Its video
    # goes through a buffer rather than a window, because the subpicture and
    # the highlight have to be composited over the picture and nothing can be
    # composited over video the graphics card is painting straight to a
    # window. Leaving the menu puts everything back the way films need it.

    def show_dvd_menu(self, *, kind: str = "", title_set: int | None = None) -> bool:
        """Ask for this DVD's menu. False when the disc is not a DVD.

        The read happens off the interface's thread (``reader.run``): it is
        seconds on a warm cache and twenty off a drive, and it used to
        freeze the window for all of it. ``_menu_read`` puts the menu up
        when the answer lands; a stale answer (the user left, ejected, or
        asked again) is dropped by generation.

        ``title_set`` names the menu's title set; a button that jumps to
        another set's menu says which, and the film's own set is the
        default, so a submenu is read from where it actually lives.
        """
        if self.profile is None or self.profile.kind is not DiscKind.DVD_VIDEO:
            return False

        if self._dvd_menu is None:
            # Only the FIRST menu remembers where the film was. A submenu
            # opened from a menu would otherwise record the menu loop's own
            # position, and "resume" would restart the film from the top.
            self._resume_ms = self.engine.position_ms
        # A menu opened over a menu keeps the old one on screen until the
        # new one has been read; it is taken down in _menu_read, so a slow
        # read never shows a dead surface and a failed one leaves the menu
        # the viewer had.

        chosen_set = title_set or getattr(self._dvd_title, "title_set", 0) or 1
        root = self.profile.root
        self._menu_generation = getattr(self, "_menu_generation", 0) + 1
        generation = self._menu_generation
        self.transport.set_mode(Mode.READING, waiting_for=strings.READING_MENU)
        self.transport.show()
        self.reader.run(
            "dvd menu",
            lambda: menu_reader.read(root, title_set=chosen_set, kind=kind),
            lambda found: self._menu_read(found, generation),
        )
        return True

    def _menu_read(self, found, generation: int) -> None:
        """The menu came back from the reader; put it up if it is still wanted."""
        if self._closing or generation != getattr(self, "_menu_generation", 0):
            return
        if found is None:
            self.transport.set_mode(Mode.PLAYBACK)
            self.report(strings.NO_DVD_MENU, tone="notice")
            return

        if self._dvd_menu is not None:
            # The old one lets go of the engine before the new one takes it,
            # or its buffer and its callbacks are both left behind.
            self._dvd_menu.stop()
            self._dvd_menu = None
        session = MenuSession(self.engine)
        session.start_with(found, on_frame=self.menu_surface.frame_ready.emit)
        self._dvd_menu = session
        buffer = session.buffer
        if buffer is not None:
            self.menu_surface.attach_buffer(
                buffer,
                session.width,
                session.height,
                getattr(self.engine, "frame_lock", lambda: None)(),
            )
        self.menu_surface.show_menu(**session.presentation())
        self.stack.setCurrentWidget(self.menu_surface)
        self.transport.set_mode(Mode.MENU)
        self.menu_surface.setFocus()
        # The disc's own entry action: a menu that arrives with a button
        # already activated says what to do, and it used to be dropped. A
        # menu whose entry action is another menu is a loop by definition
        # (each read would re-enter here), so that one is declined.
        entry = found.entry_action
        if entry is not None and entry.kind == SHOW_MENU:
            self.report(strings.menu_command_unsupported("a menu that opens a menu on arrival"), tone="notice")
        elif entry is not None:
            self._carry_out(entry)

    def leave_dvd_menu(self, *, resume: bool = True) -> None:
        """Take the menu down and give the engine back to the film.

        The screen is restored whether or not a session is up. A submenu
        that never came up after a menu that did (a dead submenu) left
        ``_dvd_menu`` empty and the surface current, and the early return
        that used to sit here stranded the viewer on a blank surface.
        """
        # Anything still being read for the menu we are leaving is stale now.
        self._menu_generation = getattr(self, "_menu_generation", 0) + 1
        surface_up = self.stack.currentWidget() is self.menu_surface
        if self._dvd_menu is None and not surface_up:
            return
        if self._dvd_menu is not None:
            self._dvd_menu.stop()
            self._dvd_menu = None
        self.menu_surface.clear_menu()
        self.stack.setCurrentWidget(self.player_page)
        self.transport.set_mode(Mode.PLAYBACK)
        self.engine.set_video_window(self.video.native_handle())
        if resume and self.profile is not None and self._chosen_title is not None:
            self.play_title(self._chosen_title)
            if self._resume_ms:
                self._pending_seek_ms = self._resume_ms
        self.video.setFocus()

    def _redraw_menu(self) -> None:
        """The selection moved, so the lit button changed.

        ``set_selection`` rather than ``show_menu``: the picture and the
        palette have not changed, and re-sending them throws away the caches
        that make moving a highlight cost 0.009 ms instead of 98.
        """
        if self._dvd_menu is not None:
            self.menu_surface.set_selection()

    def _on_menu_pointer(self, x: int, y: int) -> None:
        if self._dvd_menu is not None and self._dvd_menu.point_at(x, y):
            self._redraw_menu()

    def _on_menu_click(self, x: int, y: int) -> None:
        if self._dvd_menu is not None:
            self._carry_out(self._dvd_menu.click_at(x, y))

    def _carry_out(self, action) -> None:
        """Do what a menu button asked for, in the player's own terms."""
        if action.kind == UNSUPPORTED:
            self.report(strings.menu_command_unsupported(action.reason), tone="notice")
            return
        if action.kind in (PLAY_TITLE, PLAY_CHAPTER):
            # A DVD's titles are 1-based in its own tables, and that is the
            # numbering everything here speaks. Only libvlc counts from zero,
            # and a DVD never reaches it — so subtracting one sent "play
            # title 1", which is what nearly every disc's Play button says,
            # to a title that does not exist. An instruction that names no
            # title at all (LinkPTT, LinkPGN) means "this one".
            number = action.title or self._chosen_title or 1
            self.leave_dvd_menu(resume=False)
            if not self.play_title(number):
                return
            if action.kind == PLAY_CHAPTER and action.chapter > 1:
                self._seek_to_chapter(action.chapter)
            return
        if action.kind == SHOW_MENU:
            self.show_dvd_menu(kind=action.menu, title_set=action.title_set or None)
            return
        if action.kind == RESUME:
            self.leave_dvd_menu(resume=True)
            return
        if action.kind == STOP:
            self.leave_dvd_menu(resume=False)
            self.stop()
            return
        # "nothing" — a move, or a button the disc left empty.
        self._redraw_menu()

    def _seek_to_chapter(self, chapter: int) -> None:
        marks = self._chapter_marks()
        if 1 <= chapter <= len(marks):
            self._pending_seek_ms = marks[chapter - 1]

    def show_welcome(self, *, keep_message: bool = False) -> None:
        # A read still in flight will otherwise land after this and put the
        # disc somebody just walked away from straight back on the screen.
        self.reader.cancel()
        self.leave_dvd_menu(resume=False)
        if self.preview_mode:
            self.set_preview_mode(False)
        if not keep_message:
            self.banner.hide()
        self.profile = None
        self._chosen_title = None
        self._playing_started = False
        self.stop()
        self.stack.setCurrentWidget(self.welcome)
        self.transport.hide()
        self.transport.set_mode(Mode.PLAYBACK)
        self.transport.set_chapters([])
        self.top_bar.set_where("")
        self.top_bar.set_home_visible(False)
        self.top_bar.set_panel_available(False)
        self.setWindowTitle(window_title())
        self.welcome.set_drives(self.watcher.drives)
        self.welcome.set_shelf(shelf.scan(self.prefs.shelf()))
        self.game_menu_action.setEnabled(False)
        # A disc that has left the drive should not keep its picture in memory.
        artwork.forget()

    # -- the shelf (W2) ----------------------------------------------------

    def choose_shelf_folder(self) -> None:
        """Add a local copy of a disc to the shelf, by its folder."""
        chosen = QFileDialog.getExistingDirectory(self, strings.ADD_TO_SHELF)
        if not chosen:
            return
        root = Path(chosen)
        if shelf.read_entry(root) is None:
            self.report(strings.NOT_A_COPY)
            return
        self.prefs.set_shelf(shelf.add_root(self.prefs.shelf(), root))
        self.prefs.sync()
        self.welcome.set_shelf(shelf.scan(self.prefs.shelf()))

    def open_shelf_entry(self, root: Path) -> None:
        """A film or an album plays from its copy; a game's copy opens its own menu."""
        entry = shelf.read_entry(root)
        if entry is None:
            self.prefs.set_shelf(shelf.remove_root(self.prefs.shelf(), root))
            self.prefs.sync()
            self.welcome.set_shelf(shelf.scan(self.prefs.shelf()))
            self.report(strings.NOT_A_COPY)
            return
        if entry.kind == "game":
            self._open_game_menu(root)
            return
        self.open_path(root)

    def open_game_menu_now(self) -> None:
        """The Disc menu action: the current game disc's own menu."""
        if (
            self.profile is not None
            and self.profile.kind is DiscKind.GAME_DISC
            and self.profile.ours
        ):
            self._open_game_menu(self.profile.root)

    def _open_game_menu(self, root: Path) -> None:
        try:
            shelf.open_game_menu(root)
        except shelf.MenuMissing:
            self.report(strings.GAME_MENU_MISSING)
            return
        except OSError as error:
            self.report(f"{strings.GAME_MENU_MISSING} ({error})")
            return
        self.report(strings.GAME_MENU_OPENED, tone="notice")

    # -- playback ----------------------------------------------------------

    def play_main_feature(self) -> None:
        if self.profile is None:
            return
        engine_feature = getattr(self.engine, "main_feature_title", None)
        number = engine_feature() if callable(engine_feature) else None
        if number is None:
            number = self.profile.main_feature
        if number is None:
            self.report(strings.NOTHING_TO_PLAY)
            return
        self.play_title(number)

    def play_title(self, number: int) -> bool:
        """Start one title. False when there was nothing to start.

        The answer matters: a caller that seeks afterwards must not arm a
        seek for a title that never opened, or the next thing somebody plays
        silently starts partway in.
        """
        self._chosen_title = number
        self.titles.set_playing(number)
        if self.profile is not None and self.profile.kind is DiscKind.DVD_VIDEO:
            return self._play_dvd_title(number)
        self.engine.select_title(number)
        self.engine.play()
        # A title change does not raise PLAYING when something is already
        # playing, so the marks are asked for again here rather than waiting
        # for an event that is not coming.
        QTimer.singleShot(400, self._publish_chapters)
        return True

    def stop(self) -> None:
        self.engine.stop()
        self.transport.set_state(PlaybackState.STOPPED)

    def eject(self) -> None:
        self.stop()
        self.show_welcome()
        self.report("Playback stopped. Use the drive's own button to open it.", tone="notice")

    def toggle_fullscreen(self) -> None:
        if not self.isFullScreen() and not self._has_picture():
            # A file listing full screen has no menu bar, no top bar and no
            # transport: nothing on the screen a pointer can press, and
            # nothing saying that Esc gets the window back.
            self.report(strings.NOTHING_TO_FILL_THE_SCREEN, tone="notice")
            return
        if self.isFullScreen():
            self._chrome_timer.stop()
            self._show_chrome()
            self.showNormal()
            self.menuBar().show()
            self.top_bar.show()
            self.panel.setVisible(self._panel_wanted)
        else:
            self._panel_wanted = self.panel.isVisible()
            self.menuBar().hide()
            self.top_bar.hide()
            self.panel.hide()
            self.showFullScreen()
            self._chrome_timer.start(CHROME_IDLE_MS)
        self.transport.set_fullscreen(self.isFullScreen())

    def toggle_panel(self) -> None:
        """Let the film have the whole window without going full screen."""
        showing = not self.panel.isVisible()
        self.panel.setVisible(showing)
        self._panel_wanted = showing
        self.top_bar.panel_button.setToolTip(
            strings.HIDE_PANEL if showing else strings.SHOW_PANEL
        )

    def toggle_mute(self) -> None:
        if self._volume:
            self._volume_before_mute = self._volume
            self._set_volume(0)
        else:
            self._set_volume(self._volume_before_mute or 100)

    def _set_volume(self, percent: int) -> None:
        self._volume = max(0, min(100, percent))
        self.engine.set_volume(self._volume)
        self.transport.set_volume(self._volume)

    def _has_picture(self) -> bool:
        """Is there video on the screen right now?"""
        if self._dvd_menu is not None:
            return True
        return self.profile is not None and self.profile.kind.is_video

    # -- chrome in full screen ---------------------------------------------

    def _hide_chrome(self) -> None:
        if self.isFullScreen() and self.engine.state is PlaybackState.PLAYING:
            self.transport.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)

    def _show_chrome(self) -> None:
        self.unsetCursor()
        if self.profile is not None and self.profile.playable:
            self.transport.show()

    def mouseMoveEvent(self, event) -> None:
        if self.isFullScreen():
            self._show_chrome()
            self._chrome_timer.start(CHROME_IDLE_MS)
        super().mouseMoveEvent(event)

    def set_preview_mode(self, on: bool) -> None:
        """Menu preview mode: open a BDMV folder and walk its menus.

        The menu plays as it would on a disc, and beside it the panel says
        what the disc's own files claim — which is where the answer is when a
        menu that should come up does not.
        """
        self.preview_mode = on
        self.preview_action.setChecked(on)
        self.preview.setVisible(on)
        self.titles.setVisible(not on)
        if not on:
            self.banner.hide()
            return

        folder = QFileDialog.getExistingDirectory(self, "Open a BDMV folder to preview")
        if not folder:
            self.set_preview_mode(False)
            return
        report = self.preview.show_folder(Path(folder))
        self.open_path(Path(folder), preview=True)
        if not report.healthy:
            self.report(report.problems[0])
        elif self.profile is not None and not self.profile.has_menu:
            self.report(strings.PREVIEW_NO_MENU, tone="notice")
        else:
            self.banner.show_message(
                f"{strings.PREVIEW_TITLE}. {strings.PREVIEW_BODY}", tone="notice"
            )

    # -- actions -----------------------------------------------------------

    @property
    def _is_dvd(self) -> bool:
        return self.profile is not None and self.profile.kind is DiscKind.DVD_VIDEO

    @property
    def in_menu(self) -> bool:
        """True when the arrow keys should move a highlight, not seek."""
        if self._dvd_menu is not None:
            return True
        if self.profile is not None and not self.profile.kind.is_video:
            # An audio CD has no menu to be in, and neither has a folder of
            # files. Asking the engine would get an answer about the wrong
            # kind of thing.
            return False
        titles = self.engine.titles()
        current = self.engine.current_title
        for title in titles:
            if title.number == current:
                return title.is_menu
        return False

    def do(self, action: PlayerAction) -> None:
        """Run one action, whatever asked for it.

        The menu keys are tested BEFORE the navigation branch, not after.
        ``TOP_MENU`` and ``POPUP_MENU`` are both members of the navigation
        set, so a check for them below ``is_navigation`` is a check that
        never runs. That is how the DVD menu shipped unreachable: the code
        was all there and nothing could call it.
        """
        if action in (PlayerAction.TOP_MENU, PlayerAction.POPUP_MENU) and self._is_dvd:
            if self._dvd_menu is not None:
                self.leave_dvd_menu()
            elif self.profile is not None and not self.profile.has_menu:
                # The button for this is already disabled; the key was not,
                # and it answered with the message for a disc whose menu is
                # damaged. Most discs with no menu are simply discs with no
                # menu.
                self.report(strings.DVD_HAS_NO_MENU, tone="notice")
            else:
                self.show_dvd_menu()
            return

        if action.is_navigation:
            nav = action.to_nav()
            if nav is None:
                return
            # A DVD menu is navigated by us; a Blu-ray menu by libbluray.
            if self._dvd_menu is not None:
                self._carry_out(self._dvd_menu.press(nav))
            else:
                self.engine.navigate(nav)
            return

        # Leaving a menu must not leave somebody in a chrome-less full screen
        # needing a second press to get the window back.
        if action is PlayerAction.LEAVE_FULLSCREEN and self._dvd_menu is not None:
            self.leave_dvd_menu()
            if self.isFullScreen():
                self.toggle_fullscreen()
            return

        if action is PlayerAction.PLAY_PAUSE:
            self.engine.toggle_pause()
        elif action is PlayerAction.STOP:
            # Stopping the menu's own video leaves the menu drawn over a dead
            # picture with the keycaps still offering to move a highlight.
            if self._dvd_menu is not None:
                self.leave_dvd_menu(resume=False)
            self.stop()
        elif action is PlayerAction.SKIP_BACK:
            self.engine.seek(max(0, self.engine.position_ms - SKIP_MS))
        elif action is PlayerAction.SKIP_FORWARD:
            self.engine.seek(self.engine.position_ms + SKIP_MS)
        elif action in (PlayerAction.NEXT_CHAPTER, PlayerAction.PREVIOUS_CHAPTER):
            step = 1 if action is PlayerAction.NEXT_CHAPTER else -1
            # On a CD the same button means the next track. It is the same
            # gesture and the same expectation; only the unit differs.
            if self.profile is not None and self.profile.kind is DiscKind.AUDIO_CD:
                self._step_track(step)
            else:
                self._step_chapter(step)
        elif action in (PlayerAction.VOLUME_UP, PlayerAction.VOLUME_DOWN):
            step = VOLUME_STEP if action is PlayerAction.VOLUME_UP else -VOLUME_STEP
            self._set_volume(self._volume + step)
        elif action is PlayerAction.TOGGLE_PANEL:
            self.toggle_panel()
        elif action is PlayerAction.FULLSCREEN:
            self.toggle_fullscreen()
        elif action is PlayerAction.LEAVE_FULLSCREEN and self.isFullScreen():
            self.toggle_fullscreen()
        elif action is PlayerAction.EJECT:
            self.eject()

    def _chapter_marks(self) -> list[int]:
        if (
            self.profile is not None
            and self.profile.kind is DiscKind.DVD_VIDEO
            and self._dvd_title is not None
        ):
            return [self._dvd_title.start_ms + mark for mark in self._dvd_title.chapters_ms]
        return self.engine.chapters()

    def _step_chapter(self, direction: int) -> None:
        marks = self._chapter_marks()
        if not marks:
            return
        position = self.engine.position_ms
        if direction > 0:
            following = [mark for mark in marks if mark > position + 1000]
            if following:
                self.engine.seek(following[0])
        else:
            # Like every disc player: back once returns to the start of this
            # chapter, back again goes to the one before.
            earlier = [mark for mark in marks if mark < position - 3000]
            self.engine.seek(earlier[-1] if earlier else 0)

    # -- input -------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        action = action_for(int(event.key()), in_menu=self.in_menu)
        if action is None:
            super().keyPressEvent(event)
            return
        self.do(action)
        event.accept()

    def _poll_gamepad(self) -> None:
        state = self._gamepad.read()
        if state is None:
            self._pad_reader.release_all()
            return
        for action in self._pad_reader.poll(state, self._elapsed_ms):
            resolved = action
            if not self.in_menu and action in (PlayerAction.LEFT, PlayerAction.RIGHT):
                resolved = (
                    PlayerAction.SKIP_BACK
                    if action is PlayerAction.LEFT
                    else PlayerAction.SKIP_FORWARD
                )
            self.do(resolved)

    # -- the engine talking back -------------------------------------------

    def _on_engine_event(self, event: EngineEvent) -> None:
        self.transport.set_state(event.state)
        if event.state is PlaybackState.ERROR:
            # A DVD that will not open is usually CSS, but not always: the
            # disc can have been taken out, or have a bad sector. Claiming
            # copy protection for those tells somebody their own disc is
            # something it is not, and throws them out of playback for it.
            if self._looks_like_css():
                self.explain(strings.PROTECTED_DVD_TITLE, strings.PROTECTED_DVD, offer_eject=True)
                self.show_welcome()
                return
            self.report(event.message or strings.CANNOT_READ_DISC)
        elif event.state is PlaybackState.ENDED:
            self._on_title_ended()
        elif event.state is PlaybackState.PLAYING:
            self._playing_started = True
            if self._pending_seek_ms:
                self.engine.seek(self._pending_seek_ms)
                self._pending_seek_ms = 0
            self.banner.hide()
            self.transport.set_tracks(
                self.engine.audio_tracks(), self.engine.subtitle_tracks()
            )
            self._refresh_titles()
            self._publish_chapters()
            self.transport.set_mode(Mode.MENU if self.in_menu else Mode.PLAYBACK)
            self.titles.set_playing(
                self.engine.current_title if self._chosen_title is None else self._chosen_title
            )

    def _looks_like_css(self) -> bool:
        """Is this DVD failing because it is scrambled, or for a duller reason?

        Encryption is the answer when the disc is still in the drive, is
        still a DVD, and nothing has ever played from it. A disc that was
        playing a moment ago is not one, and telling somebody their own
        disc is copy-protected is both wrong and rude.

        Asked as "has anything played", not "where is the film now":
        pressing Stop sets the position back to zero, so the second
        question calls an hour of successful playback a scrambled disc.
        """
        if self.profile is None or self.profile.kind is not DiscKind.DVD_VIDEO:
            return False
        try:
            if not self.profile.root.exists():
                return False
        except OSError:
            return False
        return not self._playing_started

    def _on_title_ended(self) -> None:
        """Something ran out. Say so, and leave somewhere to go next.

        A blank picture and a dead Play button is what this looked like
        before: no message, nothing on screen changed, and the only way on
        was to pick another title or take the disc out and put it back.

        On an audio CD it goes on to the next track, because that is what a
        CD player does and there is no reason for this one to be the
        exception.
        """
        if self.profile is None:
            return
        if self.profile.kind is DiscKind.AUDIO_CD and self._play_next_track():
            return
        self.transport.set_state(PlaybackState.STOPPED)
        if self.profile.has_menu and self._is_dvd:
            self.report(strings.TITLE_ENDED_MENU, tone="notice")
            self.show_dvd_menu()
            return
        self.report(strings.TITLE_ENDED, tone="notice")
        if self.profile.titles:
            self.top_bar.set_panel_available(True)
            self.panel.setVisible(True)
            self._panel_wanted = True

    def _refresh_titles(self) -> None:
        """Swap the file-read title list for the engine's, once it has one.

        The two number their titles differently — a disc's playlists are not a
        player's titles — and ``select_title`` speaks the engine's. Showing
        one list and acting on the other plays the wrong thing.
        """
        titles = self.engine.titles()
        if not titles or self.profile is None:
            return
        if self.profile.kind is DiscKind.DVD_VIDEO:
            # A DVD's titles come from its IFOs, not from the engine, which
            # sees one concatenated stream and would report a single title.
            return
        feature = getattr(self.engine, "main_feature_title", None)
        self.titles.show_engine_titles(titles, feature() if callable(feature) else None)
        self.transport.set_menu_available(any(title.is_menu for title in titles))

    def _on_tick(self) -> None:
        self._elapsed_ms += TICK_MS
        if not self.engine.state.is_active:
            return
        duration = self.engine.duration_ms
        self.transport.set_position(self.engine.position_ms, duration)
        # A disc does not always know its own length or its own chapters the
        # instant it starts. When either answer changes, the marks are redrawn.
        if duration != self._known_duration_ms:
            self._known_duration_ms = duration
            self._publish_chapters()

    # -- talking to a person -----------------------------------------------

    def explain(self, headline: str, body: str, *, offer_eject: bool = False) -> None:
        """Say the whole reason, in a window someone can read and close.

        The banner is one line and this is not a one-line thing. Anything that
        amounts to "we would play this for you if we were allowed to" gets the
        paragraphs it needs. ``offer_eject`` adds the one thing a person can
        do about a disc that will not play: take it out.
        """
        box = QMessageBox(self)
        box.setWindowTitle(headline)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setText(f"<b>{headline}</b>")
        box.setInformativeText(body)
        ok = box.addButton(QMessageBox.StandardButton.Ok)
        eject = box.addButton(strings.EJECT, QMessageBox.ButtonRole.ActionRole) if offer_eject else None
        box.setDefaultButton(ok)
        self.report(headline + ".", tone="notice")
        self._last_explain = box
        box.exec()
        if eject is not None and box.clickedButton() is eject:
            self.eject()

    def report(self, message: str, *, tone: str = "problem") -> None:
        """The one way anything in the Player tells someone what happened."""
        self.banner.show_message(message, tone=tone)

    def show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(strings.ABOUT_TITLE)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(strings.about_text())
        box.exec()

    # -- a new Player, only when asked --------------------------------------

    def check_for_updates(self, checked: bool = False, *, check=None) -> None:
        """Help > Check for a new Player. Off-thread; one sentence back.

        ``check`` is a seam for tests: a callable returning an ``Outcome``
        in place of the real request.
        """
        from ..update.ui import UpdateCheck

        if self._update_check is None:
            self._update_check = UpdateCheck(self)
        if self._update_check.busy:
            return
        self.report(strings.UPDATE_CHECKING, tone="notice")
        self._update_check.start(self._on_update_checked, check=check)

    def _on_update_checked(self, outcome) -> None:
        if self._closing:
            return
        if outcome.release is None:
            self.report(outcome.sentence, tone="notice")
            return
        self.report(outcome.sentence, tone="notice")
        self._offer_update(outcome.release)

    def _offer_update(self, release) -> None:
        from ..version import VERSION

        box = QMessageBox(self)
        box.setWindowTitle(strings.UPDATE_MENU.rstrip("…"))
        box.setText(strings.update_offer(release.version, VERSION))
        get = box.addButton(strings.UPDATE_GET, QMessageBox.ButtonRole.AcceptRole)
        notes = box.addButton(strings.UPDATE_NOTES, QMessageBox.ButtonRole.HelpRole) if release.notes_url else None
        box.addButton(strings.UPDATE_NOT_NOW, QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(get)

        def clicked(button) -> None:
            if button is notes and release.notes_url:
                QDesktopServices.openUrl(QUrl(release.notes_url))
                return
            if button is get:
                self._install_update(release)

        box.buttonClicked.connect(clicked)
        self._update_box = box
        box.open()

    def _install_update(self, release) -> None:
        if self._update_check is None:
            return
        self.report(strings.UPDATE_DOWNLOADING, tone="notice")

        def installed(sentence: str) -> None:
            if self._closing:
                return
            self.report(sentence, tone="notice")
            if sentence == strings.UPDATE_INSTALLING:
                self.close()

        self._update_check.install(release, installed)

    def closeEvent(self, event) -> None:
        # Every timer, before the engine goes. The gamepad one was being
        # missed, and a poll that runs after release() calls into a media
        # player that is no longer there.
        for name in ("_drive_timer", "_tick", "_chrome_timer", "_pad_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        # And the disc being read, which is not a timer. A read that lands
        # after release() runs _on_disc_read against a freed engine and calls
        # open() on it — an access violation, reproducibly, three runs in
        # three. The excepthook catches it often enough to look survivable,
        # which is worse than crashing.
        self.reader.cancel()
        self._closing = True
        if self._update_check is not None:
            self._update_check.cancel()
        # The shape of the window and the volume, for next time. Written
        # here and nowhere else, so a crash mid-run keeps the last good pair.
        try:
            if not self.isFullScreen():
                self.prefs.set_geometry(bytes(self.saveGeometry()))
            self.prefs.set_volume(self._volume)
            self.prefs.sync()
        except Exception:
            pass
        if self._dvd_menu is not None:
            self._dvd_menu.stop()
            self._dvd_menu = None
        self.engine.release()
        super().closeEvent(event)
