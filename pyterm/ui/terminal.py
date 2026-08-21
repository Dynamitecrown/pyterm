"""The terminal widget: draws the pyte screen, collects keyboard/mouse input."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..emulation import Terminal
from . import keys
from .highlight import highlight_line

# --------------------------------------------------------------------------
# Palette. pyte reports colours either as a name (the 16 ANSI colours) or as
# a bare hex string for 256-colour / truecolour SGR sequences.
# --------------------------------------------------------------------------

DEFAULT_FG = "#d0d0d0"
DEFAULT_BG = "#1a1a1a"
CURSOR_COLOR = "#3ad900"
SELECTION_BG = "#3a5a80"

PALETTE = {
    "black": "#2e3436", "red": "#cc3333", "green": "#4e9a06",
    "brown": "#c4a000", "blue": "#3465a4", "magenta": "#a347ba",
    "cyan": "#06989a", "white": "#d3d7cf",
    "brightblack": "#666666", "brightred": "#ef4a4a",
    "brightgreen": "#8ae234", "brightbrown": "#fce94f",
    "brightblue": "#729fcf", "brightmagenta": "#ad7fa8",
    "brightcyan": "#34e2e2", "brightwhite": "#eeeeec",
}

#: Repaint at most this often (ms). Without throttling, a `show run` dump
#: would trigger a full repaint per network packet and the UI would crawl.
REPAINT_INTERVAL = 25


def _resolve(color: str, *, bold: bool, default: str) -> QColor:
    if color == "default":
        return QColor(default)
    if bold and color in PALETTE and not color.startswith("bright"):
        color = "bright" + color
    if color in PALETTE:
        return QColor(PALETTE[color])
    if len(color) == 6:  # pyte hands back bare hex for 256/truecolour
        return QColor("#" + color)
    return QColor(default)


class TerminalWidget(QWidget):
    """Renders a Terminal and emits the bytes the user types."""

    data_typed = Signal(bytes)
    size_changed = Signal(int, int)  # cols, rows

    def __init__(self, scrollback: int = 5000, font_family: str = "",
                 font_size: int = 11, theme: dict[str, str] | None = None,
                 syntax: str = "none", parent=None):
        super().__init__(parent)
        self.terminal = Terminal(80, 24, scrollback)
        self._syntax = syntax

        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.IBeamCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._set_font(font_family, font_size)
        self._fg = DEFAULT_FG
        self._bg = DEFAULT_BG
        self._cursor_color = CURSOR_COLOR
        self._selection_bg = SELECTION_BG
        if theme:
            self._apply_theme(theme)

        self._sel_anchor: tuple[int, int] | None = None
        self._sel_head: tuple[int, int] | None = None
        self._selecting = False

        self._last_cursor_row: int | None = None

        self._blink_on = True
        self._blink = QTimer(self)
        self._blink.timeout.connect(self._toggle_blink)
        self._blink.start(530)

        self._repaint = QTimer(self)
        self._repaint.setSingleShot(True)
        self._repaint.timeout.connect(self.update)

    # -- font / metrics ----------------------------------------------------

    def _set_font(self, family: str, size: int) -> None:
        if family:
            font = QFont(family, size)
        else:
            font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
            font.setPointSize(size)
        font.setFixedPitch(True)
        font.setStyleHint(QFont.Monospace)
        self._font = font
        self._font_bold = QFont(font)
        self._font_bold.setBold(True)

        metrics = QFontMetricsF(font)
        self._cw = max(metrics.horizontalAdvance("M"), 1.0)
        self._ch = max(metrics.height(), 1.0)
        self._baseline = metrics.ascent()

    def set_font_config(self, family: str, size: int) -> None:
        self._set_font(family, size)
        self._apply_geometry()
        self.update()

    # -- theme ---------------------------------------------------------------

    def _apply_theme(self, theme: dict[str, str]) -> None:
        self._fg = theme.get("fg", DEFAULT_FG)
        self._bg = theme.get("bg", DEFAULT_BG)
        self._cursor_color = theme.get("cursor", CURSOR_COLOR)
        self._selection_bg = theme.get("selection", SELECTION_BG)

    def set_theme(self, theme: dict[str, str]) -> None:
        self._apply_theme(theme)
        self.update()

    def set_syntax(self, syntax: str) -> None:
        self._syntax = syntax
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(int(self._cw * 80) + 4, int(self._ch * 24) + 4)

    # -- incoming data -----------------------------------------------------

    def feed(self, data: bytes) -> None:
        self.terminal.feed(data)
        self._clear_selection()

        # pyte tells us exactly which rows changed -- usually just the one
        # line being typed on. Repainting only that (plus wherever the
        # cursor was and now is) means a keystroke's echo doesn't have to
        # redraw, or re-run syntax highlighting over, the whole visible
        # scrollback on every character.
        dirty_rows = self.terminal.pop_dirty()
        cursor_row = self.terminal.cursor.y
        if self._last_cursor_row is not None:
            dirty_rows.add(self._last_cursor_row)
        dirty_rows.add(cursor_row)
        self._last_cursor_row = cursor_row

        if self._repaint.isActive():
            return  # a repaint is already queued and will pick this up too
        if dirty_rows:
            top = min(dirty_rows) * self._ch
            height = (max(dirty_rows) - min(dirty_rows) + 1) * self._ch
            self.update(QRect(0, int(top), self.width(), int(height) + 1))
        self._repaint.start(REPAINT_INTERVAL)

    def clear(self) -> None:
        self.terminal.clear()
        self.update()

    def reset(self) -> None:
        self.terminal.reset()
        self.update()

    # -- geometry ----------------------------------------------------------

    def _apply_geometry(self) -> None:
        cols = max(int(self.width() / self._cw), 2)
        rows = max(int(self.height() / self._ch), 2)
        if (cols, rows) != (self.terminal.columns, self.terminal.lines):
            self.terminal.resize(cols, rows)
            self.size_changed.emit(cols, rows)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_geometry()

    # -- painting ----------------------------------------------------------

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        if self.hasFocus():
            cur = self.terminal.cursor
            y = int(cur.y * self._ch)
            self.update(QRect(0, y, self.width(), int(self._ch) + 1))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(self._bg))

        term = self.terminal
        buffer = term.buffer
        cols, rows = term.columns, term.lines
        cw, ch = self._cw, self._ch

        first = max(int(event.rect().top() / ch), 0)
        last = min(int(event.rect().bottom() / ch) + 1, rows)
        sel = self._selection_range()

        for y in range(first, last):
            line = buffer[y]
            top = y * ch
            row_overrides: dict[int, str] = {}
            if self._syntax != "none":
                row_text = "".join(line[i].data for i in range(cols))
                row_overrides = highlight_line(row_text, self._syntax)
            x = 0
            while x < cols:
                char = line[x]
                selected = sel is not None and sel[0] <= (y * cols + x) <= sel[1]
                override = row_overrides.get(x)

                # Coalesce the run of cells sharing this style, so a full line
                # of plain text is one drawText call instead of eighty.
                run_end = x + 1
                while run_end < cols:
                    nxt = line[run_end]
                    nxt_sel = (sel is not None
                               and sel[0] <= (y * cols + run_end) <= sel[1])
                    if (nxt.fg, nxt.bg, nxt.bold, nxt.italics, nxt.underscore,
                            nxt.reverse, nxt_sel, row_overrides.get(run_end)) != (
                            char.fg, char.bg, char.bold, char.italics,
                            char.underscore, char.reverse, selected, override):
                        break
                    run_end += 1

                fg = _resolve(char.fg, bold=char.bold, default=self._fg)
                bg = _resolve(char.bg, bold=False, default=self._bg)
                if char.reverse:
                    fg, bg = bg, fg
                if override and not selected:
                    fg = QColor(override)
                if selected:
                    bg = QColor(self._selection_bg)

                rect = QRect(int(x * cw), int(top),
                             int((run_end - x) * cw) + 1, int(ch) + 1)
                if bg != QColor(self._bg):
                    painter.fillRect(rect, bg)

                text = "".join(line[i].data for i in range(x, run_end))
                if text.strip():
                    font = self._font_bold if char.bold else self._font
                    if char.italics:
                        font = QFont(font)
                        font.setItalic(True)
                    font = QFont(font)
                    font.setUnderline(char.underscore)
                    painter.setFont(font)
                    painter.setPen(fg)
                    painter.drawText(int(x * cw), int(top + self._baseline), text)

                x = run_end

        self._paint_cursor(painter)
        painter.end()

    def _paint_cursor(self, painter: QPainter) -> None:
        term = self.terminal
        if not term.cursor_visible or term.scrolled_back:
            return
        cur = term.cursor
        if not (0 <= cur.y < term.lines and 0 <= cur.x < term.columns):
            return

        rect = QRect(int(cur.x * self._cw), int(cur.y * self._ch),
                     int(self._cw) + 1, int(self._ch))
        if not self.hasFocus():
            painter.setPen(QColor(self._cursor_color))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            return
        if not self._blink_on:
            return

        painter.fillRect(rect, QColor(self._cursor_color))
        char = term.buffer[cur.y][cur.x]
        if char.data.strip():
            painter.setFont(self._font_bold if char.bold else self._font)
            painter.setPen(QColor(self._bg))
            painter.drawText(int(cur.x * self._cw),
                             int(cur.y * self._ch + self._baseline), char.data)

    # -- keyboard ----------------------------------------------------------

    def keyPressEvent(self, event):
        mods = event.modifiers()
        ctrl_shift = (mods & Qt.ControlModifier) and (mods & Qt.ShiftModifier)

        if ctrl_shift and event.key() == Qt.Key_C:
            self.copy_selection()
            return
        if ctrl_shift and event.key() == Qt.Key_V:
            self.paste()
            return

        # Shift+PgUp/PgDn scroll locally instead of going to the far end.
        if mods & Qt.ShiftModifier and event.key() in (Qt.Key_PageUp,
                                                       Qt.Key_PageDown):
            if event.key() == Qt.Key_PageUp:
                self.terminal.page_up()
            else:
                self.terminal.page_down()
            self.update()
            return

        data = keys.encode(event, self.terminal.application_cursor_keys)
        if data:
            self._blink_on = True
            self.data_typed.emit(data)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        steps = event.angleDelta().y()
        if steps == 0:
            return
        moved = False
        for _ in range(max(abs(steps) // 120, 1)):
            moved |= self.terminal.page_up() if steps > 0 else self.terminal.page_down()
        if moved:
            self.update()

    # -- mouse / selection -------------------------------------------------

    def _cell_at(self, pos) -> tuple[int, int]:
        col = min(max(int(pos.x() / self._cw), 0), self.terminal.columns - 1)
        row = min(max(int(pos.y() / self._ch), 0), self.terminal.lines - 1)
        return row, col

    def _selection_range(self) -> tuple[int, int] | None:
        if self._sel_anchor is None or self._sel_head is None:
            return None
        cols = self.terminal.columns
        a = self._sel_anchor[0] * cols + self._sel_anchor[1]
        b = self._sel_head[0] * cols + self._sel_head[1]
        return (a, b) if a <= b else (b, a)

    def _clear_selection(self) -> None:
        if self._sel_anchor is not None:
            self._sel_anchor = self._sel_head = None
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.paste()  # PuTTY habit: right-click pastes
            return
        if event.button() == Qt.LeftButton:
            self._selecting = True
            self._sel_anchor = self._sel_head = self._cell_at(event.position())
            self.update()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._sel_head = self._cell_at(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            self._sel_head = self._cell_at(event.position())
            if self._sel_anchor == self._sel_head:
                self._sel_anchor = self._sel_head = None
            else:
                self.copy_selection()  # PuTTY habit: selecting copies
            self.update()

    def mouseDoubleClickEvent(self, event):
        """Double-click selects the whole line."""
        row, _ = self._cell_at(event.position())
        self._sel_anchor = (row, 0)
        self._sel_head = (row, self.terminal.columns - 1)
        self.copy_selection()
        self.update()

    # -- clipboard ---------------------------------------------------------

    def selected_text(self) -> str:
        sel = self._selection_range()
        if sel is None:
            return ""
        cols = self.terminal.columns
        start, end = sel
        lines = []
        for y in range(start // cols, end // cols + 1):
            lo = start - y * cols if y == start // cols else 0
            hi = end - y * cols if y == end // cols else cols - 1
            line = self.terminal.buffer[y]
            lines.append("".join(line[x].data
                                 for x in range(lo, hi + 1)).rstrip())
        return "\n".join(lines)

    def copy_selection(self) -> None:
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    def paste(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            # Normalise line endings; terminals want CR, not CRLF.
            self.data_typed.emit(
                text.replace("\r\n", "\r").replace("\n", "\r").encode("utf-8")
            )

    def select_all(self) -> None:
        self._sel_anchor = (0, 0)
        self._sel_head = (self.terminal.lines - 1, self.terminal.columns - 1)
        self.update()

    # -- focus -------------------------------------------------------------

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._blink_on = True
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()
