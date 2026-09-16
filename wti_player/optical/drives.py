"""Find the optical drives, and notice when a disc goes in or comes out.

Everything that touches Windows is behind :class:`DriveScanner`, so the rest
of the Player — and every test — can run against :class:`FakeScanner` with a
disc that does not exist. The untestable surface is one function,
:func:`_scan_windows`, and it is deliberately dull.

Insertion is noticed by polling. A drive takes a few seconds to spin up and
mount anyway, so a poll every second and a half costs nothing and is far less
to get wrong than a window-message hook — and it works the same whether the
Player has a window yet or not.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Protocol

#: What Windows calls an optical drive in ``GetDriveTypeW``.
_DRIVE_CDROM = 5


@dataclass(frozen=True)
class OpticalDrive:
    """One optical drive, and whatever is in it right now."""

    #: ``E:\\`` on Windows, a mount point elsewhere.
    mount: str
    #: A name to put in front of a person: "BD-ROM Drive (E:)".
    description: str = ""
    has_media: bool = False
    #: The disc's volume label, when it has one.
    label: str = ""
    #: ``UDF``, ``CDFS``, ``ISO9660``... empty when nothing is mounted.
    filesystem: str = ""

    @property
    def letter(self) -> str:
        """``E`` on Windows, the mount point's name elsewhere."""
        return self.mount[0] if self.mount[1:2] == ":" else Path(self.mount).name

    @property
    def root(self) -> Path:
        return Path(self.mount)

    @property
    def device_path(self) -> str:
        r"""The raw device, ``\\.\E:``, for engines that want it over a path."""
        if self.mount[1:2] == ":":
            return rf"\\.\{self.mount[0]}:"
        return self.mount

    def describe(self) -> str:
        if not self.has_media:
            return f"{self.description or self.mount} · empty"
        return f"{self.description or self.mount} · {self.label or 'untitled disc'}"


class DriveScanner(Protocol):
    """Anything that can list the optical drives."""

    def scan(self) -> list[OpticalDrive]:
        """Every optical drive on the machine, in a stable order."""
        ...


class FakeScanner:
    """A scanner tests drive by hand.

    ``insert`` and ``eject`` do to a fake drive what a person does to a real
    one, so a test can exercise the whole insertion path without hardware.
    """

    def __init__(self, drives: Iterable[OpticalDrive] = ()) -> None:
        self._drives = list(drives)

    def scan(self) -> list[OpticalDrive]:
        return list(self._drives)

    def add(self, drive: OpticalDrive) -> None:
        self._drives.append(drive)

    def insert(self, mount: str, *, label: str = "", filesystem: str = "UDF") -> None:
        self._replace(mount, has_media=True, label=label, filesystem=filesystem)

    def eject(self, mount: str) -> None:
        self._replace(mount, has_media=False, label="", filesystem="")

    def _replace(self, mount: str, **changes: object) -> None:
        for index, drive in enumerate(self._drives):
            if drive.mount == mount:
                self._drives[index] = replace(drive, **changes)  # type: ignore[arg-type]
                return
        raise KeyError(f"no fake drive at {mount}")


def _scan_windows() -> list[OpticalDrive]:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # Stop Windows popping "There is no disc in the drive" at the user while
    # we are the ones asking. SEM_FAILCRITICALERRORS.
    previous = kernel32.SetErrorMode(0x0001)
    try:
        drives: list[OpticalDrive] = []
        mask = kernel32.GetLogicalDrives()
        for index in range(26):
            if not mask & (1 << index):
                continue
            mount = f"{chr(ord('A') + index)}:\\"
            if kernel32.GetDriveTypeW(mount) != _DRIVE_CDROM:
                continue
            label_buffer = ctypes.create_unicode_buffer(261)
            fs_buffer = ctypes.create_unicode_buffer(261)
            ok = kernel32.GetVolumeInformationW(
                mount,
                label_buffer,
                ctypes.sizeof(label_buffer) // ctypes.sizeof(ctypes.c_wchar),
                None,
                None,
                None,
                fs_buffer,
                ctypes.sizeof(fs_buffer) // ctypes.sizeof(ctypes.c_wchar),
            )
            drives.append(
                OpticalDrive(
                    mount=mount,
                    description=f"Disc drive ({mount[:2]})",
                    has_media=bool(ok),
                    label=label_buffer.value if ok else "",
                    filesystem=fs_buffer.value if ok else "",
                )
            )
        return drives
    finally:
        kernel32.SetErrorMode(previous)


def _scan_posix() -> list[OpticalDrive]:
    """Mac and Linux: whatever is mounted where optical media lands."""
    roots = [Path("/Volumes"), Path("/media"), Path("/run/media"), Path("/mnt")]
    drives: list[OpticalDrive] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and ((child / "BDMV").is_dir() or (child / "VIDEO_TS").is_dir()):
                drives.append(
                    OpticalDrive(
                        mount=str(child),
                        description=child.name,
                        has_media=True,
                        label=child.name,
                    )
                )
    return drives


class SystemScanner:
    """The real one."""

    def scan(self) -> list[OpticalDrive]:
        if sys.platform == "win32":
            return _scan_windows()
        return _scan_posix()


class DriveEventKind(Enum):
    APPEARED = "appeared"
    INSERTED = "inserted"
    EJECTED = "ejected"
    REMOVED = "removed"


@dataclass(frozen=True)
class DriveEvent:
    kind: DriveEventKind
    drive: OpticalDrive


class DriveWatcher:
    """Turns repeated scans into "a disc went in" / "a disc came out".

    The caller decides how often to :meth:`poll` — the UI hangs it off a
    timer. Nothing here starts a thread, which keeps the whole thing testable
    by calling ``poll`` by hand.
    """

    def __init__(self, scanner: DriveScanner | None = None) -> None:
        self._scanner: DriveScanner = scanner or SystemScanner()
        self._known: dict[str, OpticalDrive] = {}
        self._started = False

    @property
    def drives(self) -> list[OpticalDrive]:
        return list(self._known.values())

    def find(self, mount: str) -> OpticalDrive | None:
        return self._known.get(mount)

    def poll(self) -> list[DriveEvent]:
        """Rescan and report what changed since last time.

        The first poll reports every drive as ``APPEARED`` and any disc
        already in one as ``INSERTED``, so start-up and insertion take the
        same path through the app.
        """
        events: list[DriveEvent] = []
        current = {drive.mount: drive for drive in self._scanner.scan()}

        for mount, drive in current.items():
            previous = self._known.get(mount)
            if previous is None:
                events.append(DriveEvent(DriveEventKind.APPEARED, drive))
                if drive.has_media:
                    events.append(DriveEvent(DriveEventKind.INSERTED, drive))
            elif drive.has_media and not previous.has_media:
                events.append(DriveEvent(DriveEventKind.INSERTED, drive))
            elif previous.has_media and not drive.has_media:
                events.append(DriveEvent(DriveEventKind.EJECTED, drive))
            elif drive.has_media and previous.has_media and drive.label != previous.label:
                # Swapped quickly enough that we never saw the empty tray.
                events.append(DriveEvent(DriveEventKind.EJECTED, previous))
                events.append(DriveEvent(DriveEventKind.INSERTED, drive))

        for mount, drive in self._known.items():
            if mount not in current:
                events.append(DriveEvent(DriveEventKind.REMOVED, drive))

        self._known = current
        self._started = True
        return events
