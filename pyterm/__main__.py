"""Entry point: python -m pyterm"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PyTerm")
    app.setOrganizationName("PyTerm")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
