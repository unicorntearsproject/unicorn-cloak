from PySide6.QtWidgets import QTabWidget, QTextBrowser

from unicorn_cloak.help_window import HelpWindow


def test_help_window_has_the_four_expected_tabs_in_order(qapp):
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Overview", "Usage", "Sprites", "Reference",
    ]


def test_every_help_tab_has_its_own_rendered_content(qapp):
    # Regression 2026-09-17, owner's request ("a proper help dialog with
    # overall usage methodology & tips... make it tabbed"): each tab is a
    # genuinely separate QTextBrowser/document, not one shared HTML blob
    # sliced by anchors -- verify each one actually has non-empty content.
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    for i in range(tabs.count()):
        browser = tabs.widget(i)
        assert isinstance(browser, QTextBrowser)
        assert browser.toPlainText().strip() != ""


def test_reference_tab_keeps_the_original_field_reference_content(qapp):
    # The pre-tabbed Help window's exhaustive per-field reference must
    # not be lost in the split -- it's the one thing tooltips alone don't
    # cover (see control_panel_window.py's own tooltips).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    reference_text = tabs.widget(3).toPlainText()
    assert "Sprite concepts" in reference_text
    assert "Group name / State name" in reference_text
    assert "Check for Issues" in reference_text


def test_overview_tab_states_the_app_premise(qapp):
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    overview_text = tabs.widget(0).toPlainText()
    assert "About me" in overview_text
    assert "PNGTuber" in overview_text
