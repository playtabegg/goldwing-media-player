"""Everything the Player says to a person, in one file.

Copy lives here so it can be read and fixed as prose, without hunting through
widget code. "Never a stack trace at a customer" is a promise about text, and
it is easier to keep when all the text is in one place.

House style, borrowed from Rialto: say what happened and what to do about it.
No error codes, no blame, no exclamation marks. "Made by hand", never
"pressed", never "burned".
"""

from __future__ import annotations

from .inputs.actions import SKIP_MS
from .version import APP_NAME, PUBLISHER, build_stamp, display_version

# -- the empty state -------------------------------------------------------

WELCOME_TITLE = "Put a disc in."
DROP_HINT = "Drop a disc folder or image on the window to open it."
WELCOME_BODY = (
    "A game disc, an unprotected Blu-ray or DVD, an audio CD, or a data disc "
    "from twenty years ago. This plays all of them. " + DROP_HINT
)
#: The product's one sentence, on the screen a person sees first. Everything
#: else the Player says follows from it.
WELCOME_PROMISE = (
    "A disc you own should outlive the company that sold it to you. "
    "Nothing here needs an account, and nothing here checks anything on its own."
)
NO_DRIVE = "No disc drive found. Plug one in and GoldWing will notice."
DRIVE_EMPTY = (
    "The drive is empty. Put a disc in, or open a folder or a disc image "
    "from the Disc menu."
)
READING_DISC = "Reading the disc…"
READING_MENU = "Reading the menu…"

OPEN_DISC = "Open disc"
OPEN_FOLDER = "Open a folder…"
OPEN_IMAGE = "Open a disc image…"

# -- the shelf (W2, 30 Aug 2026) --------------------------------------------
#
# Local copies of discs, laid out like the disc, beside the drives. A film
# or an album plays from its copy without the disc; a game's copy opens its
# own disc menu.

SHELF_TITLE = "Your shelf"
SHELF_EMPTY = "Nothing on the shelf yet. A copy is a folder laid out like the disc, so you can play it without the disc in the drive."
ADD_TO_SHELF = "Add a copy to the shelf…"
ADD_TO_SHELF_TIP = (
    "A copy is a folder laid out like the disc: the disc document, the art, "
    "and for a game the disc menu. It stays on this computer. GoldWing does "
    "not need Rook for this."
)
REMOVE_FROM_SHELF = "Take off the shelf"
NOT_A_COPY = (
    "That folder has no disc document in it, so GoldWing cannot tell what "
    "it is. Pick the folder that holds the disc's own files, the one with "
    "the disc document in it."
)
OPEN_GAME_MENU = "Open the disc menu"
GAME_MENU_OPENED = "Opened the disc menu. GoldWing stays where it is."
GAME_MENU_MISSING = (
    "This copy has no disc menu to open. Put the disc in a drive and "
    "GoldWing will open the menu from there."
)
GO_HOME = "Home"
KIND_OURS_GAME = "We The Indies game"
GAME_OURS = (
    "This is a We The Indies game. GoldWing opens the disc menu. "
    "The game itself is what plays."
)
GAME_OURS_IMAGE = (
    "This is a We The Indies game, saved as a disc image. "
    "Put the disc in a drive, or open the folder laid out like the disc, "
    "and GoldWing will open the disc menu. The game itself is what plays."
)
GAME_OTHER = (
    "This is a game from someone else. GoldWing will show the files on it "
    "if you open the folder. It does not start the game."
)
GAME_OTHER_IMAGE = (
    "This is a game disc image from someone else. "
    "GoldWing will show the files if you open the folder. "
    "It does not start the game."
)
PLAY_MAIN_FEATURE = "Play main feature"
BACK_TO_MENU = "Top menu"

# -- controls, named so an icon can be learned -----------------------------
#
# Every icon-only control carries one of these as its tooltip and as the name
# a screen reader says.

# Taken from the constant the buttons actually use, so the label cannot
# promise thirty seconds while the button moves ten.
SKIP_BACK = f"Back {SKIP_MS // 1000} seconds"
SKIP_FORWARD = f"Forward {SKIP_MS // 1000} seconds"
FULL_SCREEN = "Full screen"
LEAVE_FULL_SCREEN = "Leave full screen"
HIDE_PANEL = "Hide the panel"
SHOW_PANEL = "Show the panel"
EJECT = "Eject"
OPEN_RECENT = "Open &recent"
RECENT_EMPTY = "Nothing opened by hand yet"
CLEAR_RECENT = "Forget these"
RELOAD_FOLDER = "Reload folder"

AUDIO = "Audio"
AUDIO_TRACK = "Audio track"
SUBTITLES = "Subtitles"
AUDIO_CD = "Audio CD"

#: The section heading over a disc's list of titles.
ON_THIS_DISC = "On this disc"
TRACKS = "Tracks"
FILES = "Files"
EXTRAS = "Extras"
CHAPTERS = "Chapters"

# -- what a disc turned out to be ------------------------------------------

