"""Platform configuration, read from the environment with defaults.

Importing this module loads the `.env` file next to it (if python-dotenv is
installed and the file exists), so the app, the seed scripts and the scripts
under scripts/ all see the same settings. Variables that are already set in
the environment take precedence over the file.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:   # python-dotenv not installed: environment variables only
    pass

NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
PORT           = int(os.getenv("PORT", 5050))

# ── Demo / read-only mode ──────────────────────────────────────────
# When DEMO_MODE is on (the read-only demo instance), the server hard-rejects
# every write: all mutating API endpoints return 403 (only read/GET + the
# GraphRAG chat is allowed) and the chat engine is forced read-only
# (no enrichment/reassignment). Enforced server-side — not just hidden in the UI.
DEMO_MODE      = os.getenv("DEMO_MODE", "0").strip().lower() in ("1", "true", "yes", "on")

