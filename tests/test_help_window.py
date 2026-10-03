from PySide6.QtWidgets import QTabWidget, QTextBrowser

from unicorn_cloak.help_window import HelpWindow


def test_help_window_has_the_five_expected_tabs_in_order(qapp):
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Overview", "Usage", "Sprites", "Hotkeys", "Reference",
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
    reference_text = tabs.widget(4).toPlainText()
    assert "Sprite concepts" in reference_text
    assert "Group name / State name" in reference_text
    assert "Check for Issues" in reference_text


def test_overview_tab_states_the_app_premise(qapp):
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    overview_text = tabs.widget(0).toPlainText()
    assert "About me" in overview_text
    assert "PNGTuber" in overview_text


def test_hotkeys_tab_covers_costumes_expressions_and_canvas_dragging(qapp):
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    hotkeys_text = tabs.widget(3).toPlainText()
    assert "Shift+1" in hotkeys_text
    assert "Hide" in hotkeys_text and "Show" in hotkeys_text
    assert "Escape" in hotkeys_text
    assert "rotate" in hotkeys_text.lower()


def test_hotkeys_tab_flags_the_control_panel_focus_requirement_for_expressions(qapp):
    # The one real gotcha: unlike costume hotkeys (Render Window focus),
    # Expression hotkeys only fire while the Control Panel itself has
    # focus, since they click its own buttons -- must not be silently
    # left out of the docs.
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    hotkeys_text = tabs.widget(3).toPlainText()
    assert "Control Panel" in hotkeys_text
    assert "closed" in hotkeys_text.lower() or "focus" in hotkeys_text.lower()


def test_reference_tab_documents_desktop_audio_and_the_device_dropdown(qapp):
    # Regression, bug audit addendum 2026-09-23, D5 ("missing docs"):
    # neither the Help window nor the README mentioned Desktop Audio or
    # the Device dropdown/"Now capturing" label before this.
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    reference_text = tabs.widget(4).toPlainText()
    assert "Desktop audio" in reference_text
    assert "Now capturing" in reference_text
    assert "Device dropdown" in reference_text


def test_reference_tab_documents_the_mute_mouth_button(qapp):
    # Quick-win enhancement E12 (bug audit addendum 2026-09-23): a manual
    # mute toggle, independent of OBS mute -- must be documented, not
    # just a mystery button in the bottom bar.
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    reference_text = tabs.widget(4).toPlainText()
    assert "Mute mouth" in reference_text
    assert "independent of OBS mute" in reference_text


def test_reference_tab_documents_the_calibrate_noise_gate_button(qapp):
    # Quick-win enhancement E5 (bug audit addendum 2026-09-23).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    reference_text = tabs.widget(4).toPlainText()
    assert "Calibrate noise gate" in reference_text


def test_reference_tab_documents_render_window_size_presets(qapp):
    # Quick-win enhancement E6 (bug audit addendum 2026-09-23).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    reference_text = tabs.widget(4).toPlainText()
    assert "Render Window size" in reference_text
    assert "1920×1080" in reference_text


def test_reference_tab_documents_the_file_playback_timeline(qapp):
    # New feature, owner's request 2026-09-23: "a clickable timeline bar
    # for when playing from a file with a time/total clock by it."
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    reference_text = tabs.widget(4).toPlainText()
    assert "timeline" in reference_text.lower()
    assert "Rewind" in reference_text


def test_reference_tab_documents_recent_avatars_costume_memory_and_backups(qapp):
    # E7, E10, E11 (bug audit addendum 2026-09-23).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    reference_text = tabs.widget(4).toPlainText()
    assert "Recent" in reference_text
    assert "last showing" in reference_text
    assert "timestamped copy" in reference_text


def test_hotkeys_tab_documents_the_editing_shortcuts(qapp):
    # E4 (bug audit addendum 2026-09-23).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    hotkeys_text = tabs.widget(3).toPlainText()
    for chord in ("Ctrl+S", "Ctrl+Shift+S", "Ctrl+O", "Ctrl+D", "Arrow keys"):
        assert chord in hotkeys_text


def test_reference_tab_documents_clickable_issue_results(qapp):
    # E8 (bug audit addendum 2026-09-23).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    assert "click an issue to select" in tabs.widget(4).toPlainText()


def test_reference_tab_documents_drag_and_drop_sprites(qapp):
    # E9 (bug audit addendum 2026-09-23).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    assert "drag one or more PNGs" in tabs.widget(4).toPlainText()


def test_reference_tab_documents_the_error_status_line(qapp):
    # E3 (bug audit addendum 2026-09-23).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    text = tabs.widget(4).toPlainText()
    assert "red status message" in text
    assert "Dismiss" in text


def test_reference_tab_documents_per_source_audio_profiles(qapp):
    # E1 (bug audit addendum 2026-09-23).
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    assert "per-source profile" in tabs.widget(4).toPlainText()


def test_reference_tab_explains_the_per_source_device_lists(qapp):
    # Owner's report 2026-10-02: Microphone and Desktop audio each used to
    # offer every device.
    dlg = HelpWindow()
    tabs = dlg.findChild(QTabWidget)
    text = tabs.widget(4).toPlainText()
    assert "only real inputs" in text
    assert "only outputs" in text
