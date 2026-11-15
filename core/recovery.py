"""Crash recovery: the open session is mirrored to a local file after every change and removed
on a normal exit. If the app stops unexpectedly, the next start offers to restore it. No Qt.

The file stays on this computer (DV1_LOGGER_DATA_DIR, or the user's local app-data folder).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from core.data_io import SessionError, load_session, save_session
from core.session import Session

FILE_NAME = "recovery-session.json"


def data_dir() -> Path:
    override = os.environ.get("DV1_LOGGER_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "EML" / "DV1Logger"
    return Path.home() / ".local" / "share" / "dv1logger"


def recovery_path() -> Path:
    return data_dir() / FILE_NAME


def write_recovery(session: Session, app_version: str = "") -> Path:
    path = recovery_path()
    save_session(session, str(path), app_version=app_version)
    return path


def clear_recovery() -> None:
    try:
        recovery_path().unlink()
    except FileNotFoundError:
        pass


def read_recovery() -> Optional[Session]:
    """The session left by an unexpected exit, or None. A damaged file is set aside, not deleted."""
    path = recovery_path()
    if not path.exists():
        return None
    try:
        session = load_session(str(path))
    except SessionError:
        try:
            os.replace(path, path.with_suffix(".damaged.json"))
        except OSError:
            pass
        return None
    return session if session.readings else None
