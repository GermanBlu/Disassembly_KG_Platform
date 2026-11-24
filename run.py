"""Cross-platform launcher for the KG Platform.

Works identically on macOS, Linux and Windows. Detects the OS, picks the
right Python interpreter (prefers an active venv / conda env, falls back to
the current `python`) and runs `app.py`.

Usage:
    python run.py [args passed through to app.py]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _pick_python() -> str:
    """Pick the best Python interpreter for app.py.

    Preference order:
      1. The interpreter currently running this script (covers active venv /
         conda env — `python run.py` from inside `.venv` Just Works).
      2. A `.venv` inside the project (created by `python -m venv .venv`).
      3. `python3` on PATH (POSIX convention), then `python` (Windows).
    """
    if sys.executable and Path(sys.executable).is_file():
        return sys.executable

    if os.name == "nt":
        venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = ROOT / ".venv" / "bin" / "python3"
    if venv_py.is_file():
        return str(venv_py)

    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found

    sys.exit("No Python interpreter found on PATH.")


def main() -> int:
    env = os.environ.copy()

    cmd = [_pick_python(), str(ROOT / "app.py"), *sys.argv[1:]]
    # On Windows, child Ctrl+C handling is cleaner with subprocess.run than execv.
    # Using subprocess uniformly keeps behaviour identical across OSes.
    try:
        return subprocess.run(cmd, env=env, cwd=str(ROOT)).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
