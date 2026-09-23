"""
Small, reusable Qt building blocks shared across the Control Panel --
factored out of what used to be editor_window.py/settings_window.py when
those two windows merged into one (2026-09-17, owner's request: "single
window for editing/settings"). No app-specific state lives here, only
generic widget behavior, so each piece is independently testable.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsView,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import theme


class _ScrollSafeSpinBoxMixin:
    """Requires the field to already have keyboard focus (a prior click)
    before the mouse wheel changes its value. Without this, Qt's default
    QAbstractSpinBox wheelEvent fires on *hover* alone -- scrolling a
    long, scrollable panel while the cursor happens to be resting over a
    spinbox silently changes a setting instead of scrolling past it
    (owner's report, 2026-09-16: "it's easy to miss and change a setting
    you didn't want to").

    `set_locked(True)` is a second, stronger guarantee on top of that,
    for a field the owner wants to make it hard to bump even
    deliberately: it blocks every value-changing interaction -- wheel,
    arrow keys, the spin buttons, and typing a new value and pressing
    Enter -- regardless of focus. stepBy() is what wheel/arrow-keys/
    spin-buttons all funnel through in Qt, so guarding it alone covers
    all three; typing a value in directly bypasses stepBy entirely (it
    goes through interpretText()/setValue()), which is why setReadOnly()
    is also needed to block that path.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._locked = False

    def is_locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setReadOnly(locked)
        self.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons
            if locked
            else QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )

    def stepBy(self, steps: int) -> None:  # noqa: N802 (Qt override)
        if self._locked:
            return
        super().stepBy(steps)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class ScrollSafeSpinBox(_ScrollSafeSpinBoxMixin, QSpinBox):
    pass


class ScrollSafeDoubleSpinBox(_ScrollSafeSpinBoxMixin, QDoubleSpinBox):
    pass


def elide_path_middle(path: str, font_metrics, max_width: int) -> str:
    """Shortens `path` to fit `max_width` pixels by trimming characters
    out of the *directory* portion only, always keeping the filename
    itself fully intact -- e.g. "/home/jj/.../recording-final.mp3", not
    Qt's own Qt.TextElideMode.ElideMiddle (which elides by raw character
    position and can chew into the filename itself for a long one).
    Owner's request, 2026-09-17: "make sure file name is chopped from
    the middle if too long (/x/y/.../file.mp3)"."""
    if font_metrics.horizontalAdvance(path) <= max_width:
        return path
    name = Path(path).name
    parent = str(Path(path).parent)
    ellipsis = "…"
    for head_len in range(len(parent), -1, -1):
        head = parent[:head_len]
        candidate = f"{head}{ellipsis}/{name}" if head else f"{ellipsis}/{name}"
        if font_metrics.horizontalAdvance(candidate) <= max_width:
            return candidate
    return f"{ellipsis}/{name}"


class CollapsibleSection(QWidget):
    """A titled section with a clickable header that shows/hides its
    body -- added 2026-09-17 for the merged Control Panel window (owner's
    request: "each section of the editor should be resizable and
    collapsible"). Resizing is handled by whatever QSplitter this is
    placed in (a collapsed section just cedes its space to its splitter
    siblings); this widget only owns the collapse/expand half.

    `body_layout` is the QVBoxLayout callers add their own content to.

    `collapsed_changed` fires on every real state change, regardless of
    whether it came from a user click or a programmatic `set_collapsed()`
    call -- unlike the header QPushButton's own `toggled`, which
    `set_collapsed()` deliberately blocks to avoid a spurious emission
    when restoring persisted state (see its own docstring). A caller that
    needs to react to *every* change, e.g. a QSplitter resync, needs this
    one instead.

    `wants_extra_space` (owner's report, 2026-09-19: a gap between two
    small expanded sections "disappears when layers is also open") marks
    a section as having something inside that should actually grow into
    extra room -- an auto-expanding list widget, so far. Everything else
    defaults to False: control_panel_window.py's _resync_tab_splitter_
    sizes caps those to their own real content height instead of letting
    them request QWIDGETSIZE_MAX, so a splitter with nothing that wants
    the leftover space doesn't split it between sections that don't need
    it either -- it collects harmlessly below the last one instead.
    """

    collapsed_changed = Signal(bool)

    def __init__(
        self, title: str, collapsed: bool = False, parent=None, wants_extra_space: bool = False
    ) -> None:
        super().__init__(parent)
        self._title = title
        self.wants_extra_space = wants_extra_space
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QPushButton()
        self._header.setCheckable(True)
        self._header.setObjectName("CollapsibleSectionHeader")
        self._header.toggled.connect(self._on_toggled)
        outer.addWidget(self._header)

        self._body = QWidget()
        self.body_layout = QVBoxLayout(self._body)
        outer.addWidget(self._body)

        self.set_collapsed(collapsed)

    @property
    def title(self) -> str:
        return self._title

    def is_collapsed(self) -> bool:
        return self._header.isChecked()

    def set_collapsed(self, collapsed: bool) -> None:
        self._header.blockSignals(True)
        self._header.setChecked(collapsed)
        self._header.blockSignals(False)
        self._apply_collapsed_state(collapsed)

    def _on_toggled(self, checked: bool) -> None:
        self._apply_collapsed_state(checked)

    def _apply_collapsed_state(self, collapsed: bool) -> None:
        self._body.setVisible(not collapsed)
        arrow = "▸" if collapsed else "▾"  # ▸ / ▾
        # "&&", not "&": QPushButton.setText() treats a single "&" as a
        # mnemonic marker (consumed, underlining the next letter) --
        # found via a real screenshot, 2026-09-17: "Position & Hierarchy"
        # rendered as "Position_Hierarchy". "&&" is Qt's own escape for a
        # literal ampersand.
        escaped_title = self._title.replace("&", "&&")
        self._header.setText(f"{arrow}  {escaped_title}")
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum if collapsed else QSizePolicy.Policy.Preferred,
        )
        self.collapsed_changed.emit(collapsed)


