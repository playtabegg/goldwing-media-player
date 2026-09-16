"""Work out what a disc *is*, before anything tries to play it.

Given a drive, a folder, an ISO or a BDMV directory, this answers: Blu-ray,
DVD-Video, audio CD, a game disc we made, or plain data. It answers from the
disc's own structure, and it reads that structure with our own parsers rather
than by starting the engine, because libbluray will crash on a disc whose
seek index is damaged. Anything this module refuses never reaches the engine.

It is filesystem-only: give it a path and it works, whether that path is a
drive, a folder on disk, or a mounted image. It is also what makes menu
preview mode possible: a BDMV folder is a disc as far as this is concerned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from ..formats import clpi as clpi_reader
from ..formats import ifo, index_bdmv, mpls
from . import meta as disc_meta
from .image import ImageKind, is_image, peek_image

#: Files an audio CD shows through Windows' CDFS view of it.
_CDA_SUFFIX = ".cda"

#: How much of a data disc to walk before we stop counting and just say "lots".
_MAX_WALK_ENTRIES = 20_000

#: And how long. An optical drive can take seconds per seek on a scratched
#: disc, and a file count is not worth making somebody wait for.
_MAX_WALK_SECONDS = 2.0


class DiscKind(Enum):
    BLU_RAY = "blu-ray"
    DVD_VIDEO = "dvd-video"
    AUDIO_CD = "audio-cd"
    GAME_DISC = "game-disc"
    DATA = "data"
    EMPTY = "empty"
    UNREADABLE = "unreadable"

    @property
    def is_video(self) -> bool:
        return self in (DiscKind.BLU_RAY, DiscKind.DVD_VIDEO)


@dataclass(frozen=True)
class TitleSummary:
    """One playable thing on the disc, as the disc describes it."""

    number: int
    name: str
    duration_ms: int
    chapters: int = 0
    is_menu: bool = False

    @property
    def duration_text(self) -> str:
        seconds = self.duration_ms // 1000
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


@dataclass(frozen=True)
class DiscProfile:
    """Everything we know about a disc without playing it."""

    kind: DiscKind
    root: Path
    label: str = ""
    titles: tuple[TitleSummary, ...] = ()
    #: The title "Play main feature" should start, when we can tell.
    main_feature: int | None = None
    has_menu: bool = False
    needs_bdj: bool = False
    #: Set when something is wrong and the user needs telling.
    problem: str = ""
    #: Set when ``problem`` is not just worth saying but a reason to stop.
    #: Most problems are not: a disc can be missing a clip, have no menu, or
    #: name a codec we do not have, and still be worth opening. This is for
    #: the ones where opening it is what does the damage — a damaged seek
    #: index takes libbluray down with it, and the crash lands on the user
    #: with no window and no message.
    refuses: bool = False
    #: "aacs" when the disc carries Blu-ray encryption, "" when it does not.
    #: CSS on a DVD cannot be seen from the filesystem, so it is not set here
    #: — that one shows up as a read failure once a DVD engine exists.
    protection: str = ""
    #: For a data or game disc.
    file_count: int = 0
    total_bytes: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: What the disc says about itself — its real name, who made it, the
    #: chapter names somebody typed into a form months ago, and where its
    #: artwork is. ``None`` for a disc that is not one of ours, which is most
    #: of them; everything downstream has to work without it.
    meta: disc_meta.DiscMeta | None = None
    #: We The Indies made this: our document, our edition, or the Rialto
    #: menu fileset. A game from someone else is still a game disc; it is
    #: not this.
    ours: bool = False

    @property
    def display_name(self) -> str:
        """What to put at the top of the window.

        The disc's own name if it carries one, then its volume label, then
        the folder it was opened from. Never empty, because a blank headline
        reads as a bug.
        """
        if self.meta is not None and self.meta.title:
            return self.meta.title
        if self.label:
            return self.label
        return self.root.name or str(self.root)

    @property
    def art(self) -> disc_meta.DiscArt:
        return self.meta.art if self.meta is not None else disc_meta.DiscArt()

    def chapter_names_or_empty(self) -> tuple[str, ...]:
        """The names the factory wrote for this disc's chapters, if any.

        A disc that is not one of ours has marks and no names, which is
        still more than any of this could show before.
        """
        return self.meta.chapter_names() if self.meta is not None else ()

    @property
    def playable(self) -> bool:
        if self.protection:
            return False
        return self.kind.is_video or self.kind == DiscKind.AUDIO_CD

    @property
    def is_encrypted(self) -> bool:
        return bool(self.protection)

    @property
    def browsable(self) -> bool:
        return self.kind in (DiscKind.DATA, DiscKind.GAME_DISC)

    def title(self, number: int) -> TitleSummary | None:
        for entry in self.titles:
            if entry.number == number:
                return entry
        return None


def _bdmv_dir(root: Path) -> Path | None:
    for candidate in (root / "BDMV", root):
        if (candidate / "index.bdmv").is_file() or (candidate / "PLAYLIST").is_dir():
            return candidate
    return None


def _aacs_present(root: Path) -> bool:
    """A commercial Blu-ray carries an AACS folder beside its BDMV.

    This is the disc telling us what it is, in the clear. Nothing here reads
    or touches the keys — the folder's existence is the whole signal.
    """
    aacs = root / "AACS"
    if not aacs.is_dir():
        return False
    return any(
        (aacs / name).exists()
        for name in ("Unit_Key_RO.inf", "Content000.cer", "MKB_RO.inf", "CPSUnit00001.cci")
    ) or any(aacs.iterdir())


def _identify_blu_ray(root: Path, bdmv: Path, label: str) -> DiscProfile:
    notes: list[str] = []
    needs_bdj = False
    has_menu = False
    problem = ""
    refuses = False

    if _aacs_present(root):
        return DiscProfile(
            kind=DiscKind.BLU_RAY,
            root=root,
            label=label,
            protection="aacs",
            problem="This Blu-ray is encrypted with AACS.",
            refuses=True,
        )

    try:
        index = index_bdmv.read_index(bdmv)
        needs_bdj = index.uses_bdj
        has_menu = index.has_top_menu
    except index_bdmv.IndexError_ as exc:
        notes.append(f"index.bdmv could not be read ({exc})")

    playlists = mpls.read_all(bdmv / "PLAYLIST")
    if not playlists:
        return DiscProfile(
            kind=DiscKind.BLU_RAY,
            root=root,
            label=label,
            has_menu=has_menu,
            needs_bdj=needs_bdj,
            problem="This Blu-ray has no playlists Goldwing can read.",
            refuses=True,
            notes=tuple(notes),
        )

    clips = clpi_reader.read_all(bdmv / "CLIPINF")
    referenced = {clip_id for playlist in playlists for clip_id in playlist.clip_ids}
    missing_clips = {clip_id for clip_id in referenced if clip_id not in clips}
    if missing_clips:
        notes.append(
            "playlists reference clips that are not on the disc: "
            + ", ".join(sorted(missing_clips))
        )

    # libbluray crashes rather than complains on a clip with no seek index,
    # so that check happens here, before anything opens the disc for real.
    unseekable = _clips_without_seek_index(bdmv, clips, referenced)
    if unseekable:
        refuses = True
        problem = (
            "This disc's seek index is damaged, so Goldwing will not open it. "
            "That usually means the disc is scratched or the copy is incomplete."
        )
        notes.append("clips with no entry-point map: " + ", ".join(sorted(unseekable)))

    feature = mpls.main_feature(playlists)
    titles = tuple(
        TitleSummary(
            number=number,
            name=f"Title {number + 1}",
            duration_ms=playlist.duration_ms,
            chapters=len(playlist.chapters_ms),
            is_menu=playlist.looks_like_menu,
        )
        for number, playlist in enumerate(playlists)
    )
    has_menu = has_menu or any(playlist.has_interactive_graphics for playlist in playlists)
    if needs_bdj:
        notes.append(
            "Parts of this disc are BD-J, which needs Java. Goldwing does not run it; "
            "the titles below still play."
        )

    return DiscProfile(
        kind=DiscKind.BLU_RAY,
        root=root,
        label=label,
        titles=titles,
        main_feature=playlists.index(feature) if feature is not None else None,
        has_menu=has_menu,
        needs_bdj=needs_bdj,
        problem=problem,
        refuses=refuses,
        notes=tuple(notes),
    )


def _clips_without_seek_index(
    bdmv: Path,
    clips: dict[str, clpi_reader.ClipInfo],
    referenced: set[str] | None = None,
) -> list[str]:
    """Clip ids whose seek index would take libbluray down.

    This is the gate that exists because libbluray dereferences an entry-point
    map without checking it, and an access violation is not something a person
    can be shown. Three things were wrong with the version this replaces.

    **It read one field.** Whether the CPI block's length was zero, and nothing
    inside it. A single corrupted 18-bit fine-entry reference — three bytes on
    a scratched disc — sailed through and killed the process on ``play()``.
    The block is now walked and checked.

    **It only looked at clips that had already parsed.** ``clpi.read_all``
    drops a file it cannot read, so a damaged CLIPINF sector, which is the
    likeliest damage there is, left this iterating over an empty dictionary
    and reporting nothing wrong. It now walks what is on disc and what the
    playlists reference, and a clip that will not parse is broken by
    definition.

    **It re-read every file** that ``read_all`` had just read, which on an
    optical drive is a second seek per clip.
    """
    broken: list[str] = []
    seen: set[str] = set()

    wanted = set(clips) | (referenced or set())
    try:
        wanted |= {path.stem for path in (bdmv / "CLIPINF").glob("*.clpi")}
    except OSError:
        pass

    for clip_id in sorted(wanted):
        if clip_id in seen:
            continue
        seen.add(clip_id)
        path = bdmv / "CLIPINF" / f"{clip_id}.clpi"
        try:
            data = path.read_bytes()
        except OSError:
            broken.append(clip_id)
            continue
        if not clpi_reader.seek_index_is_sound(data):
            broken.append(clip_id)
    return broken


def _identify_dvd(root: Path, video_ts: Path, label: str) -> DiscProfile:
    """A DVD, read from its own IFO tables rather than by an engine.

    The Player carries no DVD engine, so this is where a DVD's titles and
    chapters come from. It also means nothing here can touch an encrypted
    sector: the IFOs are in the clear on every disc ever pressed, and the
    scrambled part is the video, which libvlc fails to play.
    """
    try:
        disc = ifo.read(root)
    except ifo.IfoError as exc:
        return DiscProfile(
            kind=DiscKind.DVD_VIDEO,
            root=root,
            label=label,
            problem=f"This DVD's table of contents could not be read. {exc}.",
        )

    titles = tuple(
        TitleSummary(
            number=title.number,
            name=title.name,
            duration_ms=title.duration_ms,
            chapters=len(title.chapters_ms) or title.chapter_count,
        )
        for title in disc.titles
    )
    feature = disc.main_feature
    notes: list[str] = []
    if any(not title.duration_ms for title in disc.titles):
        notes.append("Some titles do not declare a length; they play from the start.")

    # Whether this disc has a menu we can show. Read from the IFOs, which is
    # cheap, rather than assumed from the fact that most DVDs have one. A
    # "menu" button that does nothing is worse than no button.
    try:
        menus = ifo.read_menus(root)
        has_menu = menus.has_menus and bool(menus.vob_files)
    except (OSError, ValueError):
        has_menu = False

    return DiscProfile(
        kind=DiscKind.DVD_VIDEO,
        root=root,
        label=label,
        titles=titles,
        main_feature=feature.number if feature is not None else None,
        has_menu=has_menu,
        file_count=len(list(video_ts.glob("*.VOB"))),
        notes=tuple(notes),
    )


def _identify_audio_cd(root: Path, tracks: list[Path], label: str) -> DiscProfile:
    titles = tuple(
        TitleSummary(number=number, name=path.stem, duration_ms=0)
        for number, path in enumerate(tracks)
    )
    return DiscProfile(
        kind=DiscKind.AUDIO_CD,
        root=root,
        label=label,
        titles=titles,
        main_feature=0 if titles else None,
        file_count=len(tracks),
        notes=("Track names come from CD-TEXT when the disc carries it.",),
    )


def _walk(root: Path) -> tuple[int, int]:
    files = 0
    total = 0
    stack = [root]
    deadline = time.monotonic() + _MAX_WALK_SECONDS
    while stack and files < _MAX_WALK_ENTRIES and time.monotonic() < deadline:
        current = stack.pop()
        try:
            for entry in current.iterdir():
                if entry.is_dir():
                    stack.append(entry)
                else:
                    files += 1
                    try:
                        total += entry.stat().st_size
                    except OSError:
                        pass
                    if files >= _MAX_WALK_ENTRIES:
                        break
        except OSError:
            continue
    return files, total


def _folder_is_ours(root: Path) -> bool:
    """The factory's fileset or document, not a guess from autorun."""
    return (
        (root / "menu" / "menu.exe").is_file()
        or (root / ".wti_meta.json").is_file()
        or (root / "menu" / ".wti_meta.json").is_file()
        or (root / ".wti_edition.json").is_file()
    )


