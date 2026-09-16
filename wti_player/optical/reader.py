"""Read a disc without freezing the window.

Working out what a disc is means touching an optical drive, and an optical
drive takes its time: it spins up, it seeks, and on a scratched disc it
retries for seconds at a stretch. Doing that on the interface's thread is how
a player ends up not repainting while somebody wonders whether it has crashed.

So identification happens on a worker and comes back as a signal. The seam is
:class:`DiscReader`, with a threaded one for the Player and an immediate one
for tests, which is the same shape the drive scanner and the playback engine
already use.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .identify import DiscKind, DiscProfile, identify

log = logging.getLogger(__name__)

#: What a reader hands back when it is done.
OnRead = Callable[[DiscProfile], None]
#: Any piece of disc work that must not run on the interface's thread, and
#: what to do with its answer. ``None`` is the answer when the work raised.
Work = Callable[[], Any]
OnDone = Callable[[Any], None]


class DiscReader(Protocol):
    """Anything that can work out what a disc is, or read something off one."""

    def read(self, path: Path, label: str, done: OnRead) -> None:
        """Identify ``path`` and call ``done`` with the answer."""
        ...

    def run(self, label: str, work: Work, done: OnDone) -> None:
        """Do ``work`` off the interface's thread and hand ``done`` its answer.

        Reading a DVD's menu off a drive is the case this exists for:
        seconds on a warm cache, twenty off a disc, and it used to run on
        the thread that paints the window (28 Aug 2026).
        """
        ...

    def cancel(self) -> None:
        """Forget any read in flight — its answer will not be delivered."""
        ...


class ImmediateReader:
    """Reads on the spot. What tests use, and what a fixture folder deserves."""

    def __init__(self) -> None:
        self.cancelled = False

    def read(self, path: Path, label: str, done: OnRead) -> None:
        self.cancelled = False
        done(identify(path, label=label))

    def run(self, label: str, work: Work, done: OnDone) -> None:
        self.cancelled = False
        try:
            answer = work()
        except Exception:
            log.exception("%s failed", label)
            answer = None
        done(answer)

    def cancel(self) -> None:
        self.cancelled = True


class ThreadedReader:
    """Reads on a worker thread and answers on the interface's.

    Only the most recent read is delivered. Swap a disc quickly and the first
    one's answer is dropped rather than fighting the second for the window.
    """

    def __init__(self) -> None:
        from PyQt6.QtCore import QObject, pyqtSignal

        class _Bridge(QObject):
            done = pyqtSignal(object, int)
            ran = pyqtSignal(object, int)

        self._bridge = _Bridge()
        self._bridge.done.connect(self._deliver)
        self._bridge.ran.connect(self._deliver_run)
        # Two lanes. A disc read and a menu read are different questions
        # with different lifetimes; one counter for both meant a drive poll
        # starting a disc read silently dropped the menu read in flight and
        # left the window pinned on "Reading the menu" (review, 28 Aug 2026).
        self._generation = 0
        self._pending: dict[int, OnRead] = {}
        self._run_generation = 0
        self._run_pending: dict[int, OnDone] = {}

    def read(self, path: Path, label: str, done: OnRead) -> None:
        def identify_or_say_why() -> DiscProfile:
            try:
                return identify(path, label=label)
            except Exception:
                return DiscProfile(
                    kind=DiscKind.UNREADABLE,
                    root=path,
                    label=label,
                    problem="This disc could not be read.",
                )

        self._generation += 1
        generation = self._generation
        self._pending[generation] = done
        self._start(label, identify_or_say_why, self._bridge.done, generation)

    def run(self, label: str, work: Work, done: OnDone) -> None:
        self._run_generation += 1
        generation = self._run_generation
        self._run_pending[generation] = done
        self._start(label, work, self._bridge.ran, generation)

    def _start(self, label: str, work: Work, signal: Any, generation: int) -> None:
        from PyQt6.QtCore import QRunnable, QThreadPool

        class _Job(QRunnable):
            def run(self) -> None:
                try:
                    answer = work()
                except Exception:
                    log.exception("%s failed", label)
                    answer = None
                signal.emit(answer, generation)

        job = _Job()
        job.setAutoDelete(True)
        QThreadPool.globalInstance().start(job)

    def cancel(self) -> None:
        self._pending.clear()
        self._run_pending.clear()

    def _deliver(self, answer: Any, generation: int) -> None:
        callback = self._pending.pop(generation, None)
        # Anything older than the newest read is stale; a disc that has been
        # swapped should not have its predecessor's answer arrive on top.
        if callback is not None and generation == self._generation:
            callback(answer)

    def _deliver_run(self, answer: Any, generation: int) -> None:
        callback = self._run_pending.pop(generation, None)
        if callback is not None and generation == self._run_generation:
            callback(answer)
