"""Terminal emulation.

This is the layer that turns raw bytes into a screen. Writing it yourself is
the classic trap -- ANSI/VT100 has scroll regions, origin mode, character
sets, 256-colour and truecolour SGR, and a hundred edge cases that only show
up when you run `nano` over a flaky link. pyte already handles all of it, so
this module is just a thin, well-behaved wrapper.
"""

from __future__ import annotations

import pyte

#: DEC private mode 1 (cursor keys application mode). pyte stores private
#: modes shifted left by 5, whether or not it recognises them by name.
DECCKM = 1 << 5

#: DEC private mode 25 -- cursor visible.
DECTCEM = pyte.modes.DECTCEM


class Terminal:
    def __init__(self, cols: int = 80, rows: int = 24, scrollback: int = 5000):
        self.screen = pyte.HistoryScreen(
            max(cols, 2), max(rows, 2), history=max(scrollback, 0), ratio=0.5
        )
        self.stream = pyte.ByteStream(self.screen)
        self._scrollback = scrollback

    # -- input -------------------------------------------------------------

    def feed(self, data: bytes) -> None:
        self.stream.feed(data)

    # -- geometry ----------------------------------------------------------

    @property
    def columns(self) -> int:
        return self.screen.columns

    @property
    def lines(self) -> int:
        return self.screen.lines

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = max(cols, 2), max(rows, 2)
        if (cols, rows) != (self.screen.columns, self.screen.lines):
            self.screen.resize(rows, cols)

    # -- state queries used by the renderer --------------------------------

    @property
    def cursor(self):
        return self.screen.cursor

    @property
    def cursor_visible(self) -> bool:
        return DECTCEM in self.screen.mode

    @property
    def application_cursor_keys(self) -> bool:
        """True when the far end wants ESC O A instead of ESC [ A."""
        return DECCKM in self.screen.mode

    @property
    def buffer(self):
        return self.screen.buffer

    def line_text(self, row: int) -> str:
        """Plain text of one visible row, trailing blanks stripped."""
        line = self.screen.buffer[row]
        cols = self.screen.columns
        return "".join(line[x].data for x in range(cols)).rstrip()

    def text(self) -> str:
        return "\n".join(self.line_text(y) for y in range(self.screen.lines))

    # -- scrollback --------------------------------------------------------

    def page_up(self) -> bool:
        try:
            before = len(self.screen.history.top)
            self.screen.prev_page()
            return len(self.screen.history.top) != before
        except Exception:
            return False

    def page_down(self) -> bool:
        try:
            before = len(self.screen.history.bottom)
            self.screen.next_page()
            return len(self.screen.history.bottom) != before
        except Exception:
            return False

    @property
    def scrolled_back(self) -> bool:
        try:
            return len(self.screen.history.bottom) > 0
        except Exception:
            return False

    # -- housekeeping ------------------------------------------------------

    def reset(self) -> None:
        """Full reset -- the equivalent of typing `reset` in a wedged shell."""
        cols, rows = self.screen.columns, self.screen.lines
        self.screen.reset()
        self.screen.resize(rows, cols)

    def clear(self) -> None:
        """Clear the visible screen but keep scrollback and cursor position."""
        self.feed(b"\x1b[2J\x1b[H")
