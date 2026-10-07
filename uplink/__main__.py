"""Start the terminal:  python -m uplink"""
import sys

from . import updater
from .app import Uplink


def main() -> int:
    app = Uplink(after_update="--after-update" in sys.argv)
    result = app.run()
    if result == "restart":
        updater.restart()          # replaces this process
    return 0


if __name__ == "__main__":
    sys.exit(main())
