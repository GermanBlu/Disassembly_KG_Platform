#!/usr/bin/env python3
"""Subprocess worker for STEP Phase 1.

Reads a JSON request from stdin, runs run_step_phase1(), and writes the
JSON result to stdout.  Designed to be invoked by app.py via subprocess.run()
so that OCC's Cocoa/OpenGL requirements are fully isolated from Flask.
"""
import json
import os
import sys

# Ensure the project root is on sys.path so "from models.…" works
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def main():
    req = json.loads(sys.stdin.read())
    step_paths = req["step_paths"]
    labels = req["labels"]
    manual_liaison = req.get("manual_liaison")
    contact_tol = req.get("contact_tol")
    pixel_tol = req.get("pixel_tol")
    settings = req.get("settings")

    # Redirect stdout → stderr at the OS file-descriptor level.
    # This catches BOTH Python print() AND C-level printf from OpenCASCADE
    # (which writes directly to fd 1, bypassing Python's sys.stdout).
    # We save a copy of the real stdout fd to write the JSON result at the end.
    real_stdout_fd = os.dup(1)          # duplicate fd 1
    os.dup2(2, 1)                       # point fd 1 → stderr (fd 2)
    sys.stdout = sys.stderr             # also fix Python-level

    try:
        from models.step_pipeline import run_step_phase1
        result = run_step_phase1(step_paths, labels, manual_liaison=manual_liaison,
                                 contact_tol=contact_tol, pixel_tol=pixel_tol,
                                 settings=settings)
    except Exception as e:
        import traceback
        traceback.print_exc()
        result = {"success": False, "error": f"Worker crash: {str(e)}"}

    # Restore real stdout and write ONLY the JSON result.
    # allow_nan=False enforces the no-inf/NaN invariant at the serialization
    # boundary (browsers reject Infinity/NaN tokens). If a non-finite value ever
    # slips through, fail loudly with a clean error result instead of emitting
    # invalid JSON that would only break far downstream in the browser.
    os.dup2(real_stdout_fd, 1)
    os.close(real_stdout_fd)
    sys.stdout = os.fdopen(1, "w")
    try:
        payload = json.dumps(result, default=str, allow_nan=False)
    except ValueError as e:
        payload = json.dumps({"success": False,
                              "error": f"Non-finite value in Phase 1 result: {e}"})
    sys.stdout.write(payload)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