KIND_NAMES = {
    "blu-ray": "Blu-ray",
    "dvd-video": "DVD",
    "audio-cd": "Audio CD",
    "game-disc": "Game disc",
    "data": "Data disc",
    "empty": "Empty drive",
    "unreadable": "Unreadable disc",
}

# -- things that go wrong --------------------------------------------------

CANNOT_READ_DISC = (
    "This disc could not be read. It may be dirty or scratched. "
    "A wipe with a soft cloth, from the centre outwards, fixes more discs than you would think."
)
CANNOT_READ_BLU_RAY = (
    "This Blu-ray could not be read. If it is a commercial disc it is locked, "
    "and GoldWing does not carry that licence. If it is one of ours, the copy "
    "may be incomplete: take the disc out, put it back in, and try it again."
)
IMAGE_NOTE_BLU_RAY = "A Blu-ray disc image."
IMAGE_NOTE_DVD = "A DVD disc image."
IMAGE_NOTE_GAME = GAME_OURS_IMAGE
IMAGE_NOTE_DATA = (
    "A disc image. GoldWing can tell this is a disc, but not a film, "
    "an album, or a Blu-ray. If it is a game, put it in a drive or open "
    "the folder laid out like the disc."
)
# Protected-disc messages explain current support and the licensing roadmap.

#: Where the whole of what GoldWing plays and does not play is written out.
#: Named in both encrypted-disc dialogs so nobody has to go looking for it.
PLAYER_PAGE = "wetheindies.com/player"

#: One sentence, said the same way in both dialogs.
UNPROTECTED_ONLY = (
    "GoldWing plays unprotected discs only: unprotected Blu-rays and DVDs, "
    "audio CDs, data discs, game discs, and every disc we make."
)

#: The headline over each of those dialogs. It says what the disc is, not
#: what a codec did.
PROTECTED_BLU_RAY_TITLE = "This is a locked commercial Blu-ray"
PROTECTED_DVD_TITLE = "This is a locked commercial DVD"

PROTECTED_BLU_RAY = (
    "This is a locked commercial Blu-ray, so it will not play here.\n\n"
    "Protected Blu-rays require licensed playback software. GoldWing does "
    "not currently include that licensed support.\n\n"
    "Our roadmap includes officially licensed playback for protected DVDs "
    "and Blu-rays, subject to obtaining the licences, meeting their "
    "requirements and releasing an update. There is no release date yet.\n\n"
    "So GoldWing carries no lock-breaker. " + UNPROTECTED_ONLY + " Take this "
    "disc out and put in one of those, or read the whole list at "
    f"{PLAYER_PAGE}.\n\n"
    "We think this is the wrong way round. A disc you own should outlive the "
    "company that sold it to you, and the shop it came from, and us. That is "
    "the whole reason we make discs."
)

PROTECTED_DVD = (
    "This is a locked commercial DVD, so it will not play here.\n\n"
    "We plan to add officially licensed playback for protected DVDs and "
    "Blu-rays, and we are going after it through the appropriate licensing "
    "processes. Support depends on obtaining the licences, meeting their "
    "requirements and releasing an update. There is no release date yet.\n\n"
    "Until then GoldWing carries no lock-breaker. " + UNPROTECTED_ONLY + " "
    "Take this disc out and put in one of those, or read the whole list at "
    f"{PLAYER_PAGE}.\n\n"
    "A disc you own should outlive the company that sold it to you. That is "
    "the whole reason we make discs, and it is why we would rather pay for the "
    "key than break the lock."
)

#: Short forms, for the About box and anywhere a paragraph will not fit.
PROTECTED_SHORT = (
    "Copy-protected commercial discs will not play. We would rather pay for the "
    "key than break the lock, and this build carries neither licence."
)
NEEDS_JAVA = (
    "This disc's menus are written in BD-J, which needs a Java runtime "
    "GoldWing does not include. Its titles still play: pick one below."
)
DAMAGED_INDEX = (
    "This disc's seek index is damaged, so GoldWing will not open it. "
    "That usually means the disc is scratched or the copy is incomplete. "
    "A wipe with a soft cloth, or another copy, is the thing to try."
)
NOTHING_TO_PLAY = (
    "There is nothing on this disc GoldWing knows how to play. "
    "Its files are listed in the panel, so you can still see what is on it."
)
UNEXPECTED_PROBLEM = (
    "Something went wrong that GoldWing did not expect. Nothing on the disc "
    "was changed. Take the disc out and put it back in. If it keeps happening, "
    "start GoldWing with --log and it writes what happened to a file."
)

# -- menu preview mode -----------------------------------------------------

PREVIEW_TITLE = "Menu preview"
PREVIEW_BODY = (
    "Open a BDMV folder and walk its menus before anything is made by hand. "
    "Arrow keys, the mouse or a gamepad all move the highlight."
)
PREVIEW_NO_MENU = (
    "This disc has no interactive menu, only a first-play title. "
    "There is nothing here to walk through."
)

NO_DVD_MENU = (
    "This DVD's menu could not be read, so the titles are listed instead. "
    "Everything on the disc still plays."
)

