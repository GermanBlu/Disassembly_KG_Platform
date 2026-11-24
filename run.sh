#!/bin/bash
# Cross-platform entry point for macOS / Linux. Delegates to run.py so the
# OS detection and PYTHONPATH wiring live in one place.
#
# If you have a venv, activate it first: source .venv/bin/activate
# Otherwise ensure flask, neo4j, openai, python-dotenv are installed.

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    exec python3 run.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python run.py "$@"
else
    echo "No Python interpreter found on PATH." >&2
    exit 1
fi
