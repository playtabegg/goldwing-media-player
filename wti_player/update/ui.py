"""The check, from a menu click to a sentence, off the interface thread.

:class:`UpdateCheck` runs :func:`check_for_update` on a worker and reports
on the interface thread. A generation counter drops any answer that arrives
after :meth:`cancel` (the window closed) or after a newer click. Nothing is
kept between checks.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from .. import strings
from .apply import launch_installer
from .check import Outcome, check_for_update
from .download import DownloadProblem, download_installer
from .feed import Release
from .keys import trusted_keys
from .verify import is_ours

OnOutcome = Callable[[Outcome], None]


_FALLBACK_POOL: QThreadPool | None = None


def _pool() -> QThreadPool:
    global _FALLBACK_POOL
    pool = QThreadPool.globalInstance()
    if pool is not None:
        return pool
    if _FALLBACK_POOL is None:
        _FALLBACK_POOL = QThreadPool()
    return _FALLBACK_POOL
OnInstalled = Callable[[str], None]


class UpdateCheck(QObject):
    _checked = pyqtSignal(object, int)
    _downloaded = pyqtSignal(object, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._generation = 0
        self._on_outcome: OnOutcome | None = None
        self._on_installed: OnInstalled | None = None
        self._checked.connect(self._deliver)
        self._downloaded.connect(self._deliver_download)
        self.busy = False

    def start(self, on_outcome: OnOutcome, *, check: Callable[[], Outcome] | None = None) -> None:
        """Run one check. A second click while one runs is ignored."""
        if self.busy:
            return
        self.busy = True
        self._generation += 1
        generation = self._generation
        self._on_outcome = on_outcome
        work = check or check_for_update
        signal = self._checked

        class _Job(QRunnable):
            def run(self) -> None:
                try:
                    outcome = work()
                except Exception:
                    outcome = Outcome(strings.UPDATE_UNEXPECTED)
                signal.emit(outcome, generation)

        job = _Job()
        job.setAutoDelete(True)
        _pool().start(job)

    def install(self, release: Release, on_installed: OnInstalled) -> None:
        """Download, verify twice, hand to the installer. Off-thread; the
        answer is one sentence, or the Player quits for the installer."""
        if self.busy:
            return
        self.busy = True
        self._generation += 1
        generation = self._generation
        self._on_installed = on_installed
        signal = self._downloaded
        pubs = trusted_keys()

        self._pending_release = release

        class _Job(QRunnable):
            def run(self) -> None:
                folder: Path | None = None
                try:
                    folder = Path(tempfile.mkdtemp(prefix="wti-player-update-"))
                    path = download_installer(release, folder, pubs)
                    if not is_ours(path):
                        answer: object = strings.UPDATE_NOT_OURS
                    else:
                        answer = path
                except DownloadProblem as problem:
                    answer = str(problem)
                except Exception:
                    answer = strings.UPDATE_UNEXPECTED
                if not isinstance(answer, Path) and folder is not None:
                    shutil.rmtree(folder, ignore_errors=True)
                signal.emit(answer, generation)

        job = _Job()
        job.setAutoDelete(True)
        _pool().start(job)

    def cancel(self) -> None:
        """Drop whatever is in flight. Called when the window closes."""
        self._generation += 1
        self._on_outcome = None
        self._on_installed = None
        self.busy = False

    def _deliver(self, outcome: object, generation: int) -> None:
        if generation != self._generation:
            return
        self.busy = False
        callback, self._on_outcome = self._on_outcome, None
        if callback is not None and isinstance(outcome, Outcome):
            callback(outcome)

    def _deliver_download(self, answer: object, generation: int) -> None:
        if generation != self._generation:
            return
        self.busy = False
        callback, self._on_installed = self._on_installed, None
        if callback is None:
            return
        if isinstance(answer, Path):
            release = getattr(self, "_pending_release", None)
            args = release.args if release is not None else ()
            try:
                launch_installer(answer, args)
            except OSError:
                callback(strings.UPDATE_COULD_NOT_START)
                return
            callback(strings.UPDATE_INSTALLING)
            return
        callback(str(answer))
