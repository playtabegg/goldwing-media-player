"""The libvlc-backed engine.

This is the only file in the Player that knows libvlc exists. Everything the
spike learned lives here as behaviour rather than as a comment somewhere:

* discs are opened with menus on, always — with them off, an image reports no
  titles at all and "Play main feature" has nothing to work with;
* diagnostics go through VLC's own file logging, never a Python log callback,
  because the ``va_list`` it hands the callback cannot be read through
  ``ctypes`` on Windows and trying takes the process down;
* hardware decoding is on by default and can be turned off, because a menu
  overlay cannot always be blended onto a hardware surface.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from .base import (
    AudioCdInfo,
    CdTrack,
    EngineEvent,
    EngineListener,
    EngineTitle,
    MediaKind,
    MediaTarget,
    NavAction,
    PlaybackState,
    Track,
)
from .libvlc_loader import RuntimeRefused, has_plugin, load_vlc

#: How many sets of memory-output callbacks to hold on to. The one in
#: use, and the one a vout may still be finishing with. Any more is a
#: leak: each set owns a full frame buffer, 1.4 MB at menu size.
KEPT_FRAME_CALLBACKS = 2

#: Bits ``libvlc_title_description_t.flags`` uses.
_TITLE_MENU = 0x01
_TITLE_INTERACTIVE = 0x02


class EngineError(RuntimeError):
    """The engine could not start. The message is fit to show a person."""


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value is None else str(value)


_NAVIGATE = {
    NavAction.UP: "up",
    NavAction.DOWN: "down",
    NavAction.LEFT: "left",
    NavAction.RIGHT: "right",
    NavAction.ACTIVATE: "activate",
    NavAction.POPUP_MENU: "popup",
}


class VlcEngine:
    """Implements :class:`~wti_player.engine.base.PlaybackEngine`."""

    def __init__(
        self,
        *,
        hardware_decoding: bool = True,
        log_file: Path | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        self._vlc: ModuleType = load_vlc()
        self._hardware_decoding = hardware_decoding
        self._listeners: list[EngineListener] = []
        self._state = PlaybackState.IDLE
        self._target: MediaTarget | None = None
        #: True once a title has run out. libvlc releases the media when
        #: that happens, so Play has to open it again rather than resume.
        self._finished = False
        self._titles_cache: list[EngineTitle] | None = None
        self._chapters_cache: dict[int, list[int]] = {}
        # Held by libvlc's lock/unlock pair around the memory-output buffer,
        # and by anything reading that buffer from another thread.
        self._frame_lock = threading.Lock()
        # Every set of trampolines ever handed to libvlc. Kept, not replaced:
        # a vout can still be holding an older set when a new one is made.
        self._frame_callbacks: list[tuple] = []

        args = [
            "--intf", "dummy",
            "--no-video-title-show",
            "--no-osd",
            "--no-snapshot-preview",
            "--no-stats",
            # Update checking is compiled out of the runtime we ship, so
            # there is no switch for it and nothing to switch off. The
            # Player's own check runs only from the Help menu, by hand
            # (wti_player/update), never from here and never on its own.
        ]
        if not hardware_decoding:
            args.append("--avcodec-hw=none")
        if log_file is not None:
            # Verbosity here; the destination is set after the instance
            # exists, by _log_to_file below. libvlc 3.x cannot be told to
            # write to a file from its arguments at all: --file-logging is
            # the VLC 2.x spelling and 3.x rejects it outright, which made
            # Instance() return None — so --log, the one way to get a
            # diagnostic out of a customer, was the single switch that
            # guaranteed the Player would not start.
            args.append("--verbose=2")
        else:
            args.append("--quiet")
        args += extra_args or []

        instance = self._vlc.Instance(args)
        if instance is None:
            # libvlc says nothing about why. The one thing worth naming is
            # the switch a person is most likely to have just added.
            hint = (
                " Try again without --log."
                if log_file is not None
                else " Reinstalling GoldWing usually fixes this."
            )
            raise EngineError("GoldWing's video engine would not start." + hint)
        self._instance = instance
        self._log_handle: int | None = None
        if log_file is not None:
            self._log_to_file(log_file)
        self._player = instance.media_player_new()
        self._attach_events()

    def _log_to_file(self, path: Path) -> None:
        """Point libvlc's own diagnostics at ``path``.

        ``libvlc_log_set_file`` takes a C ``FILE*``, and which C runtime it
        came from matters: VideoLAN builds libvlc with mingw against
        ``msvcrt.dll``, while this Python uses the universal CRT. A UCRT
        ``FILE*`` handed across that boundary is a different struct being
        read as if it were the same one. So the handle is opened from
        msvcrt, which is the runtime that will be reading it.

        The other route, ``libvlc_log_set`` with a callback, is not an
        option: the ``va_list`` it hands the callback cannot be read through
        ctypes on Windows and trying takes the process down. That was the
        day-one spike's finding and it has not changed.

        Failing to open a log is never worth failing to start over.
        """
        if sys.platform != "win32":
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            crt = ctypes.CDLL("msvcrt")
            crt.fopen.restype = ctypes.c_void_p
            crt.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            handle = crt.fopen(str(path).encode("mbcs", "replace"), b"a")
            if not handle:
                return

            set_file = self._vlc.dll.libvlc_log_set_file
            set_file.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            set_file.restype = None
            set_file(self._instance_pointer(), ctypes.c_void_p(handle))
            self._log_handle = handle
        except Exception:
            # A diagnostic switch is not worth a failed launch.
            self._log_handle = None

    def _instance_pointer(self) -> ctypes.c_void_p:
        raw = getattr(self._instance, "_as_parameter_", self._instance)
        return ctypes.c_void_p(int(getattr(raw, "value", raw)))

    def _close_log(self) -> None:
        if self._log_handle is None:
            return
        try:
            crt = ctypes.CDLL("msvcrt")
            crt.fclose.argtypes = [ctypes.c_void_p]
            crt.fclose(ctypes.c_void_p(self._log_handle))
        except Exception:
            pass
        self._log_handle = None

    # -- lifecycle ---------------------------------------------------------

    def _attach_events(self) -> None:
        vlc = self._vlc
        manager = self._player.event_manager()
        mapping = {
            vlc.EventType.MediaPlayerOpening: PlaybackState.OPENING,
            vlc.EventType.MediaPlayerPlaying: PlaybackState.PLAYING,
            vlc.EventType.MediaPlayerPaused: PlaybackState.PAUSED,
            vlc.EventType.MediaPlayerStopped: PlaybackState.STOPPED,
            vlc.EventType.MediaPlayerEndReached: PlaybackState.ENDED,
        }
        for event_type, state in mapping.items():
            manager.event_attach(event_type, self._on_state, state)
        manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_error)

    def _on_state(self, _event: object, state: PlaybackState) -> None:
        if state is PlaybackState.PLAYING and self._state is not PlaybackState.PLAYING:
            # A disc has no titles to report until it is actually playing.
            self._titles_cache = None
            self._chapters_cache.clear()
            self._finished = False
        elif state is PlaybackState.ENDED:
            # Remembered past the STOPPED that follows it, because that is
            # the state anyone asking later will see, and it is not the same
            # thing as a stop somebody asked for.
            self._finished = True
        self._state = state
        self._emit(EngineEvent(state=state))

    def _on_error(self, _event: object) -> None:
        self._state = PlaybackState.ERROR
        self._emit(
            EngineEvent(
                state=PlaybackState.ERROR,
                message=self._explain_failure(),
            )
        )

    def _explain_failure(self) -> str:
        """What went wrong, said the way a person would say it.

        The Blu-ray sentence is only for a Blu-ray we actually tried to
        open. Saying it about a game ISO or a DVD was the 30 Aug 2026 bug:
        every image was handed to libbluray, then this line ran.
        """
        from .. import strings

        target = self._target
        if target is None:
            return "GoldWing could not open that."
        source = target.source
        if source is not None and not source.exists():
            return "That disc or file is no longer there."
        if target.kind is MediaKind.BLU_RAY:
            return strings.CANNOT_READ_BLU_RAY
        return strings.CANNOT_READ_DISC

    def _emit(self, event: EngineEvent) -> None:
        for listener in list(self._listeners):
            listener(event)

    def add_listener(self, listener: EngineListener) -> None:
        self._listeners.append(listener)

    def release(self) -> None:
        try:
            self._player.stop()
            self._player.release()
            self._instance.release()
        except Exception:  # a teardown must not be the thing that fails
            pass
        # After the instance, never before: libvlc writes to this handle
        # until it is torn down.
        self._close_log()
        # And after the player is gone, nothing can call these, so the
        # buffers they hold can go too. release() used to leave every frame
        # buffer the process had ever made still resident.
        self._frame_callbacks.clear()
        self._state = PlaybackState.IDLE

    # -- playback ----------------------------------------------------------

    def open(self, target: MediaTarget) -> None:
        self._target = target
        self._finished = False
        self._titles_cache = None
        self._chapters_cache.clear()
        media = self._instance.media_new(target.mrl)
        # Menus on, always. See the module docstring.
        media.add_option(":bluray-menu")
        media.add_option(":dvdnav-menu")
        if not self._hardware_decoding:
            media.add_option(":avcodec-hw=none")
        for option in target.options:
            media.add_option(option)
        self._player.set_media(media)
        self._state = PlaybackState.OPENING
        self._emit(EngineEvent(state=PlaybackState.OPENING))
        if self._player.play() == -1:
            self._state = PlaybackState.ERROR
            self._emit(EngineEvent(state=PlaybackState.ERROR, message=self._explain_failure()))

    def play(self) -> None:
        if self._finished and self._target is not None:
            self.open(self._target)
            return
        self._player.play()

    def pause(self) -> None:
        if self._player.is_playing():
            self._player.pause()

    def toggle_pause(self) -> None:
        """Pause, resume, or start again — whichever the button means now.

        ``libvlc_media_player_pause`` does nothing whatsoever to a player
        that is not playing, so a Play button wired straight to it is dead
        from the moment somebody presses Stop. And once a title has run out,
        libvlc has let go of the media: nothing short of opening it again
        starts anything, whatever state it reports afterwards.
        """
        if self._state in (
            PlaybackState.OPENING,
            PlaybackState.PLAYING,
            PlaybackState.PAUSED,
        ):
            self._player.pause()
            return
        self.play()

    def stop(self) -> None:
        self._player.stop()

    @property
    def state(self) -> PlaybackState:
        return self._state

    @property
    def position_ms(self) -> int:
        return max(0, self._player.get_time())

    @property
    def duration_ms(self) -> int:
        return max(0, self._player.get_length())

    def seek(self, position_ms: int) -> None:
        if self._player.is_seekable():
            self._player.set_time(max(0, position_ms))

    def set_volume(self, percent: int) -> None:
        self._player.audio_set_volume(max(0, min(100, percent)))

    def use_memory_output(
        self, width: int, height: int, on_frame: Callable[[], None]
    ) -> memoryview:
        """Render into a buffer we own, instead of into a window.

        This is how a DVD menu gets drawn: the subpicture and the highlight
        have to be composited over the picture, and nothing can be composited
        over video the graphics card is painting straight to a window.

        It costs a copy per frame, so it is not how ordinary playback runs —
        a Blu-ray keeps its native window. Returns the buffer the caller
        should paint from; ``on_frame`` is called from libvlc's own thread
        each time a new one lands, so it must do nothing but wake the
        interface up.
        """
        size = width * height * 4
        buffer = (ctypes.c_ubyte * size)()
        guard = self._frame_lock

        @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        def lock(_opaque, planes):
            # libvlc's lock/unlock pair exists so that the decoder and
            # whoever is reading the buffer are never in it at once. Without
            # taking anything here, a widget painting from the buffer sees a
            # frame half-overwritten by the next one.
            guard.acquire()
            planes[0] = ctypes.cast(buffer, ctypes.c_void_p)
            return None

        @ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
        )
        def unlock(_opaque, _picture, _planes):
            guard.release()
            return None

        @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        def display(_opaque, _picture):
            try:
                on_frame()
            except Exception:
                pass  # a frame callback must never take playback down
            return None

        self._vlc.libvlc_video_set_callbacks(self._player, lock, unlock, display, None)
        self._vlc.libvlc_video_set_format(self._player, b"RV32", width, height, width * 4)
        # ctypes trampolines are collected the moment nothing holds them, and
        # libvlc would then call into freed memory. They are APPENDED rather
        # than replaced: a second menu can be started before the vout from
        # the first has finished with the callbacks it was given, and
        # dropping the old tuple then frees executable memory libvlc is
        # about to call.
        #
        # Appended and never retired was the other half of the bug: every menu
        # opened kept its 1.4 MB buffer for the life of the process, and two
        # hundred menus held 276 MB that release() did not free either. Two
        # sets are kept — the one in use and the one a vout may still be
        # letting go of — and older ones are dropped.
        self._frame_callbacks.append((lock, unlock, display, buffer))
        del self._frame_callbacks[:-KEPT_FRAME_CALLBACKS]
        return memoryview(buffer)

    def frame_lock(self):
        """Hold this while reading the memory-output buffer.

        The decoder writes under it. Anything painting from the buffer takes
        it too, or it is reading a frame that is halfway to being the next
        one.
        """
        return self._frame_lock

    def set_video_window(self, handle: int) -> None:
        if sys.platform == "win32":
            self._player.set_hwnd(handle)
        elif sys.platform == "darwin":
            self._player.set_nsobject(handle)
        else:
            self._player.set_xwindow(handle)

    # -- structure ---------------------------------------------------------

    def titles(self) -> list[EngineTitle]:
        """The disc's titles, read once per disc and kept.

        Two reasons this is not a straight call through to libvlc. It is asked
        on every key press — deciding whether the arrow keys move a highlight
        or seek — and libvlc allocates a fresh array each time, which
        ``python-vlc``'s own helper never frees. So the array is released here
        by hand, and the answer is cached until the disc or the state changes.
        """
        if self._titles_cache is not None:
            return list(self._titles_cache)

        vlc = self._vlc
        pointer = ctypes.POINTER(vlc.TitleDescription)()
        count = vlc.libvlc_media_player_get_full_title_descriptions(
            self._player, ctypes.byref(pointer)
        )
        if count <= 0:
            return []
        try:
            array = ctypes.cast(
                pointer, ctypes.POINTER(ctypes.POINTER(vlc.TitleDescription) * count)
            ).contents
            out: list[EngineTitle] = []
            for number in range(count):
                entry = array[number].contents
                flags = int(entry.flags)
                out.append(
                    EngineTitle(
                        number=number,
                        name=_text(entry.name) or f"Title {number + 1}",
                        duration_ms=int(entry.duration),
                        is_menu=bool(flags & _TITLE_MENU),
                        is_interactive=bool(flags & _TITLE_INTERACTIVE),
                        chapters=max(
                            0,
                            vlc.libvlc_media_player_get_chapter_count_for_title(
                                self._player, number
                            ),
                        ),
                    )
                )
        finally:
            self._release_array("libvlc_title_descriptions_release", pointer, count)

        self._titles_cache = out
        return list(out)

    def _release_array(self, function: str, pointer: object, count: int) -> None:
        """Hand a description array back to libvlc.

        Called against the library directly rather than through python-vlc's
        wrapper: that wrapper declares the argument one pointer level short of
        what libvlc actually writes, and calling it that way is an access
        violation rather than a free.
        """
        try:
            release = getattr(self._vlc.dll, function)
            release.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            release.restype = None
            release(ctypes.cast(pointer, ctypes.c_void_p), count)
        except (AttributeError, OSError):
            # A leak is bad; taking the Player down to avoid one is worse.
            pass

    def _forget_titles(self) -> None:
        self._titles_cache = None

    @property
    def current_title(self) -> int:
        return self._player.get_title()

    def select_title(self, number: int) -> None:
        self._player.set_title(number)

    def chapters(self, title: int | None = None) -> list[int]:
        """Chapter marks for a title. Same allocation rules as :meth:`titles`."""
        number = self._player.get_title() if title is None else title
        cached = self._chapters_cache.get(number)
        if cached is not None:
            return list(cached)

        vlc = self._vlc
        pointer = ctypes.POINTER(vlc.ChapterDescription)()
        count = vlc.libvlc_media_player_get_full_chapter_descriptions(
            self._player, number, ctypes.byref(pointer)
        )
        if count <= 0:
            return []
        try:
            array = ctypes.cast(
                pointer, ctypes.POINTER(ctypes.POINTER(vlc.ChapterDescription) * count)
            ).contents
            marks = [int(array[index].contents.time_offset) for index in range(count)]
        finally:
            self._release_array("libvlc_chapter_descriptions_release", pointer, count)

        self._chapters_cache[number] = marks
        return list(marks)

    def select_chapter(self, number: int) -> None:
        self._player.set_chapter(number)

    def navigate(self, action: NavAction) -> None:
        if action == NavAction.TOP_MENU:
            # A disc's Top Menu is the title libbluray flags as the menu; on a
            # DVD, dvdnav answers the same request through the popup action.
            for title in self.titles():
                if title.is_menu:
                    self._player.set_title(title.number)
                    return
            action = NavAction.POPUP_MENU
        name = _NAVIGATE.get(action)
        if name is None:
            return
        mode = getattr(self._vlc.NavigateMode, name)
        self._vlc.libvlc_media_player_navigate(self._player, mode.value)

    @property
    def supports_dvd(self) -> bool:
        """Whether the bound runtime carries the DVD plugin.

        ``has_plugin`` answers False for a runtime that is missing; a
        runtime that is present and refused (``RuntimeRefused``) is also
        not one we play DVDs with, and it used to escape as an exception
        from a property the window reads while opening a disc.
        """
        try:
            return has_plugin("libdvdnav_plugin.dll")
        except RuntimeRefused:
            return False

    def main_feature_title(self) -> int | None:
        """The longest ordinary title — what "Play main feature" should start.

        Menus are skipped, and so is First Play: libbluray reports it as a
        title with the *menu clip's* length on it, which on a short menu is
        longer than the feature's reported length, because a Blu-ray does not
        tell a player how long a title is until it plays one. Skipping both
        leaves only the titles a viewer would call titles.
        """
        candidates = [
            title for title in self.titles() if not title.is_menu and not title.is_interactive
        ]
        if not candidates:
            return None
        timed = [title for title in candidates if title.duration_ms]
        if timed:
            return max(timed, key=lambda title: title.duration_ms).number
        return candidates[0].number

    def _meta(self, item: object, field: str) -> str:
        """One metadata field, by name.

        Asked for by name because ``libvlc_meta_t`` has grown members over
        the years and the bundled python-vlc may be older than the one this
        was written against. A field that does not exist is a field the disc
        did not have.
        """
        key = getattr(self._vlc.Meta, field, None)
        if key is None:
            return ""
        try:
            return _text(item.get_meta(key))
        except Exception:
            return ""

    def audio_cd_tracks(self, target: MediaTarget, timeout_ms: int = 8000) -> list[str]:
        """Track names from an audio CD, one string per track.

        Kept because it is the smallest thing a caller can want. Everything
        it knows comes from :meth:`audio_cd_info`.
        """
        info = self.audio_cd_info(target, timeout_ms)
        return [
            f"{track.title} · {track.artist}" if track.artist and track.title else track.title
            for track in info.tracks
        ]

    def audio_cd_info(self, target: MediaTarget, timeout_ms: int = 8000) -> AudioCdInfo:
        """What an audio CD says about itself, from CD-TEXT where it has any.

        The disc is parsed rather than played: libvlc reads the table of
        contents and any CD-TEXT, and hands back one sub-item per track. A
        disc with no CD-TEXT gives numbered tracks and no album name, which
        is what a disc with no CD-TEXT deserves — the table of contents is
        still real, so the track *lengths* are right either way.
        """
        media = self._instance.media_new(target.mrl)
        try:
            media.parse_with_options(self._vlc.MediaParseFlag.local, timeout_ms)
        except AttributeError:  # older python-vlc
            media.parse()
        deadline = timeout_ms / 1000.0
        step = 0.1
        waited = 0.0
        while waited < deadline:
            try:
                if media.get_parsed_status() == self._vlc.MediaParsedStatus.done:
                    break
            except AttributeError:
                break
            time.sleep(step)
            waited += step

        tracks: list[CdTrack] = []
        album = ""
        album_artist = ""
        subitems = media.subitems()
        if subitems is not None:
            subitems.lock()
            try:
                for index in range(subitems.count()):
                    item = subitems.item_at_index(index)
                    if item is None:
                        continue
                    title = _text(item.get_meta(self._vlc.Meta.Title))
                    artist = _text(item.get_meta(self._vlc.Meta.Artist))
                    album = album or _text(item.get_meta(self._vlc.Meta.Album))
                    album_artist = album_artist or self._meta(item, "AlbumArtist") or artist
                    try:
                        duration = max(0, int(item.get_duration()))
                    except Exception:
                        duration = 0
                    tracks.append(
                        CdTrack(
                            number=index + 1,
                            title=title or f"Track {index + 1}",
                            artist=artist,
                            duration_ms=duration,
                        )
                    )
            finally:
                subitems.unlock()
        return AudioCdInfo(album=album, artist=album_artist, tracks=tuple(tracks))

    # -- tracks ------------------------------------------------------------

    def audio_tracks(self) -> list[Track]:
        return self._describe(self._player.audio_get_track_description(), "Audio")

    def select_audio_track(self, identifier: int) -> None:
        self._player.audio_set_track(identifier)

    def subtitle_tracks(self) -> list[Track]:
        return self._describe(self._player.video_get_spu_description())

    def select_subtitle_track(self, identifier: int) -> None:
        self._player.video_set_spu(identifier)

    @staticmethod
    def _describe(descriptions: object, kind: str = "Subtitles") -> list[Track]:
        # ``kind`` is a caller-supplied word, not copy: see wti_player.strings.
        """VLC's track list, in our words.

        ``kind`` matters: both lists carry a "Disable" entry, and calling the
        one at the top of the AUDIO menu "Subtitles off" is how a disc ends
        up offering to turn off something it is not showing.
        """
        out: list[Track] = []
        for identifier, name in descriptions or []:  # type: ignore[union-attr]
            label = _text(name)
            # VLC calls the "none of them" entry "Disable", which is its word
            # for a setting, not ours for a choice a viewer makes.
            if label.lower() in ("disable", "disabled"):
                label = kind + " off"
            out.append(Track(identifier=int(identifier), name=label))
        return out
