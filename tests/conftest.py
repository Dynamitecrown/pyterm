"""Shared test fixtures.

Qt needs a platform plugin even in CI where there is no display, so we force
the offscreen backend before PySide6 is imported anywhere.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session -- Qt allows only one."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
