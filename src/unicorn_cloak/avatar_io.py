"""
Loads an avatar with an automatic format upgrade: a file saved by an
older version gets its missing fields filled with defaults (already
handled by persistence.load_avatar's field-by-field .get() defaults),
then is immediately re-saved in the current format so it won't need
upgrading again -- with the usual one-backup safety net from
persistence.save_avatar. The owner is warned that this happened, and that
the backup is temporary (overwritten the very next time this avatar is
saved, not a permanent archive).

Kept separate from persistence.py, which is deliberately Qt-free: this
module's whole job is showing a QMessageBox.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from .persistence import load_avatar, needs_migration, save_avatar
from .rig import AvatarRig


def load_avatar_with_upgrade(path: str | Path, parent=None) -> AvatarRig:
    path = Path(path)
    migration_needed = needs_migration(path)
    rig = load_avatar(path)

    if migration_needed:
        save_avatar(rig, path)
        backup_path = path.with_suffix(path.suffix + ".bak")
        QMessageBox.information(
            parent,
            "Avatar updated",
            f'"{rig.name}" was saved by an older version of Unicorn Cloak '
            f"and has been automatically updated to the current format.\n\n"
            f"A backup of the original was saved to:\n{backup_path}\n\n"
            f"That backup only lasts until the next time this avatar is "
            f"saved again -- copy it elsewhere first if you want to keep "
            f"it longer.",
        )

    return rig