class PreviewView(QGraphicsView):
    """A second, read-only view onto another QGraphicsScene -- Qt keeps
    every view attached to a scene in sync automatically, so there's no
    manual redraw/pixel-copy loop here; whatever repaints the source
    scene's own view repaints this one too, for free."""

    def __init__(self, scene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setInteractive(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # The mirrored scene is render_window.scene, whose own background
        # mode is usually "transparent" (NoBrush) -- correct for the real
        # Render Window (OBS needs to see through it) but not for this
        # in-UI mirror, which just fell through to the viewport's native
        # (white) palette color with nothing else painting over it. This
        # view's own backgroundBrush overrides that, independent of the
        # scene's, without touching the real window's transparency at
        # all. Bug found 2026-09-17, owner's report: "the white
        # background in the settings section" -- this was the Live
        # Preview canvas specifically, not settings fields.
        self.setBackgroundBrush(QColor(theme.INK_850))

    def refit(self) -> None:
        if not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self.refit()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self.refit()


class LevelMeter(QWidget):
    """A live, painted level bar plus the current audio-to-frame latency,
    for tuning the thresholds without guessing (Phase 2 Milestone
    request, 2026-09-16 -- owner: "fighting responsiveness... show it").

    Reads `config.audio` directly at paint time, so the threshold marks
    never go stale as they're tuned in the very same window, and polls
    `render_window`'s plain `current_envelope`/`measured_latency_ms`/
    `talk_level` attributes via its own QTimer (same "read the live
    object directly" pattern PreviewView uses for its scene, rather than
    a signal per audio sample -- this only needs to look right at
    ~20fps, not react to every single one)."""

    def __init__(self, config, render_window) -> None:
        super().__init__()
        self.config = config
        self.render_window = render_window
        self.setMinimumHeight(64)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(50)  # 20Hz -- a diagnostic meter, not the render loop

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        audio = self.config.audio
        envelope = getattr(self.render_window, "current_envelope", 0.0) or 0.0
        latency_ms = getattr(self.render_window, "measured_latency_ms", 0.0) or 0.0
        talk_level = getattr(self.render_window, "talk_level", 0) or 0
        muted = getattr(self.render_window, "muted", False)

        rect = self.rect()
        bar_rect = QRectF(4, 4, rect.width() - 8, rect.height() - 26)
        max_scale = max(audio.wide_open * 1.5, envelope, 0.01)

        def x_for(value: float) -> float:
            fraction = min(max(value / max_scale, 0.0), 1.0)
            return bar_rect.left() + fraction * bar_rect.width()

        painter.fillRect(bar_rect, QColor(theme.INK_800))
        painter.setPen(QPen(QColor(theme.INK_500)))
        painter.drawRect(bar_rect)

        level_color = QColor(theme.MAGENTA_500 if muted else theme.CYAN_500)
        level_width = x_for(envelope) - bar_rect.left()
        painter.fillRect(
            QRectF(bar_rect.left(), bar_rect.top(), level_width, bar_rect.height()),
            level_color,
        )

        marks = [
            (audio.noise_gate, theme.GREY_500, Qt.PenStyle.DotLine),
            (audio.mild_open, theme.VIOLET_500, Qt.PenStyle.SolidLine),
            (audio.mild_close, theme.VIOLET_500, Qt.PenStyle.DashLine),
            (audio.wide_open, theme.MAGENTA_500, Qt.PenStyle.SolidLine),
            (audio.wide_close, theme.MAGENTA_500, Qt.PenStyle.DashLine),
        ]
        for value, color, style in marks:
            x = x_for(value)
            pen = QPen(QColor(color))
            pen.setWidth(2)
            pen.setStyle(style)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, bar_rect.top() - 2), QPointF(x, bar_rect.bottom() + 2))

        painter.setPen(QPen(QColor(theme.PINK_WHITE)))
        state = "muted" if muted else f"talk={talk_level}"
        text = f"Level {envelope:.4f}   {state}   Audio→frame latency: {latency_ms:.1f} ms"
        painter.drawText(
            QRectF(4, bar_rect.bottom() + 2, rect.width() - 8, 18),
            Qt.AlignmentFlag.AlignLeft,
            text,
        )