def _identify_data(root: Path, label: str) -> DiscProfile:
    autorun = root / "autorun.inf"
    # The launcher on a WTI game disc is at menu/menu.exe. Rialto 1.5 puts it
    # there, a test over in the factory guards that fileset name for name, and
    # this looked for it at the root — so every disc we have ever pressed
    # would have read as a plain data disc. The root form is kept because a
    # disc from somewhere else may use it.
    has_our_menu = (root / "menu" / "menu.exe").is_file()
    ours = _folder_is_ours(root)
    is_game = autorun.is_file() or has_our_menu
    files, total = _walk(root)
    notes: list[str] = []
    if autorun.is_file():
        # cp1252, which is what Windows writes and what the factory writes.
        # Read as latin-1 the bytes 0x80-0x9F come back as control codes, so
        # a curly quote or an em dash in a disc's label turns to rubbish.
        for line in autorun.read_text(encoding="cp1252", errors="replace").splitlines():
            if line.lower().startswith("label="):
                label = label or line.split("=", 1)[1].strip()
    return DiscProfile(
        kind=DiscKind.GAME_DISC if is_game else DiscKind.DATA,
        root=root,
        label=label,
        file_count=files,
        total_bytes=total,
        notes=tuple(notes),
        ours=ours,
    )


def identify(target: Path | str, *, label: str = "") -> DiscProfile:
    """What is this? Works on a drive root, a folder, a BDMV directory, or an image.

    An ``.iso`` is peeked, not guessed: a game disc is a game disc, a DVD is
    a DVD, and only an image that actually carries a BDMV is a Blu-ray.
    """
    root = Path(target)
    if not root.exists():
        return DiscProfile(
            kind=DiscKind.UNREADABLE,
            root=root,
            label=label,
            problem="There is nothing at that path.",
        )
    if root.is_file():
        if is_image(root):
            return _identify_image(root, label)
        return DiscProfile(
            kind=DiscKind.UNREADABLE,
            root=root,
            label=label,
            problem="That is a file, not a disc.",
        )

    try:
        entries = list(root.iterdir())
    except OSError as exc:
        return DiscProfile(
            kind=DiscKind.UNREADABLE,
            root=root,
            label=label,
            problem=_read_failure_text(exc),
        )
    if not entries:
        return DiscProfile(kind=DiscKind.EMPTY, root=root, label=label)

    tracks = sorted(path for path in entries if path.suffix.lower() == _CDA_SUFFIX)
    if tracks:
        return _identify_audio_cd(root, tracks, label)
    # An album's locker copy: the mastered WAVs beside their CUE sheet, the
    # same bytes the workshop wrote to the disc. Read as the album it is,
    # not as a data folder (the second survey, 30 Aug 2026).
    if any(path.suffix.lower() == ".cue" for path in entries):
        wavs = sorted(path for path in entries if path.suffix.lower() == ".wav")
        if wavs:
            return _with_meta(_identify_audio_cd(root, wavs, label))

    bdmv = _bdmv_dir(root)
    if bdmv is not None:
        return _with_meta(_identify_blu_ray(root, bdmv, label))

    video_ts = root / "VIDEO_TS"
    if video_ts.is_dir():
        return _with_meta(_identify_dvd(root, video_ts, label))
    if root.name.upper() == "VIDEO_TS":
        return _with_meta(_identify_dvd(root.parent, root, label))

    return _with_meta(_identify_data(root, label))


