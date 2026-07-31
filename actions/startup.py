"""Windows startup-with-Windows via the registry Run key.

All registry operations are best-effort and never raise to the caller.
On non-Windows hosts (no ``winreg``) every function degrades gracefully.
"""

from __future__ import annotations

import os
import sys

try:
    import winreg  # stdlib on Windows
except Exception:  # pragma: no cover - non-Windows / stripped interp.
    winreg = None  # type: ignore[assignment]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MemScope"


def startup_exe_path() -> str:
    """Return the command string to launch MemScope at login.

    When frozen (PyInstaller / similar) the executable itself is the entry
    point. In dev we launch the venv python against ``memscope/app.py`` so
    the registry value stays portable across checkouts.
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    app_path = os.path.join(repo_root, "memscope", "app.py")
    return sys.executable + " " + app_path


def is_startup_set() -> bool:
    """True if the MemScope Run value exists under HKCU."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_startup(enabled: bool) -> bool:
    """Enable or disable login startup. Returns True on success."""
    if winreg is None:
        return False
    try:
        if enabled:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_exe_path())
            return True
        # disabled -> delete value (missing is success)
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
        return True
    except Exception:
        return False
