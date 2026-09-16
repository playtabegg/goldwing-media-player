r"""Run the Player from a source checkout.

    python Player.pyw
    python Player.pyw "D:\"                 open a drive straight away
    python Player.pyw --no-hardware-decoding

Same entry point the frozen dist\Player.exe uses.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wti_player.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