def _identify_image(root: Path, label: str) -> DiscProfile:
    """A disc image, named from what is actually in it."""
    from .. import strings

    peek = peek_image(root)
    name = label or peek.label or root.stem
    if peek.kind is ImageKind.UNREADABLE:
        return DiscProfile(
            kind=DiscKind.UNREADABLE,
            root=root,
            label=name,
            problem="This disc image could not be read.",
        )
    if peek.kind is ImageKind.BLU_RAY:
        return DiscProfile(
            kind=DiscKind.BLU_RAY,
            root=root,
            label=name,
            notes=(strings.IMAGE_NOTE_BLU_RAY,),
        )
    if peek.kind is ImageKind.DVD_VIDEO:
        return DiscProfile(
            kind=DiscKind.DVD_VIDEO,
            root=root,
            label=name,
            notes=(strings.IMAGE_NOTE_DVD,),
        )
    if peek.kind is ImageKind.GAME:
        return DiscProfile(
            kind=DiscKind.GAME_DISC,
            root=root,
            label=name,
            notes=(strings.game_note(ours=peek.ours, image=True),),
            ours=peek.ours,
        )
    return DiscProfile(
        kind=DiscKind.DATA,
        root=root,
        label=name,
        notes=(strings.IMAGE_NOTE_DATA,),
    )


def _with_meta(profile: DiscProfile) -> DiscProfile:
    """Attach what the disc says about itself, if it says anything.

    Done here, once, rather than in each identifier: the document is in the
    same place whatever kind of disc it turns out to be, and a reader that
    forgets to look on one path is a disc that mysteriously has no name.

    A BDMV or VIDEO_TS folder opened directly is a disc whose root is one
    level up, so both are tried. Reading is best-effort by construction —
    :func:`meta.read` swallows its own failures — but it touches an optical
    drive, so an unexpected OS error is caught here too.
    """
    roots = [profile.root]
    if profile.root.name.upper() in ("BDMV", "VIDEO_TS"):
        roots.append(profile.root.parent)
    for root in roots:
        try:
            document = disc_meta.read(root)
        except OSError:
            document = None
        if document is not None:
            return replace(profile, meta=document, ours=True)
    return profile


def _read_failure_text(exc: OSError) -> str:
    """Turn an OS error into something worth showing a person."""
    if exc.errno in (13, 5):  # EACCES / EIO
        return "The disc could not be read. It may be dirty, scratched, or still spinning up."
    return "The disc could not be read."
