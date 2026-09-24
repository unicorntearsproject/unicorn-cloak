"""
Unicorn Cloak's v2 look: the Unicorn Tears/Viz neon-rave design system
(`/home/jj/projects/unicorn-tears/claude-design-system`), ported from its
web CSS custom-property tokens to a Qt stylesheet plus bundled fonts --
there's no web engine here to consume the original `tokens/*.css` files
directly, so the color/type/radius values below are hand-copied from
them, not derived automatically. Keep them in sync by eye if the source
tokens ever change.

Applied once, globally, in `__main__.py` via `apply(app)`. The two
control-panel windows (`ControlPanelWindow`, `HelpWindow`) each need one
line of explicit opt-in -- `ControlPanelWindow` sets `WA_StyledBackground`
+ `setObjectName("ControlPanelWindow")`; `HelpWindow` sets only
`setObjectName("HelpWindow")`, since QDialog already paints its
stylesheet background natively. Every
*control* inside those windows (QPushButton, QGroupBox, QSpinBox, ...)
then picks up its styling automatically via Qt's stylesheet cascade, with
no further per-widget work.

**The Render Window is deliberately excluded.** It must stay exactly as
transparent/frameless as OBS needs it, so every selector below targets a
concrete control class or an explicit objectName -- never a blanket
`QWidget` rule -- and render.py never opts its own QWidget into
`Qt.WA_StyledBackground`, which is what would be required for a
stylesheet background to paint on a plain QWidget subclass in the first
place. Belt and suspenders, not just one of them.

**A blanket `QDialog` selector is still avoided.** An earlier version of
this stylesheet used one, which would have styled every dialog in the
app -- including any the app doesn't fully own -- with no guarantee its
internal widgets (arbitrary third-party or OS-native chrome) are all
covered. `QDialog#HelpWindow` stays scoped to the one QDialog subclass
this app actually owns.

**`QMessageBox`/`QInputDialog`/`QFileDialog` get explicit, type-scoped
rules instead** (not a blanket `QDialog`), added 2026-09-17 after the
owner reported invisible dialog text on their real (light-palette) GNOME
session: an application-wide stylesheet's descendant selectors match by
Qt's parent-child *ownership* tree, not the visual/layout tree, so the
blanket `QLabel`/`QPushButton`/etc. rules below were already leaking into
every one of these dialogs regardless -- they just had no matching
background of their own, so light-on-light text was the result on a
light desktop theme (this app's own dev/offscreen environment happens to
default dark, which is why it wasn't caught here first). `QFileDialog`
(the Add/Replace/Save/Load/Export pickers) gets the fullest treatment:
its own background plus its internal `QLineEdit`/`QListView`/
`QTreeView`/`QHeaderView` -- true embedded child widgets, not a separate
top-level window, so ordinary descendant selectors reach them -- since a
background-only fix would have left the file list looking half-themed.
`QT_QPA_PLATFORMTHEME` isn't set on this machine, so there's no reliable
guarantee Qt hands these off to a native/portal picker instead of its own
built-in implementation; verified live that it doesn't (the "Look in:"/
"File name:"/"Files of type:" labels are Qt's own non-native dialog).

Font substitution note carried over unchanged from the design system's
own `tokens/fonts.css`: the real "Unicorn Tears" wordmark is hand-painted
brush lettering with no font file provided; Anton is *their* documented
stand-in for display type, used here the same way, not invented for this
app. The three families (Anton, Space Grotesk, JetBrains Mono) aren't
installed on this machine, so `assets/fonts/*.ttf` bundles them directly
(downloaded from Google Fonts' static CDN, the same source the design
system's own `tokens/fonts.css` `@import` points at) rather than relying
on a system that may not have them.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

# ---- Color tokens (hand-copied from tokens/colors.css) --------------
INK_900 = "#07060d"  # page base
INK_850 = "#0c0a16"  # raised base
INK_800 = "#120c1f"  # card surface
INK_700 = "#1b1230"  # card surface, elevated
INK_600 = "#261a42"  # hover surface
INK_500 = "#342357"  # borders / strokes

MAGENTA_500 = "#ff2bd6"  # primary accent -- "tears" pink
MAGENTA_600 = "#e60bb8"
CYAN_500 = "#19e3ff"  # secondary accent / focus ring
VIOLET_500 = "#9d4eff"  # tertiary accent

WHITE = "#ffffff"
PINK_WHITE = "#ffeffb"  # body text on dark
GREY_500 = "#6d6088"  # disabled / placeholder
DANGER = "#ff4d6d"

FONT_SANS = "'Space Grotesk'"  # UI/body, see tokens/typography.css
FONT_DISPLAY = "'Anton'"  # headings/kickers only -- illegible at body sizes
FONT_MONO = "'JetBrains Mono'"  # code/hotkey text

RADIUS_SM = "8px"  # tokens/spacing.css --radius-sm
RADIUS_MD = "14px"  # tokens/spacing.css --radius-md


def load_fonts() -> None:
    """Registers the bundled brand fonts with Qt's font database. Safe to
    call more than once (e.g. across tests that each build their own
    QApplication) -- Qt just re-registers the same families."""
    for path in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def stylesheet() -> str:
    # QMessageBox/QInputDialog/QFileDialog get explicit rules further down
    # (not a blanket QDialog rule -- that's still avoided, see the test)
    # because of a real bug found 2026-09-17: the QLabel rule below
    # already applies inside all three regardless -- verified empirically
    # that an *application-wide* stylesheet's descendant selectors
    # (`#Foo QLabel`) match by Qt's parent-child *ownership* tree, not
    # the embedded-widget/layout tree, so a QMessageBox constructed as
    # `QMessageBox.warning(self, ...)` (parented to ControlPanelWindow
    # for lifetime management, but a genuinely separate top-level
    # window) still gets the light label text -- scoping the QLabel rule
    # to `#ControlPanelWindow QLabel` would NOT have stopped that leak,
    # only giving the dialog itself a matching dark background does.
    # Without this, the label text was light-on-native-light-background
    # on a light desktop theme -- readable in this app's own dev
    # environment (whose native palette happens to be dark already) but
    # invisible on the owner's actual GNOME session, which is exactly
    # what was reported. QFileDialog got the same treatment plus its
    # internal QLineEdit/QListView/QTreeView/QHeaderView -- true embedded
    # children of the dialog itself, not a separate top-level window, so
    # ordinary descendant selectors (`QFileDialog QListView`) reach them
    # directly, no ownership-tree caveat needed there.
    return f"""
    QWidget#ControlPanelWindow, QDialog#HelpWindow, QDialog#IssuesDialog {{
        background-color: {INK_900};
        color: {PINK_WHITE};
        font-family: {FONT_SANS};
        font-size: 13px;
    }}
    QLabel {{
        color: {PINK_WHITE};
        background: transparent;
        font-family: {FONT_SANS};
    }}
    QGroupBox {{
        border: 1px solid {INK_500};
        border-radius: {RADIUS_MD};
        margin-top: 14px;
        padding-top: 10px;
        background-color: {INK_800};
        font-family: {FONT_SANS};
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: {MAGENTA_500};
        font-family: {FONT_DISPLAY};
        font-size: 14px;
    }}
    QLabel#BehaviorHeader {{
        color: {MAGENTA_500};
        font-family: {FONT_DISPLAY};
        font-size: 13px;
        font-weight: 600;
        padding: 2px 0 6px 0;
    }}
    QPushButton#CollapsibleSectionHeader {{
        background-color: {INK_700};
        color: {MAGENTA_500};
        border: 1px solid {INK_500};
        border-radius: {RADIUS_SM};
        padding: 6px 10px;
        text-align: left;
        font-family: {FONT_DISPLAY};
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton#CollapsibleSectionHeader:hover {{
        border-color: {MAGENTA_500};
    }}
    QPushButton#CollapsibleSectionHeader:checked {{
        background-color: {INK_700};
        color: {MAGENTA_500};
        border-color: {INK_500};
    }}
    QPushButton {{
        background-color: {INK_700};
        color: {WHITE};
        border: 1px solid {INK_500};
        border-radius: {RADIUS_SM};
        padding: 5px 12px;
        font-family: {FONT_SANS};
    }}
    QPushButton:hover {{
        border-color: {MAGENTA_500};
        color: {MAGENTA_500};
    }}
    QPushButton:pressed {{
        background-color: {INK_600};
    }}
    QPushButton:checked {{
        background-color: {MAGENTA_600};
        border-color: {MAGENTA_500};
        color: {WHITE};
    }}
    QPushButton:disabled {{
        color: {GREY_500};
        border-color: {INK_600};
    }}
    QToolButton {{
        padding: 2px;
        border: 1px solid transparent;
        border-radius: 4px;
        background: transparent;
    }}
    QToolButton:hover {{
        border-color: {CYAN_500};
        background-color: {INK_700};
    }}
    QCheckBox {{
        color: {PINK_WHITE};
        font-family: {FONT_SANS};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {INK_500};
        border-radius: 4px;
        background: {INK_800};
    }}
    QCheckBox::indicator:checked {{
        background-color: {MAGENTA_500};
        border-color: {MAGENTA_500};
    }}
    QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit, QLineEdit {{
        background-color: {INK_800};
        color: {WHITE};
        border: 1px solid {INK_500};
        border-radius: {RADIUS_SM};
        padding: 3px 6px;
        font-family: {FONT_SANS};
    }}
    QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus, QLineEdit:focus {{
        border: 1px solid {CYAN_500};
    }}
    QSpinBox:read-only, QDoubleSpinBox:read-only {{
        color: {GREY_500};
        background-color: {INK_850};
    }}
    QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        color: {GREY_500};
        background-color: {INK_850};
        border-color: {INK_600};
    }}
    QComboBox::drop-down {{
        border: none;
    }}
    QComboBox QAbstractItemView {{
        background-color: {INK_800};
        color: {WHITE};
        selection-background-color: {MAGENTA_600};
        border: 1px solid {INK_500};
    }}
    QListWidget {{
        background-color: {INK_800};
        color: {PINK_WHITE};
        border: 1px solid {INK_500};
        border-radius: {RADIUS_SM};
        font-family: {FONT_SANS};
    }}
    QListWidget::item:selected {{
        background-color: {MAGENTA_600};
        color: {WHITE};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QSplitter {{
        background: transparent;
    }}
    QSplitter::handle {{
        background-color: {INK_500};
    }}
    QSplitter::handle:hover {{
        background-color: {VIOLET_500};
    }}
    QSplitter::handle:horizontal {{
        width: 4px;
    }}
    QSplitter::handle:vertical {{
        height: 4px;
    }}
    QTabWidget::pane {{
        background: transparent;
        border: 1px solid {INK_500};
        border-radius: {RADIUS_MD};
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: {INK_700};
        color: {PINK_WHITE};
        border: 1px solid {INK_500};
        border-bottom: none;
        border-top-left-radius: {RADIUS_SM};
        border-top-right-radius: {RADIUS_SM};
        padding: 6px 14px;
        margin-right: 2px;
        font-family: {FONT_SANS};
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background-color: {INK_800};
        color: {MAGENTA_500};
        border-color: {MAGENTA_500};
    }}
    QTabBar::tab:!selected:hover {{
        color: {MAGENTA_500};
    }}
    QScrollBar:vertical {{
        background: {INK_800};
        width: 12px;
        border-radius: 6px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {INK_500};
        border-radius: 6px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {VIOLET_500};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QTextBrowser {{
        background-color: {INK_800};
        color: {PINK_WHITE};
        border: 1px solid {INK_500};
        border-radius: {RADIUS_MD};
        font-family: {FONT_SANS};
    }}
    QToolTip {{
        background-color: {INK_700};
        color: {WHITE};
        border: 1px solid {MAGENTA_500};
        padding: 4px 6px;
        font-family: {FONT_SANS};
    }}
    QMessageBox, QInputDialog {{
        background-color: {INK_900};
    }}
    QFileDialog {{
        background-color: {INK_900};
        color: {PINK_WHITE};
        font-family: {FONT_SANS};
    }}
    QFileDialog QLineEdit {{
        background-color: {INK_800};
        color: {WHITE};
        border: 1px solid {INK_500};
        border-radius: {RADIUS_SM};
        padding: 3px 6px;
        font-family: {FONT_SANS};
    }}
    QFileDialog QLineEdit:focus {{
        border: 1px solid {CYAN_500};
    }}
    QFileDialog QListView, QFileDialog QTreeView {{
        background-color: {INK_800};
        color: {PINK_WHITE};
        border: 1px solid {INK_500};
        border-radius: {RADIUS_SM};
        font-family: {FONT_SANS};
    }}
    QFileDialog QListView::item:selected, QFileDialog QTreeView::item:selected {{
        background-color: {MAGENTA_600};
        color: {WHITE};
    }}
    QFileDialog QHeaderView {{
        background-color: {INK_700};
    }}
    QFileDialog QHeaderView::section {{
        background-color: {INK_700};
        color: {PINK_WHITE};
        border: 1px solid {INK_500};
        padding: 4px 6px;
        font-family: {FONT_SANS};
    }}
    """


def apply(app: QApplication) -> None:
    load_fonts()
    app.setStyleSheet(stylesheet())
