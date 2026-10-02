"""The size the window opens at, when nothing was remembered.

The design size is 1180 x 720. A 1366 x 768 laptop at 125 percent scaling
gives the window about 1093 x 574 of free screen, so the design size opened
with its title bar and its right edge off the screen (audit of 8 Sep 2026,
PLAYERUX-24). The window now opens no larger than the free area, less room
for its own frame.
"""

from __future__ import annotations

#: The window's design size.
DEFAULT_WIDTH = 1180
DEFAULT_HEIGHT = 720

#: Room left for the frame the window manager draws around the window: its
#: side borders, and the title bar above it.
FRAME_WIDTH = 16
FRAME_HEIGHT = 40


def fit_size(free_width: int, free_height: int, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> tuple[int, int]:
    """``(width, height)`` no larger than the free area. A free area nobody
    reported (zero or less) leaves the size alone."""
    if free_width <= 0 or free_height <= 0:
        return width, height
    return min(width, max(1, free_width - FRAME_WIDTH)), min(height, max(1, free_height - FRAME_HEIGHT))