def format_playback_time(seconds: float) -> str:
    """"m:ss", for the file-playback timeline's clock -- no hours field:
    this app's own use case (a participant's isolated audio track for a
    recording session) is never going to run anywhere near an hour, and
    minutes simply run past 59 for the rare file that does, same as most
    simple players do rather than growing a conditional h:mm:ss format
    for a case that doesn't come up here."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


class FileTimelineWidget(QWidget):
    """A clickable/draggable file-playback timeline with a "m:ss / m:ss"
    clock -- owner's request, 2026-09-23: "a clickable timeline bar for
    when playing from a file with a time/total clock by it." Reads
    nothing live on its own (unlike LevelMeter's QTimer poll of
    render_window) -- position/duration only change when AudioManager
    says so (audio.FilePlayback's on_position/on_duration), so
    control_panel_window.py just calls set_position/set_duration
    whenever AudioManager.position_measured/duration_measured fire,
    rather than polling.

    Duration of 0 (nothing has ever played, or the file's total couldn't
    be probed -- see audio.probe_duration) means "nothing to seek yet":
    mouse interaction is a no-op and the clock reads "m:ss / --:--".

    Click-and-drag scrubbing previews locally (the bar/clock move
    immediately, so dragging feels responsive) without spamming
    seek_requested -- and, symmetrically, ignores incoming set_position
    calls while a drag is in progress, so the actually-still-playing old
    position doesn't fight the drag the owner is mid-gesture on. The
    real seek (which restarts ffmpeg decoding -- not something to fire on
    every mouse-move pixel) only fires once, on release.
    """

    seek_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.position_s = 0.0
        self.duration_s = 0.0
        self._dragging = False
        self.setMinimumHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_position(self, seconds: float) -> None:
        if self._dragging:
            return  # the user's own drag is the source of truth right now
        self.position_s = max(0.0, seconds)
        self.update()

    def set_duration(self, seconds: float) -> None:
        self.duration_s = max(0.0, seconds)
        self.update()

    def _bar_rect(self) -> QRectF:
        rect = self.rect()
        clock_width = 96  # room for "m:ss / m:ss" at this widget's font size
        return QRectF(4, 4, max(0, rect.width() - 8 - clock_width), rect.height() - 8)

    def _seek_from_x(self, x: float) -> None:
        bar_rect = self._bar_rect()
        if self.duration_s <= 0 or bar_rect.width() <= 0:
            return
        fraction = min(max((x - bar_rect.left()) / bar_rect.width(), 0.0), 1.0)
        self.position_s = fraction * self.duration_s
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if event.button() != Qt.MouseButton.LeftButton or self.duration_s <= 0:
            return
        self._dragging = True
        self._seek_from_x(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if not self._dragging:
            return
        self._seek_from_x(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if not self._dragging:
            return
        self._dragging = False
        self.seek_requested.emit(self.position_s)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar_rect = self._bar_rect()
        painter.fillRect(bar_rect, QColor(theme.INK_800))
        painter.setPen(QPen(QColor(theme.INK_500)))
        painter.drawRect(bar_rect)

        if self.duration_s > 0 and bar_rect.width() > 0:
            fraction = min(max(self.position_s / self.duration_s, 0.0), 1.0)
            filled_width = fraction * bar_rect.width()
            painter.fillRect(
                QRectF(bar_rect.left(), bar_rect.top(), filled_width, bar_rect.height()),
                QColor(theme.CYAN_500),
            )

        painter.setPen(QPen(QColor(theme.PINK_WHITE)))
        total_text = format_playback_time(self.duration_s) if self.duration_s > 0 else "--:--"
        clock_text = f"{format_playback_time(self.position_s)} / {total_text}"
        painter.drawText(
            QRectF(bar_rect.right() + 8, 0, self.width() - bar_rect.right() - 12, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            clock_text,
        )
