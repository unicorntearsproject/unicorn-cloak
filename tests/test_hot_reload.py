import time

from unicorn_cloak.hot_reload import AssetWatcher


def _wait_until(qapp, predicate, timeout=5.0, interval=0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(interval)
    qapp.processEvents()
    return predicate()


def test_avatar_file_changed_fires_when_the_watched_file_is_rewritten(qapp, tmp_path):
    path = tmp_path / "avatar.uc"
    path.write_text("v1")

    watcher = AssetWatcher()
    watcher.watch_avatar_file(str(path))
    fired = []
    watcher.avatar_file_changed.connect(lambda: fired.append(True))

    path.write_text("v2")
    assert _wait_until(qapp, lambda: len(fired) > 0)
    watcher.stop()


def test_sprite_file_changed_reports_the_specific_path(qapp, tmp_path):
    sprite_path = tmp_path / "mouth-open.png"
    sprite_path.write_bytes(b"fake-png-v1")
    other_path = tmp_path / "mouth-closed.png"
    other_path.write_bytes(b"fake-png-v1")

    watcher = AssetWatcher()
    watcher.watch_sprite_files([str(sprite_path), str(other_path)])
    changed = []
    watcher.sprite_file_changed.connect(changed.append)

    sprite_path.write_bytes(b"fake-png-v2")
    assert _wait_until(qapp, lambda: len(changed) > 0)
    assert changed[0] == str(sprite_path)
    watcher.stop()


def test_a_burst_of_writes_is_debounced_into_one_signal(qapp, tmp_path):
    path = tmp_path / "avatar.uc"
    path.write_text("v1")

    watcher = AssetWatcher()
    watcher.watch_avatar_file(str(path))
    fired = []
    watcher.avatar_file_changed.connect(lambda: fired.append(True))

    for i in range(5):
        path.write_text(f"v{i + 2}")
        qapp.processEvents()
        time.sleep(0.01)

    # Give the debounce timer (200ms) time to settle after the burst.
    time.sleep(0.3)
    qapp.processEvents()
    assert len(fired) == 1
    watcher.stop()


def test_watch_survives_a_replace_via_rename_not_just_in_place_writes(qapp, tmp_path):
    # Many editors save via write-to-temp + os.replace(), which changes
    # the file's inode -- QFileSystemWatcher would otherwise silently
    # drop the path after the first such save (see hot_reload.py's
    # docstring). Verify a *second* replace-based save still fires.
    path = tmp_path / "mouth-open.png"
    path.write_bytes(b"v1")

    watcher = AssetWatcher()
    watcher.watch_sprite_files([str(path)])
    changed = []
    watcher.sprite_file_changed.connect(changed.append)

    def replace_save(content: bytes) -> None:
        tmp = tmp_path / "mouth-open.png.tmp"
        tmp.write_bytes(content)
        tmp.replace(path)

    replace_save(b"v2")
    assert _wait_until(qapp, lambda: len(changed) == 1)

    replace_save(b"v3")
    assert _wait_until(qapp, lambda: len(changed) == 2)
    watcher.stop()


def test_watch_sprite_files_replaces_the_previous_set(qapp, tmp_path):
    old_path = tmp_path / "old.png"
    new_path = tmp_path / "new.png"
    old_path.write_bytes(b"v1")
    new_path.write_bytes(b"v1")

    watcher = AssetWatcher()
    watcher.watch_sprite_files([str(old_path)])
    watcher.watch_sprite_files([str(new_path)])

    changed = []
    watcher.sprite_file_changed.connect(changed.append)

    old_path.write_bytes(b"v2")
    time.sleep(0.3)
    qapp.processEvents()
    assert changed == []  # no longer watched

    new_path.write_bytes(b"v2")
    assert _wait_until(qapp, lambda: len(changed) == 1)
    watcher.stop()


def test_stop_clears_all_watches(qapp, tmp_path):
    path = tmp_path / "avatar.uc"
    path.write_text("v1")

    watcher = AssetWatcher()
    watcher.watch_avatar_file(str(path))
    watcher.stop()

    fired = []
    watcher.avatar_file_changed.connect(lambda: fired.append(True))
    path.write_text("v2")
    time.sleep(0.3)
    qapp.processEvents()
    assert fired == []


def test_watch_avatar_file_with_none_is_a_noop():
    watcher = AssetWatcher()
    watcher.watch_avatar_file(None)  # should not raise
    watcher.stop()


def test_watching_a_nonexistent_path_does_not_raise(tmp_path):
    watcher = AssetWatcher()
    watcher.watch_avatar_file(str(tmp_path / "does-not-exist.uc"))
    watcher.watch_sprite_files([str(tmp_path / "also-missing.png")])
    watcher.stop()
