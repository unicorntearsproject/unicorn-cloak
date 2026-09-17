from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase

from unicorn_cloak import theme
from unicorn_cloak.config import Config
from unicorn_cloak.control_panel_window import ControlPanelWindow
from unicorn_cloak.help_window import HelpWindow
from unicorn_cloak.render import RenderWindow

from qt_helpers import make_test_rig


def test_load_fonts_registers_the_bundled_families(qapp):
    theme.load_fonts()
    families = set(QFontDatabase.families())
    assert {"Anton", "Space Grotesk", "JetBrains Mono"} <= families


def test_stylesheet_never_uses_a_blanket_qwidget_selector():
    # A bare "QWidget {" rule would paint a background on every QWidget
    # in the app, including render.py's RenderWindow -- which must stay
    # exactly as transparent as OBS needs it (see theme.py's module
    # docstring). Every rule here must target a concrete class or an
    # explicit objectName instead.
    css = theme.stylesheet()
    assert "QWidget {" not in css
    assert "QWidget{" not in css


def test_stylesheet_never_uses_a_blanket_qdialog_selector():
    # Regression 2026-09-16, found in review: an earlier version used a
    # bare "QDialog" selector, which would style every QDialog in the
    # app, with no guarantee every dialog's internal widgets are all
    # covered. Only HelpWindow, the one QDialog subclass this app
    # actually owns, should be targeted that broadly; QMessageBox,
    # QInputDialog and QFileDialog get their own type-scoped rules
    # instead (see the tests below).
    css = theme.stylesheet()
    assert "QDialog {" not in css
    assert "QDialog{" not in css
    assert "QDialog#HelpWindow" in css


def test_stylesheet_gives_messagebox_and_inputdialog_a_dark_background():
    # Regression 2026-09-17, reported by the owner: quit/save confirmation
    # text was invisible on their real (light-palette) GNOME session.
    # Root cause: the blanket QLabel rule above leaks into any
    # QMessageBox/QInputDialog parented to a themed window (Qt's
    # stylesheet cascade matches descendant selectors by parent-child
    # ownership, not layout embedding), giving them light text with no
    # matching dark background of their own.
    css = theme.stylesheet()
    assert "QMessageBox" in css
    assert "QInputDialog" in css


def test_stylesheet_fully_themes_qfiledialog():
    # Follow-up to the above, same day, owner's request ("yep, fix the
    # thing please"): QFileDialog has the identical text-color leak, but
    # a background-only fix would have left its file list/tree view
    # looking native (light) inside a dark dialog -- half-themed rather
    # than fixed. Its internal views are true embedded child widgets (not
    # a separate top-level window), so ordinary descendant selectors
    # reach them directly.
    css = theme.stylesheet()
    assert "QFileDialog {" in css
    assert "QFileDialog QLineEdit" in css
    assert "QFileDialog QListView" in css
    assert "QFileDialog QTreeView" in css
    assert "QFileDialog QHeaderView" in css


def test_stylesheet_themes_splitters_tabs_and_lineedits():
    # Regression 2026-09-17, owner's report: "killin' me w/the white
    # background in the settings section". Root cause: QSplitter,
    # QTabWidget's pane/QTabBar, and QLineEdit (used directly for OBS
    # host/password/input-name, and internally by every QKeySequenceEdit
    # hotkey field) had no rule at all, so on a light native palette they
    # fell through to native white/light-grey instead of the app's own
    # background showing through or its own dark field styling -- also
    # made the Position & Hierarchy labels unreadable (near-white text on
    # a white splitter background).
    css = theme.stylesheet()
    assert "QSplitter {" in css
    assert "QSplitter::handle" in css
    assert "QTabWidget::pane" in css
    assert "QTabBar::tab" in css
    assert "QLineEdit" in css


def test_control_panel_window_paints_the_neon_grid_background(qapp, tmp_path):
    # Same report, other half: the flat single-color background wasn't
    # enough once the containers above stopped hiding it behind their own
    # native white -- the owner asked for the actual neon cyber grid
    # pattern from ../ai-animated-video's design system instead of a
    # plain fill. Verified by construction (paintEvent doesn't raise, and
    # a grabbed frame isn't just the flat INK_900 -- the grid lines /
    # glow actually paint something) rather than asserting exact pixel
    # colors, which would be brittle against antialiasing/gradient math.
    from unicorn_cloak.config import Config
    from unicorn_cloak.control_panel_window import ControlPanelWindow
    from unicorn_cloak.render import RenderWindow

    from qt_helpers import make_test_rig

    rig = make_test_rig()
    config = Config()
    window = RenderWindow(rig, config.motion, hotkeys_config=config.hotkeys)
    qapp.setStyleSheet(theme.stylesheet())
    try:
        panel = ControlPanelWindow(rig, config, window, state_path=tmp_path / "settings.json")
        panel.resize(800, 600)
        panel.show()
        qapp.processEvents()
        img = panel.grab().toImage()
        colors = {img.pixelColor(x, 2).name() for x in range(0, 800, 4)}
        # A flat fill would produce exactly one color across the row;
        # the grid's periodic hairlines must produce more than one.
        assert len(colors) > 1
    finally:
        qapp.setStyleSheet("")


def test_messagebox_actually_gets_the_themed_background_color(qapp):
    from PySide6.QtWidgets import QMessageBox

    qapp.setStyleSheet(theme.stylesheet())
    try:
        box = QMessageBox()
        box.ensurePolished()
        assert box.palette().color(box.backgroundRole()).name() == theme.INK_900
    finally:
        qapp.setStyleSheet("")


def test_filedialog_actually_gets_the_themed_background_color(qapp):
    from PySide6.QtWidgets import QFileDialog

    qapp.setStyleSheet(theme.stylesheet())
    try:
        dlg = QFileDialog()
        dlg.ensurePolished()
        assert dlg.palette().color(dlg.backgroundRole()).name() == theme.INK_900
    finally:
        qapp.setStyleSheet("")


def test_render_window_is_not_opted_into_styled_background(qapp):
    # The actual behavioral guarantee behind the rule above: even after
    # the global stylesheet is applied, a real RenderWindow must not have
    # WA_StyledBackground set (that's what would let a stylesheet
    # background paint on a plain QWidget subclass in the first place),
    # and must keep the translucency attribute the transparent-window
    # OBS capture depends on.
    theme.apply(qapp)
    rig = make_test_rig()
    window = RenderWindow(rig, Config().motion)
    assert window.testAttribute(Qt.WidgetAttribute.WA_StyledBackground) is False
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
    assert window.objectName() == ""  # never matches the themed objectName selectors


def test_control_panel_and_help_windows_opt_into_the_theme(qapp):
    theme.apply(qapp)
    rig = make_test_rig()
    window = RenderWindow(rig, Config().motion)

    panel = ControlPanelWindow(rig, Config(), window)
    assert panel.objectName() == "ControlPanelWindow"
    assert panel.testAttribute(Qt.WidgetAttribute.WA_StyledBackground) is True

    help_window = HelpWindow()
    assert help_window.objectName() == "HelpWindow"
