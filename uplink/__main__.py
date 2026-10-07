"""Start the terminal:  python -m uplink"""
import sys

from . import updater
from .app import Uplink


def main() -> int:
    app = Uplink(after_update="--after-update" in sys.argv)
    result = app.run()
    if result == "restart":
        updater.restart()          # replaces this process
    # a crash gives a non-zero code, so the launcher knows to restart instead of dropping to a shell
    return app.return_code or 0


if __name__ == "__main__":
    sys.exit(main())
