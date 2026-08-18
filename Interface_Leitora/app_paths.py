from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_NAME = "OSLMeter"


def bundle_dir() -> Path:
    """Return the directory containing read-only bundled application files."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def documents_dir() -> Path:
    """Find the Windows Documents directory, including localized profiles."""
    home = Path.home()
    candidates = [home / "Documents", home / "Documentos"]
    one_drive = os.environ.get("OneDrive")
    if one_drive:
        candidates.extend(
            [Path(one_drive) / "Documents", Path(one_drive) / "Documentos"]
        )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return home / "Documents"


USER_DATA_DIR = documents_dir() / APP_NAME
USER_ASSETS_DIR = USER_DATA_DIR / "assets"


def resource_path(relative_path: str | Path) -> str:
    """Return an application resource, preferring user-copied assets."""
    path = Path(relative_path)
    if path.parts and path.parts[0].lower() == "assets":
        user_path = USER_ASSETS_DIR.joinpath(*path.parts[1:])
        if user_path.exists():
            return str(user_path)
    return str(bundle_dir() / path)


def ensure_user_data() -> Path:
    """Create the persistent Documents tree and copy missing UI assets."""
    USER_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for relative_path in (
        "database",
        "testes",
        "log",
        "exports",
        "backups",
    ):
        (USER_ASSETS_DIR / relative_path).mkdir(parents=True, exist_ok=True)

    bundled_ui = bundle_dir() / "assets" / "UI"
    target_ui = USER_ASSETS_DIR / "UI"
    if bundled_ui.is_dir():
        for source in bundled_ui.rglob("*"):
            if not source.is_file():
                continue
            target = target_ui / source.relative_to(bundled_ui)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
    return USER_DATA_DIR
