"""An engine that plays nothing, so the rest of the Player can be tested.

Time does not pass on its own here; a test moves it with :meth:`advance`.
Menus work the way a real disc's do — buttons in a ring, activation follows a
link — which is enough to drive the UI's whole navigation path without a disc,
a drive, or a video card.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .base import (
    AudioCdInfo,
    EngineEvent,
    EngineListener,
    EngineTitle,
    MediaTarget,
    NavAction,
    PlaybackState,
    Track,
)


@dataclass
class FakeButton:
    label: str
    #: The title this button jumps to when activated.
    target_title: int


@dataclass
class FakeDisc:
    """What the fake engine will find when it opens something."""

    titles: list[EngineTitle] = field(default_factory=list)
    chapters: dict[int, list[int]] = field(default_factory=dict)
    buttons: list[FakeButton] = field(default_factory=list)
    audio: list[Track] = field(default_factory=list)
    subtitles: list[Track] = field(default_factory=list)
    #: What ``audio_cd_info`` will report. Absent on most discs, because
    #: CD-TEXT is absent on most discs.
    cd: AudioCdInfo | None = None
    #: Set to make ``open`` fail the way an unreadable disc does.
    open_error: str = ""


def simple_disc(duration_ms: int = 90 * 60 * 1000) -> FakeDisc:
    """A one-feature disc with a menu, which is most discs."""
    return FakeDisc(
        titles=[
            EngineTitle(0, "Top Menu", 0, is_menu=True, is_interactive=True),
            EngineTitle(1, "Feature", duration_ms, chapters=3),
        ],
        chapters={1: [0, duration_ms // 3, 2 * duration_ms // 3]},
        buttons=[FakeButton("Play", 1), FakeButton("Chapters", 1)],
        audio=[Track(0, "English AC-3 5.1")],
        subtitles=[Track(-1, "Off"), Track(1, "English")],
    )


class FakeEngine:
    """Implements :class:`~wti_player.engine.base.PlaybackEngine`."""

    def __init__(self, disc: FakeDisc | None = None) -> None:
        self.disc = disc or FakeDisc()
        self.opened: list[MediaTarget] = []
        self._target: MediaTarget | None = None
        self._finished = False
        self.window_handle: int | None = None
        self.volume = 100
        self.selected_audio: int | None = None
        self.selected_subtitle: int | None = None
        self.navigations: list[NavAction] = []
        self.selected_button = 0
        self.released = False

        self._state = PlaybackState.IDLE
        self._position = 0
        self._title = 0
        self._chapter = 0
        self._listeners: list[EngineListener] = []
        self.memory_output: tuple[int, int] | None = None
        self.on_frame = None
        self._frame_buffer = bytearray()
        self._frame_lock = threading.Lock()

    # -- the engine surface ------------------------------------------------

    def open(self, target: MediaTarget) -> None:
        self.opened.append(target)
        self._target = target
        if self.disc.open_error:
            self._set_state(PlaybackState.ERROR, self.disc.open_error)
            return
        self._position = 0
        self._title = 0
        self._chapter = 0
        self._finished = False
        self.selected_button = 0
        self._set_state(PlaybackState.OPENING)
        self._set_state(PlaybackState.PLAYING)

    def play(self) -> None:
        # Once a title has run out, libvlc has released the media and nothing
        # short of opening it again starts anything. Modelled here because a
        # fake that quietly resumes is a fake that hides the dead Play button.
        if self._finished and self._target is not None:
            self.open(self._target)
            return
        if self._state in (PlaybackState.PAUSED, PlaybackState.STOPPED):
            self._set_state(PlaybackState.PLAYING)

    def pause(self) -> None:
        if self._state == PlaybackState.PLAYING:
            self._set_state(PlaybackState.PAUSED)

    def toggle_pause(self) -> None:
        self.pause() if self._state == PlaybackState.PLAYING else self.play()

    def finish(self) -> None:
        """Run the current title out, the way a disc does at the end."""
        self._position = self.duration_ms
        self._finished = True
        self._set_state(PlaybackState.ENDED)
        self._set_state(PlaybackState.STOPPED)

    def stop(self) -> None:
        self._position = 0
        self._set_state(PlaybackState.STOPPED)

    def release(self) -> None:
        self.released = True
        self._set_state(PlaybackState.IDLE)

    @property
    def state(self) -> PlaybackState:
        return self._state

    @property
    def position_ms(self) -> int:
        return self._position

    @property
    def duration_ms(self) -> int:
        title = self._title_at(self._title)
        return title.duration_ms if title else 0

    def seek(self, position_ms: int) -> None:
        self._position = max(0, min(position_ms, self.duration_ms))

    def titles(self) -> list[EngineTitle]:
        return list(self.disc.titles)

    @property
    def current_title(self) -> int:
        return self._title

    def select_title(self, number: int) -> None:
        if self._title_at(number) is None:
            return
        self._title = number
        self._position = 0
        self._chapter = 0
        self._set_state(PlaybackState.PLAYING)

    def chapters(self, title: int | None = None) -> list[int]:
        return list(self.disc.chapters.get(self._title if title is None else title, []))

    def select_chapter(self, number: int) -> None:
        marks = self.chapters()
        if 0 <= number < len(marks):
            self._chapter = number
            self._position = marks[number]

    def navigate(self, action: NavAction) -> None:
        self.navigations.append(action)
        if not self.disc.buttons:
            return
        if action in (NavAction.TOP_MENU, NavAction.POPUP_MENU):
            self.select_title(0)
            return
        if action in (NavAction.DOWN, NavAction.RIGHT):
            self.selected_button = (self.selected_button + 1) % len(self.disc.buttons)
        elif action in (NavAction.UP, NavAction.LEFT):
            self.selected_button = (self.selected_button - 1) % len(self.disc.buttons)
        elif action == NavAction.ACTIVATE:
            self.select_title(self.disc.buttons[self.selected_button].target_title)

    def use_memory_output(self, width: int, height: int, on_frame):
        """A buffer the size the real engine would hand back.

        Present because a fake that is missing a method is a path the tests
        cannot reach, and the DVD menu is exactly the path that went out
        unreachable for want of one.
        """
        self.memory_output = (width, height)
        self.on_frame = on_frame
        self._frame_buffer = bytearray(width * height * 4)
        return memoryview(self._frame_buffer)

    def frame_lock(self):
        return self._frame_lock

    def audio_cd_info(self, _target: MediaTarget, _timeout_ms: int = 0) -> AudioCdInfo:
        return self.disc.cd or AudioCdInfo()

    def audio_cd_tracks(self, target: MediaTarget, timeout_ms: int = 0) -> list[str]:
        return self.audio_cd_info(target, timeout_ms).names()

    def audio_tracks(self) -> list[Track]:
        return list(self.disc.audio)

    def select_audio_track(self, identifier: int) -> None:
        self.selected_audio = identifier

    def subtitle_tracks(self) -> list[Track]:
        return list(self.disc.subtitles)

    def select_subtitle_track(self, identifier: int) -> None:
        self.selected_subtitle = identifier

    def set_volume(self, percent: int) -> None:
        self.volume = max(0, min(100, percent))

    def set_video_window(self, handle: int) -> None:
        self.window_handle = handle

    def add_listener(self, listener: EngineListener) -> None:
        self._listeners.append(listener)

    # -- what tests drive --------------------------------------------------

    def advance(self, milliseconds: int) -> None:
        """Move time forward, ending the title if it runs out."""
        if self._state != PlaybackState.PLAYING:
            return
        self._position += milliseconds
        if self.duration_ms and self._position >= self.duration_ms:
            self._position = self.duration_ms
            self._set_state(PlaybackState.ENDED)

    def fail(self, message: str) -> None:
        self._set_state(PlaybackState.ERROR, message)

    def _title_at(self, number: int) -> EngineTitle | None:
        for title in self.disc.titles:
            if title.number == number:
                return title
        return None

    def _set_state(self, state: PlaybackState, message: str = "") -> None:
        self._state = state
        event = EngineEvent(state=state, message=message)
        for listener in list(self._listeners):
            listener(event)
