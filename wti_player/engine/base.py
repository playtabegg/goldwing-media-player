"""What the Player asks a playback engine to do, and how it names media.

The engine behind this is libvlc, but nothing above it says so. That keeps
two doors open: the UI is testable against :class:`~wti_player.engine.fake.
FakeEngine`, and if libvlc ever stops being the right answer, one file
changes instead of the app.

:class:`MediaTarget` is the other half. Deciding what MRL a disc gets is the
piece of engine knowledge most likely to be wrong — a Blu-ray folder handed
over as a plain ``file://`` URI does not play at all — so it lives here as
pure, tested logic rather than inside the engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class PlaybackState(Enum):
    IDLE = "idle"
    OPENING = "opening"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ENDED = "ended"
    ERROR = "error"

    @property
    def is_active(self) -> bool:
        return self in (PlaybackState.OPENING, PlaybackState.PLAYING, PlaybackState.PAUSED)


class NavAction(Enum):
    """One set of menu actions, whatever pressed them."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    ACTIVATE = "activate"
    TOP_MENU = "top-menu"
    POPUP_MENU = "popup-menu"


class MediaKind(Enum):
    BLU_RAY = "blu-ray"
    DVD_VIDEO = "dvd-video"
    AUDIO_CD = "audio-cd"
    FILE = "file"


@dataclass(frozen=True)
class MediaTarget:
    """A thing to play, and the MRL that actually opens it."""

    kind: MediaKind
    mrl: str
    #: Where it came from, for anything that wants to show a path.
    source: Path | None = None
    #: Options the engine must set on this media, e.g. the list of files a
    #: DVD title's video is spread across.
    options: tuple[str, ...] = ()

    @staticmethod
    def _file_uri(path: Path) -> str:
        return path.resolve().as_uri()

    @classmethod
    def blu_ray(cls, path: Path) -> MediaTarget:
        """A BDMV folder, a disc root, a drive, or an ISO.

        The ``bluray://`` scheme is not optional for a *folder*: with a plain
        ``file://`` URI, VLC looks at the directory, finds nothing it wants,
        and ends immediately. Images work either way; they get the same
        treatment so there is one code path.
        """
        uri = cls._file_uri(path)
        return cls(
            kind=MediaKind.BLU_RAY,
            mrl="bluray://" + uri[len("file://") :],
            source=path,
        )

    @classmethod
    def dvd(cls, path: Path) -> MediaTarget:
        """A VIDEO_TS folder, a disc root, a drive, or a DVD image.

        Used when the image itself is the disc (a ``.iso`` we have already
        peeked) and we do not have loose VOB files to concatenate. The
        ``dvd://`` scheme is what libvlc wants for that.
        """
        uri = cls._file_uri(path)
        return cls(
            kind=MediaKind.DVD_VIDEO,
            mrl="dvd://" + uri[len("file://") :],
            source=path,
        )

    @classmethod
    def dvd_title(cls, vobs: list[Path]) -> MediaTarget:
        """One DVD title, as the VOB files its video actually lives in.

        A DVD's video is one program stream split at file boundaries, so the
        files are handed over as a single concatenated stream. That is why the
        Player needs no DVD engine, and carries no descrambler: the structure
        comes from our own reader, and this is just video.
        """
        if not vobs:
            raise ValueError("a DVD title needs at least one VOB file")
        urls = ",".join(cls._file_uri(path) for path in vobs)
        return cls(
            kind=MediaKind.DVD_VIDEO,
            mrl="concat://",
            source=vobs[0].parent,
            options=(f":concat-list={urls}",),
        )

    @classmethod
    def audio_cd(cls, mount: str, track: int | None = None) -> MediaTarget:
        letter = mount[0] if mount[1:2] == ":" else mount
        mrl = f"cdda:///{letter}:/" if mount[1:2] == ":" else f"cdda://{mount}"
        # libvlc's CDDA plugin does not honour ``cdda:///E:/#N``. Track
        # selection is the 1-based ``:cdda-track=`` option. ``track`` here
        # is 0-based because that is how the UI numbers the list.
        options: tuple[str, ...] = ()
        if track is not None:
            options = (f":cdda-track={track + 1}",)
        return cls(kind=MediaKind.AUDIO_CD, mrl=mrl, source=Path(mount), options=options)

    @classmethod
    def file(cls, path: Path) -> MediaTarget:
        return cls(kind=MediaKind.FILE, mrl=cls._file_uri(path), source=path)


@dataclass(frozen=True)
class EngineTitle:
    """A title as the engine sees it — its own numbering, not the disc's."""

    number: int
    name: str
    duration_ms: int
    is_menu: bool = False
    is_interactive: bool = False
    chapters: int = 0


@dataclass(frozen=True)
class Track:
    """One audio or subtitle track the engine can switch to."""

    identifier: int
    name: str


@dataclass(frozen=True)
class CdTrack:
    """One track of an audio CD, as its table of contents describes it."""

    number: int
    title: str
    artist: str = ""
    duration_ms: int = 0


@dataclass(frozen=True)
class AudioCdInfo:
    """What an audio CD says about itself.

    A Red Book disc has no filesystem, so this is everything there is: a
    table of contents, which is always real, and CD-TEXT, which is often
    absent. There is nowhere on such a disc to keep a picture, so the Player
    draws one.
    """

    album: str = ""
    artist: str = ""
    tracks: tuple[CdTrack, ...] = ()

    @property
    def has_cd_text(self) -> bool:
        """Did the disc name anything, or are these numbered tracks?"""
        return bool(self.album) or any(
            track.title and not track.title.startswith("Track ") for track in self.tracks
        )

    def names(self) -> list[str]:
        return [track.title for track in self.tracks]


@dataclass(frozen=True)
class EngineEvent:
    """Something happened. The UI listens; nothing else does."""

    state: PlaybackState
    #: Set when ``state`` is ERROR: text fit to show a person.
    message: str = ""


EngineListener = Callable[[EngineEvent], None]


class PlaybackEngine(Protocol):
    """The whole surface the Player uses. Deliberately small."""

    def open(self, target: MediaTarget) -> None: ...

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def toggle_pause(self) -> None: ...

    def stop(self) -> None: ...

    def release(self) -> None: ...

    @property
    def state(self) -> PlaybackState: ...

    @property
    def position_ms(self) -> int: ...

    @property
    def duration_ms(self) -> int: ...

    def seek(self, position_ms: int) -> None: ...

    def titles(self) -> list[EngineTitle]: ...

    @property
    def current_title(self) -> int: ...

    def select_title(self, number: int) -> None: ...

    def chapters(self, title: int | None = None) -> list[int]: ...

    def select_chapter(self, number: int) -> None: ...

    def navigate(self, action: NavAction) -> None: ...

    def audio_tracks(self) -> list[Track]: ...

    def select_audio_track(self, identifier: int) -> None: ...

    def subtitle_tracks(self) -> list[Track]: ...

    def select_subtitle_track(self, identifier: int) -> None: ...

    def set_volume(self, percent: int) -> None: ...

    def set_video_window(self, handle: int) -> None: ...

    def add_listener(self, listener: EngineListener) -> None: ...