#: A disc built by a newer factory than this Player knows. Nothing is wrong
#: with it, so the note says so before it says anything else. Lived in
#: ui/views.py until 1 Sep 2026; copy belongs in this file.
DISC_FROM_A_NEWER_FACTORY = (
    "This disc was made by a later version of the factory than this Player "
    "knows about. Everything below is still right, and it all plays. There "
    "may be more on the disc than is being shown."
)

#: Different from the one above, and it matters: a disc with no menu is
#: not a disc whose menu is broken, and telling somebody their disc is
#: damaged when it is fine is the kind of thing they remember.
DVD_HAS_NO_MENU = "This DVD has no menu. Its titles are in the panel."

TITLE_ENDED = "That is the end. Pick something else from the panel, or press play to watch it again."
TITLE_ENDED_MENU = "That is the end. Back to the menu."


def engine_would_not_start(error: BaseException) -> str:
    """The last thing said before the Player gives up on starting."""
    return (
        f"{APP_NAME} could not start its video engine.\n\n{error}\n\n"
        "Reinstalling GoldWing usually fixes this. Running it with --log "
        "writes what happened to a file."
    )


def cannot_open_file(name: str) -> str:
    return (
        f"Windows has nothing set up to open {name}, so GoldWing left it "
        "alone. Everything on this disc that plays is in the panel."
    )


NOTHING_TO_FILL_THE_SCREEN = (
    "There is no picture to fill the screen with. This disc is a folder of "
    "files, and they are all listed in the panel."
)


def menu_command_unsupported(reason: str) -> str:
    """A menu button asked for something the Player does not follow.

    Said out loud rather than guessed at: sending somebody to the wrong part
    of a disc is the worse failure.
    """
    detail = f" ({reason})" if reason else ""
    return (
        "That button asks this disc to do something GoldWing does not "
        f"follow yet{detail}. The titles all play from the list."
    )

# -- checking for a new Player (only when asked) ----------------------------

UPDATE_MENU = "Check for a new GoldWing…"
UPDATE_CHECKING = "Asking We The Indies for a newer GoldWing…"
UPDATE_UNEXPECTED = (
    "The check did not finish. Nothing was changed, and you can ask again "
    "from the Help menu."
)
UPDATE_NOT_OURS = (
    "The download is not signed by We The Indies, so it was thrown away. "
    "Nothing was installed."
)
UPDATE_COULD_NOT_START = (
    "The installer could not be started. Nothing was changed, and the "
    "GoldWing you have is untouched."
)
UPDATE_INSTALLING = "The installer is running. GoldWing will close for it."
UPDATE_GET = "Download and install"
UPDATE_NOTES = "What changed"
UPDATE_NOT_NOW = "Not now"
UPDATE_DOWNLOADING = "Downloading and checking the new GoldWing…"


def update_offer(version: str, running: str) -> str:
    """The sentence on the offer, before the two buttons."""
    return (
        f"GoldWing {version} is out. You have {running}. "
        "It downloads from We The Indies, is checked twice before it runs, "
        "and GoldWing closes while it installs."
    )


# -- about -----------------------------------------------------------------

ABOUT_TITLE = f"About {APP_NAME}"


def about_text() -> str:
    return (
        f"<h3>{APP_NAME}</h3>"
        f"<p>Version {display_version()}<br>Build {build_stamp()}<br>{PUBLISHER}</p>"
        "<p>One app for the discs we make and the discs you already own.</p>"
        "<p><b>Copy-protected commercial discs will not play</b>: AACS "
        "Blu-rays, and DVDs with CSS. We would rather pay for the key than "
        "break the lock, and this build carries neither licence. Put one in "
        "and GoldWing will explain properly.</p>"
        "<p>A disc you own should outlive the company that sold it to you. "
        "That is the whole reason we make discs.</p>"
        "<p>No account, no telemetry, no update nag. GoldWing checks for a "
        "new version only when you ask it to, from the Help menu, and keeps "
        "nothing about it.</p>"
        "<p style='color:#888'>Playback uses libVLC, © the VideoLAN team, and "
        "decoders from FFmpeg. This program is under the GNU General Public "
        "License v3, which means you are entitled to its source. The full "
        "terms are in <b>licences</b>, beside the program.</p>"
    )


def game_note(*, ours: bool, image: bool) -> str:
    """The paragraph on a game disc screen. Two discs, two sentences."""
    if ours:
        return GAME_OURS_IMAGE if image else GAME_OURS
    return GAME_OTHER_IMAGE if image else GAME_OTHER


def disc_summary(kind: str, label: str, titles: int) -> str:
    """One line under the title list: what this disc is."""
    name = KIND_NAMES.get(kind, "Disc")
    parts = [name]
    if label:
        parts.append(f"“{label}”")
    if titles == 1:
        parts.append("1 title")
    elif titles:
        parts.append(f"{titles} titles")
    return " · ".join(parts)


def file_size(byte_count: int) -> str:
    size = float(byte_count)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def timecode(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
