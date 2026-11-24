"""KG Platform — unified multi-product GraphRAG application.

Routes:
  GET  /                          → Product Overview (SPA shell)
  GET  /api/products              → List all products
  POST /api/products              → Create new product (upload JSON data + build KG)
  DEL  /api/products/<id>         → Delete product + all its nodes
  GET  /api/products/<id>         → Get product detail + stats
  GET  /api/products/<id>/graph   → Product subgraph (with ?view= param)
  POST /api/products/<id>/chat    → RAG chat (SSE streaming)
  GET  /api/products/<id>/parts   → Part names for frontend humanizer
  GET  /api/library               → Library stats
  GET  /api/library/graph         → Library subgraph for visualization
  POST /api/library/ensure        → Ensure library nodes exist
  POST /api/validate              → Validate input data without building
  GET  /api/products/<id>/sequence-count → Complete disassembly sequences and orders of execution (AOG)
"""
import functools
import json
import logging
import os

# `config` loads the .env file; import it first so every setting is populated.
import config  # noqa: E402

from flask import (Flask, request, jsonify, Response, stream_with_context,  # noqa: E402
                   send_from_directory)
from werkzeug.exceptions import RequestEntityTooLarge  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

from models.library import ensure_library, get_library_stats, get_library_graph  # noqa: E402
from models.product import (list_products, get_product, delete_product,  # noqa: E402
                            get_product_graph, get_product_part_names,
                            update_node_properties, remove_node_property,
                            count_disassembly_sequences)
from models.kg_builder import (auto_task_names, build_product_kg, build_stage1_structural,  # noqa: E402
                                build_stage2_operational, build_stage3_properties,
                                validate_input)
from rag.engine import GraphRAGEngine  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = Flask(__name__, static_folder="static", static_url_path="/static")

# Upload size cap — reject oversized bodies before they reach the handler.
# Default 300 MB (real CAD assemblies are large — e.g. a multi-part STEP can be
# 90 MB+), override with MAX_UPLOAD_MB in .env.
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "300")) * 1024 * 1024


@app.errorhandler(RequestEntityTooLarge)
def _handle_too_large(_err):
    limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return jsonify({
        "error": f"Request body exceeds {limit_mb} MB limit. "
                 f"Set MAX_UPLOAD_MB in .env to raise it."
    }), 413


# ── Demo read-only guard ────────────────────────────────────────────────────
# In DEMO_MODE every mutating request is rejected server-side; only reads (GET)
# and the GraphRAG chat are allowed. The UI also hides the write controls, but
# this guard is what rejects a crafted request. config.DEMO_MODE is read on
# every request so tests can toggle it.
_DEMO_WRITE_WHITELIST = {"api_chat"}


@app.before_request
def _enforce_demo_read_only():
    if not config.DEMO_MODE:
        return
    if request.method in ("POST", "PUT", "PATCH", "DELETE") \
            and request.endpoint not in _DEMO_WRITE_WHITELIST:
        return jsonify({
            "error": "This is a read-only demo — modifications are disabled."
        }), 403


@app.route("/api/config", methods=["GET"])
def api_config():
    """Client-visible runtime config (e.g. whether this is a read-only demo)."""
    return jsonify({"demo_mode": config.DEMO_MODE})


# Starter questions served when the catalogue cannot be read or marks no case
# as a starter. They repeat the questions of the ui_starter cases in
# rag_eval/cases.json (the same list is the fallback in static/app.html) and
# carry no catalogue id. The six questions name no part and no product-specific
# property, so they can be asked about every product.
_FALLBACK_STARTERS = [
    {"id": None, "q": "What components are in this product?"},
    {"id": None, "q": "What connection types are used in this product?"},
    {"id": None, "q": "What is the first step to disassemble this product?"},
    {"id": None, "q": "Generate a complete disassembly sequence for this product."},
    {"id": None, "q": "Which skills do the disassembly tasks of this product require?"},
    {"id": None, "q": "How many transitions does the product have?"},
]


@functools.lru_cache(maxsize=1)
def _chat_starters():
    """Starter chips from the eval catalog (single source of truth with the
    GraphRAG eval harness — see rag_eval/cases.json).

    The chips are the cases flagged ``ui_starter``; no case id is looked up, so
    renaming or removing a case cannot break the endpoint."""
    from rag_eval.cases import load_cases, starters
    return starters(load_cases()["cases"])


@app.route("/api/chat/starters", methods=["GET"])
def api_chat_starters():
    try:
        chips = _chat_starters()
    except Exception as e:  # noqa: BLE001 — chips are optional UI sugar
        app.logger.warning("chat starters unavailable: %s", e)
        chips = []
    return jsonify({"starters": chips or _FALLBACK_STARTERS})


@app.route("/api/pipeline/algorithms", methods=["GET"])
def api_pipeline_algorithms():
    """Enumerate the selectable pipeline algorithms + the settings schema for the
    settings UI (dropdowns, standard values). OCC-free, read-only."""
    from pipeline.settings import (ALGORITHMS, ALGORITHM_LABELS,
                                   DEFAULT_PIPELINE_SETTINGS, CODE_DEFAULTS,
                                   standard_values)
    return jsonify({
        "algorithms": ALGORITHMS,
        "labels": ALGORITHM_LABELS,
        "defaults": DEFAULT_PIPELINE_SETTINGS,
        "standard": standard_values(),
        "code_defaults": CODE_DEFAULTS,
    })

# ── Lazy Neo4j driver ─────────────────────────────────────────────────────────
_driver = None

def get_driver():
    global _driver
    if _driver is None:
        try:
            _driver = GraphDatabase.driver(
                config.NEO4J_URI,
                auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
                # Aura / load-balanced deployments silently close idle server-side
                # connections. Without these, a pooled connection that has gone
                # stale during an idle period surfaces as a "defunct connection"
                # 500 on the next request (errno 49 / SessionExpired). Recycle
                # connections well before Aura's idle cutoff and liveness-check
                # any pooled connection before handing it to a query.
                max_connection_lifetime=300,      # recycle after 5 min
                liveness_check_timeout=30,         # ping conns idle > 30 s before reuse
                keep_alive=True,
            )
            _driver.verify_connectivity()
        except Exception as e:
            _driver = None
            raise ConnectionError(
                f"Could not connect to Neo4j at {config.NEO4J_URI}. "
                f"Check that Neo4j is running and your .env credentials are correct. "
                f"Details: {e}"
            )
    return _driver


# ── Static SPA ────────────────────────────────────────────────────────────────
@app.route("/")
def serve_spa():
    """The single-page app. It uses hash routing (#/products, #/product/<id>,
    #/library, #/new), so this one route serves every view. Shares the backend
    APIs and static/js/graph.js."""
    return send_from_directory("static", "app.html")


# ── Product CRUD ──────────────────────────────────────────────────────────────
@app.route("/api/products", methods=["GET"])
def api_list_products():
    return jsonify(list_products(get_driver()))


@app.route("/api/products", methods=["POST"])
def api_create_product():
    """Create product from JSON input data. Expects full data dict with
    product, components, connections, transitions."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    ok, errors, warnings = validate_input(data)
    if not ok:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    # Ensure library exists
    ensure_library(get_driver())

    # Build product KG
    summary = build_product_kg(get_driver(), data)
    return jsonify(summary), 201


@app.route("/api/products/<product_id>", methods=["GET"])
def api_get_product(product_id):
    prod = get_product(get_driver(), product_id)
    if not prod:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(prod)


@app.route("/api/products/<product_id>", methods=["DELETE"])
def api_delete_product(product_id):
    delete_product(get_driver(), product_id)
    return jsonify({"deleted": product_id})


@app.route("/api/products/<product_id>/graph", methods=["GET"])
def api_product_graph(product_id):
    view = request.args.get("view", "full")
    mode = request.args.get("mode")  # "condensed" collapses 1-part-removal transitions
    graph = get_product_graph(get_driver(), product_id, view, mode=mode)
    return jsonify(graph)


@app.route("/api/products/<product_id>/parts", methods=["GET"])
def api_product_parts(product_id):
    return jsonify(get_product_part_names(get_driver(), product_id))


@app.route("/api/products/<product_id>/sequence-count", methods=["GET"])
def api_sequence_count(product_id):
    """Number of complete disassembly sequences ("count", "sequence_count") and
    of their orders of execution ("ordering_count"), from the AND/OR graph."""
    result = count_disassembly_sequences(get_driver(), product_id)
    if result is None:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(result)


# ── Staged Population Endpoints ──────────────────────────────────────────────
@app.route("/api/products/<product_id>/structural", methods=["POST"])
def api_build_structural(product_id):
    """Stage 1 — Build structural layer (Product, Assemblies, Components,
    Connections, Transitions) in a separate transaction."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    if data.get("product", {}).get("id") != product_id:
        return jsonify({"error": "URL product_id does not match data.product.id"}), 400
    ok, errors, _ = validate_input(data)
    if not ok:
        return jsonify({"error": "Validation failed", "details": errors}), 400
    ensure_library(get_driver())
    summary = build_stage1_structural(get_driver(), data)
    from models.kg_builder import validate_structural_layer
    validation = validate_structural_layer(get_driver(), product_id)
    return jsonify({**summary, "structural_validation": validation}), 201


@app.route("/api/products/<product_id>/operational", methods=["POST"])
def api_build_operational(product_id):
    """Stage 2 — Build operational layer (DisassemblyTasks, Skills, Tools,
    Agents) anchored to existing structural nodes."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    if data.get("product", {}).get("id") != product_id:
        return jsonify({"error": "URL product_id does not match data.product.id"}), 400
    ok, errors, _ = validate_input(data)
    if not ok:
        return jsonify({"error": "Validation failed", "details": errors}), 400
    ensure_library(get_driver())
    summary = build_stage2_operational(get_driver(), data)
    return jsonify(summary), 201


@app.route("/api/products/<product_id>/properties", methods=["POST"])
def api_build_properties(product_id):
    """Stage 3 — Property enrichment. No automatic step: writes nothing and
    returns properties_set = 0 (properties are set through the chat)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    if data.get("product", {}).get("id") != product_id:
        return jsonify({"error": "URL product_id does not match data.product.id"}), 400
    summary = build_stage3_properties(get_driver(), data)
    return jsonify(summary), 200


@app.route("/api/products/<product_id>/nodes/<node_id>/properties", methods=["PATCH"])
def api_update_node_props(product_id, node_id):
    """Add/update custom properties on any node (non-destructive)."""
    props = request.get_json()
    if not props:
        return jsonify({"error": "No properties provided"}), 400
    updated, error = update_node_properties(get_driver(), product_id, node_id, props)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"properties": updated})


@app.route("/api/products/<product_id>/nodes/<node_id>/properties/<key>", methods=["DELETE"])
def api_remove_node_prop(product_id, node_id, key):
    """Remove a single custom property from a node."""
    updated, error = remove_node_property(get_driver(), product_id, node_id, key)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"properties": updated})


@app.route("/api/products/<product_id>/chat", methods=["POST"])
def api_chat(product_id):
    """GraphRAG chat — SSE streaming."""
    body = request.get_json()
    question = body.get("message", "").strip()
    history = body.get("history", [])

    if not question:
        return jsonify({"error": "Empty question"}), 400

    if not config.OPENAI_API_KEY:
        return jsonify({"error": "OPENAI_API_KEY not set"}), 500

    # Get product info for scoping
    prod = get_product(get_driver(), product_id)
    if not prod:
        return jsonify({"error": "Product not found"}), 404

    part_names = get_product_part_names(get_driver(), product_id)

    engine = GraphRAGEngine(
        driver=get_driver(),
        product_id=product_id,
        product_name=prod["name"],
        part_names=part_names,
        api_key=config.OPENAI_API_KEY,
        model=config.OPENAI_MODEL,
        read_only=config.DEMO_MODE,
    )

    def generate():
        for event in engine.ask(question, history):
            yield event

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ── Library ───────────────────────────────────────────────────────────────────
def _ensure_library_unless_demo():
    """Ensure the static library exists — but never WRITE in DEMO_MODE.

    The before_request guard only blocks mutating HTTP *methods*; a GET handler
    that called ensure_library() (a MERGE) would still issue a write transaction,
    silently violating the read-only contract. The demo is pre-seeded, so
    skipping the MERGE is a no-op there and keeps GET reads strictly read-only.
    """
    if config.DEMO_MODE:
        return
    ensure_library(get_driver())


@app.route("/api/library", methods=["GET"])
def api_library_stats():
    _ensure_library_unless_demo()
    return jsonify(get_library_stats(get_driver()))


@app.route("/api/library/graph", methods=["GET"])
def api_library_graph():
    _ensure_library_unless_demo()
    return jsonify(get_library_graph(get_driver()))


@app.route("/api/library/items/<label>", methods=["GET"])
def api_library_get_items(label):
    from models.library import get_library_items
    try:
        return jsonify(get_library_items(get_driver(), label))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/library/items/<label>", methods=["POST"])
def api_library_save_items(label):
    from models.library import save_library_items
    items = request.json
    try:
        save_library_items(get_driver(), label, items)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"status": "success"})

@app.route("/api/library/items/<label>/<item_id>", methods=["DELETE"])
def api_library_delete_item(label, item_id):
    from models.library import delete_library_item
    try:
        delete_library_item(get_driver(), label, item_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"status": "success"})


@app.route("/api/library/ensure", methods=["POST"])
def api_ensure_library():
    ensure_library(get_driver())
    return jsonify({"status": "Library ensured"})

@app.route("/api/library/reset", methods=["POST"])
def api_reset_library():
    """Destructive: wipe the entire graph and reseed the library.

    Gated on ADMIN_TOKEN. If unset, the endpoint is disabled by default.
    Callers must send `X-Admin-Token: <value>` matching the env var.
    """
    expected = os.getenv("ADMIN_TOKEN")
    if not expected or request.headers.get("X-Admin-Token") != expected:
        return jsonify({"error": "unauthorized"}), 401
    from models.library import reset_library
    reset_library(get_driver())
    return jsonify({"status": "Library reset and re-ingested"})


# ── STEP Pipeline ─────────────────────────────────────────────────────────────
# macOS subprocess architecture:
# OCC's GPU-based interference check (Viewer3d offscreen renderer) requires a
# fully initialized Cocoa NSApplication + OpenGL context.  Running this inside
# Flask's process causes a SIGSEGV because Flask has no Cocoa event loop.
#
# Solution: Phase 1 runs in an isolated subprocess (models/step_worker.py).
# Communication is JSON-over-stdin/stdout.  The worker redirects fd 1 → fd 2
# before importing OCC so that C-level printf from OpenCASCADE goes to stderr,
# keeping stdout clean for the JSON result.  See _run_step_phase1_subprocess().
#
# pyobjc-framework-Cocoa must be installed in the OCC conda env so that
# _init_cocoa() in step_pipeline.py can call NSApplication.sharedApplication().
@app.route("/api/step/check", methods=["GET"])
def api_step_check():
    """Check if STEP pipeline dependencies (OpenCASCADE) are available."""
    from models.step_pipeline import check_occ_available
    available, error = check_occ_available()
    return jsonify({"available": available, "error": error})


_OCC_PYTHON_CACHE = None


def _occ_python_works(py):
    """True if interpreter ``py`` can import OCC (and Cocoa on macOS) cleanly.

    Probes in a subprocess rather than trusting that the file exists: an
    auto-activated ``.venv`` can shadow the conda ``occ`` env on PATH yet expose
    an importable-but-ABI-mismatched OCC (e.g. a 3.13-built extension loaded into
    a 3.10 interpreter) that SIGSEGVs the worker instead of failing cleanly. On
    macOS we also require ``AppKit`` because ``_init_cocoa()`` needs pyobjc; its
    absence is a reliable signal that this is the wrong environment.
    """
    import subprocess
    import sys
    probe = "import OCC.Core.STEPControl"
    if sys.platform == "darwin":
        probe += "; import AppKit"
    try:
        r = subprocess.run([py, "-c", probe], capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def _find_occ_python():
    """Return the path to a Python interpreter that can actually import OCC.

    Cross-platform: probes well-known (Ana)conda/Miniconda env locations on
    macOS, Linux and Windows. Each candidate is *verified* by importing OCC in a
    subprocess (see ``_occ_python_works``) — not merely checked for existence —
    because the current interpreter may shadow the conda ``occ`` env yet be
    unable to load pythonocc-core, which SIGSEGVs the worker. Result is cached.
    """
    global _OCC_PYTHON_CACHE
    if _OCC_PYTHON_CACHE is not None:
        return _OCC_PYTHON_CACHE

    import sys
    # 1. Current interpreter (works if Flask runs inside the occ env)
    candidates = [sys.executable]

    # 2. Well-known conda env locations, platform-aware
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        # Windows: env lives at <base>\envs\occ\python.exe (no bin/ subdir)
        bases = [
            os.path.join(home, "miniconda3"),
            os.path.join(home, "anaconda3"),
            os.path.join(home, "AppData", "Local", "miniconda3"),
            os.path.join(home, "AppData", "Local", "anaconda3"),
            r"C:\ProgramData\miniconda3",
            r"C:\ProgramData\anaconda3",
            r"C:\miniconda3",
            r"C:\anaconda3",
        ]
        for base in bases:
            candidates.append(os.path.join(base, "envs", "occ", "python.exe"))
    else:
        # macOS / Linux: env lives at <base>/envs/occ/bin/python3
        bases = [
            "/opt/miniconda3",
            "/opt/anaconda3",
            os.path.join(home, "miniconda3"),
            os.path.join(home, "anaconda3"),
        ]
        for base in bases:
            candidates.append(os.path.join(base, "envs", "occ", "bin", "python3"))

    checked = set()
    for py in candidates:
        if py in checked or not os.path.isfile(py):
            continue
        checked.add(py)
        if _occ_python_works(py):
            app.logger.info("STEP worker interpreter: %s", py)
            _OCC_PYTHON_CACHE = py
            return py

    app.logger.error(
        "No OCC-capable Python interpreter found. Probed (existing): %s. Falling "
        "back to %s — the STEP worker will likely SIGSEGV. Launch the app from "
        "the 'occ' conda env (e.g. %s).",
        [c for c in candidates if os.path.isfile(c)],
        sys.executable,
        os.path.join("/opt/miniconda3", "envs", "occ", "bin", "python3"),
    )
    _OCC_PYTHON_CACHE = sys.executable
    return sys.executable


def _parse_pipeline_settings(raw):
    """Parse the optional ``pipeline_settings`` request field.

    Accepts a dict (JSON body) or a JSON string (multipart form). Keeps only the
    leaves a client may change (pipeline.settings.CLIENT_SETTINGS); values are
    validated later by pipeline.settings.resolve_settings in the worker. Returns
    ``(settings or None, ignored "group.leaf" names)``; never raises on bad input.
    """
    from pipeline.settings import client_settings
    if raw is None or raw == "":
        return None, []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            app.logger.warning("Ignoring invalid pipeline_settings JSON")
            return None, ["pipeline_settings (invalid JSON)"]
    if not isinstance(raw, dict):
        return None, ["pipeline_settings (not an object)"]
    settings, ignored = client_settings(raw)
    if ignored:
        app.logger.info("pipeline_settings: ignored %s", ", ".join(ignored))
    return settings, ignored


def _detect_source(step_paths):
    """Read the first STEP file's header and guess the authoring tool / domain.

    Used only as a UI *hint* to pre-select a contact preset (e.g. ECAD boards
    model components a few hundredths of a mm above the PCB). Never authoritative.
    """
    if not step_paths:
        return {"authoring_tool": None, "suggested_preset": None}
    try:
        with open(step_paths[0], "r", errors="ignore") as fh:
            head = fh.read(4000).lower()
    except OSError:
        return {"authoring_tool": None, "suggested_preset": None}
    ecad_markers = ("kicad", "electronic assembly", "eagle", "altium", "pcbnew")
    if any(m in head for m in ecad_markers):
        return {"authoring_tool": "ECAD", "suggested_preset": "ecad"}
    return {"authoring_tool": None, "suggested_preset": None}


def _run_step_phase1_subprocess(step_paths, labels, manual_liaison=None,
                                contact_tol=None, pixel_tol=None, settings=None):
    """Run STEP Phase 1 in an isolated subprocess.

    OCC's Viewer3d requires Cocoa/OpenGL and crashes if run inside Flask's
    process. We invoke models/step_worker.py as a standalone script, passing
    the request as JSON via stdin and reading the result from stdout.

    ``settings`` is the optional pipeline_settings dict (see pipeline.settings);
    None runs the standard settings (pipeline.settings.STANDARD_SETTINGS). ``contact_tol`` / ``pixel_tol``
    take precedence over the settings equivalents.
    """
    import subprocess

    project_root = os.path.dirname(os.path.abspath(__file__))
    worker = os.path.join(project_root, "models", "step_worker.py")

    req_payload = json.dumps({
        "step_paths": step_paths,
        "labels": labels,
        "manual_liaison": manual_liaison,
        "contact_tol": contact_tol,
        "pixel_tol": pixel_tol,
        "settings": settings,
    })

    generic_error = {"success": False, "error": "Phase 1 failed. See server logs."}

    try:
        proc = subprocess.run(
            [_find_occ_python(), worker],
            input=req_payload,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=project_root,
        )
        if proc.returncode != 0:
            app.logger.error("STEP phase 1 worker exited %d: %s",
                             proc.returncode, proc.stderr)
            return generic_error
        if not proc.stdout.strip():
            app.logger.error("STEP phase 1 worker produced no stdout. stderr: %s",
                             proc.stderr)
            return generic_error
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        app.logger.error("STEP phase 1 timed out after 600s")
        return {"success": False, "error": "Phase 1 timed out (600s)."}
    except json.JSONDecodeError as e:
        app.logger.error("STEP phase 1 output not valid JSON: %s. stdout: %s stderr: %s",
                         e, proc.stdout[:500], proc.stderr)
        return generic_error
    except Exception:
        app.logger.exception("STEP phase 1 subprocess error")
        return generic_error


@app.route("/api/step/run", methods=["POST"])
def api_step_run():
    """Phase 1: extract parts, compute liaison matrix and interference matrices.

    Returns parts list + liaison_matrix + contacts + interference_matrices.
    The caller then shows the fastener-identification panel and calls
    /api/step/generate-tables once the user has tagged fasteners.

    Runs the standard settings (pipeline.settings.STANDARD_SETTINGS); an optional
    pipeline_settings field overrides single values, e.g. to try other settings.
    Only the values in pipeline.settings.CLIENT_SETTINGS are accepted. The result
    echoes the settings used (pipeline_settings_resolved), the dropped names
    (pipeline_settings_ignored) and invalid values (pipeline_settings_warnings);
    the returned matrices are final.

    Expects multipart form with:
      - step_files[]: one assembly STEP file (or multiple individual part STEPs)
      - labels[]: one label per file
      - pipeline_settings: optional JSON object (see pipeline.settings)
    OR JSON body with:
      - step_dir: directory containing STEP files
      - parts: [{file, label}, ...]
      - manual_liaison: optional pre-built liaison matrix
      - pipeline_settings: optional settings object
    """
    import tempfile

    # Handle file uploads
    if request.content_type and 'multipart' in request.content_type:
        files = request.files.getlist('step_files[]')
        labels = request.form.getlist('labels[]')

        if not files or not labels or len(files) != len(labels):
            return jsonify({"error": "Must provide matching step_files[] and labels[]"}), 400

        tmpdir = tempfile.mkdtemp(prefix="step_phase1_")
        tmpdir_abs = os.path.abspath(tmpdir)
        step_paths = []
        for i, f in enumerate(files):
            safe = secure_filename(f.filename) or f"upload_{i}.step"
            path = os.path.join(tmpdir, safe)
            # Defense in depth: reject any path that would escape tmpdir.
            if os.path.commonpath([tmpdir_abs, os.path.abspath(path)]) != tmpdir_abs:
                return jsonify({"error": "invalid filename"}), 400
            f.save(path)
            step_paths.append(path)

        manual_liaison_json = request.form.get('manual_liaison')
        manual_liaison = None
        if manual_liaison_json:
            try:
                manual_liaison = json.loads(manual_liaison_json)
            except json.JSONDecodeError as e:
                app.logger.warning("Ignoring invalid manual_liaison JSON: %s", e)

        settings, ignored = _parse_pipeline_settings(request.form.get('pipeline_settings'))
        result = _run_step_phase1_subprocess(step_paths, labels, manual_liaison,
                                             settings=settings)
        if isinstance(result, dict):
            result["source_hint"] = _detect_source(step_paths)
            result["pipeline_settings_ignored"] = ignored
        return jsonify(result)

    # Handle JSON body (local file paths)
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    parts_list = data.get("parts", [])
    step_dir   = data.get("step_dir", "")
    step_paths = [os.path.join(step_dir, p["file"]) for p in parts_list]
    labels     = [p["label"] for p in parts_list]
    manual_liaison = data.get("manual_liaison")

    settings, ignored = _parse_pipeline_settings(data.get("pipeline_settings"))
    result = _run_step_phase1_subprocess(step_paths, labels, manual_liaison, settings=settings)
    if isinstance(result, dict):
        result["source_hint"] = _detect_source(step_paths)
        result["pipeline_settings_ignored"] = ignored
    return jsonify(result)


@app.route("/api/step/generate-tables", methods=["POST"])
def api_step_generate_tables():
    """Phase 2: apply fastener semantics → connections + transitions.

    Expects JSON body:
      {
        "fastener_indices":      [int, ...],
        "part_labels":           [str, ...],
        "liaison_matrix":        [[int]],
        "interference_matrices": [[[int]]]
      }
    """
    from models.step_pipeline import generate_semantic_tables

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    fastener_indices      = data.get("fastener_indices", [])
    part_labels           = data.get("part_labels", [])
    liaison_matrix        = data.get("liaison_matrix")
    interference_matrices = data.get("interference_matrices")

    if liaison_matrix is None or interference_matrices is None or not part_labels:
        return jsonify({"error": "part_labels, liaison_matrix and "
                                 "interference_matrices are all required"}), 400

    settings, ignored = _parse_pipeline_settings(data.get("pipeline_settings"))
    result = generate_semantic_tables(
        fastener_indices=fastener_indices,
        part_labels=part_labels,
        liaison_matrix=liaison_matrix,
        interference_matrices=interference_matrices,
        precedence_rules=data.get("precedence_rules"),
        fastener_groups=data.get("fastener_groups"),
        separation_precedence=data.get("separation_precedence"),
        settings=settings,
        estimate_only=bool(data.get("estimate_only", False)),
    )
    if isinstance(result, dict) and ignored:
        result["pipeline_settings_ignored"] = ignored
    return jsonify(result)


@app.route("/api/step/task-names", methods=["POST"])
def api_step_task_names():
    """Automatic disassembly task names for a build payload (Studio review step).

    Expects the payload POST /api/products would get (product, components,
    connections, transitions, optional fastener_groups); returns
    {"task_names": {connection_id: name}} as Stage 2 writes them when no manual
    name is given. No database access.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        return jsonify({"task_names": auto_task_names(data)})
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"error": f"cannot derive task names: {e}"}), 400


@app.route("/api/step/suggest-groups", methods=["POST"])
def api_step_suggest_groups():
    """Suggest fastener groupings based on contact patterns."""
    from pipeline.fastener_detection import suggest_fastener_groups

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    groups = suggest_fastener_groups(
        fastener_indices=data.get("fastener_indices", []),
        part_labels=data.get("part_labels", []),
        liaison_matrix=data.get("liaison_matrix", []),
    )
    return jsonify({"suggested_groups": groups})


@app.route("/api/validate", methods=["POST"])
def api_validate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    ok, errors, warnings = validate_input(data)

    # Derive what would be created
    preview = {}
    if ok:
        from models.kg_builder import _derive_assembly_id, _DIS_SKILLS, _SKILL_NAMES
        comp_map = {c["partId"]: c for c in data["components"]}
        assemblies = set()
        for tr in data["transitions"]:
            from_parts = tr["from_parts"]
            assemblies.add(from_parts)
            if "results_in" in tr:
                for res in tr["results_in"]:
                    if len(res) > 1:
                        assemblies.add(res)
            else:
                removed = tr.get("removed_part", "")
                remaining = "".join(sorted(set(from_parts) - {removed}))
                if len(remaining) > 1:
                    assemblies.add(remaining)

        # Auto-deduce removed_part / broken_connection_id (mirrors kg_builder logic)
        conn_to_removed = {}
        for tr in data.get("transitions", []):
            results = tr.get("results_in", [])
            removed = tr.get("removed_part")
            if not removed:
                for chunk in results:
                    if len(chunk) == 1:
                        removed = chunk
                        break
            conn_id = tr.get("broken_connection_id")
            if removed and not conn_id:
                for conn in data.get("connections", []):
                    if conn.get("fastener_id") == removed:
                        conn_id = conn["id"]
                        break
                    elif removed in [conn.get("part1"), conn.get("part2")]:
                        other_part = conn["part2"] if conn["part1"] == removed else conn["part1"]
                        if any(other_part in chunk for chunk in results if chunk != removed):
                            conn_id = conn["id"]
                            break
            if conn_id and removed:
                if conn_id not in conn_to_removed:
                    conn_to_removed[conn_id] = removed

        # Derive tasks — strict priority naming, no assembly_task column
        task_preview = []
        for conn in data["connections"]:
            ct_id = conn["connectionType_id"]
            dis_skill_id = _DIS_SKILLS.get(ct_id)
            conn_id = conn["id"]

            # Priority A: Fastener
            if conn.get("fastener_id"):
                target_pid = conn["fastener_id"]
            # Priority B: Auto-deduced transition mapping
            elif conn_id in conn_to_removed:
                target_pid = conn_to_removed[conn_id]
            # Priority C: Strict fallback to part2 — NEVER part1
            else:
                target_pid = conn["part2"]

            part_info = comp_map.get(target_pid, {})
            part_name = part_info.get("name", target_pid)
            dis_name = f"{_SKILL_NAMES.get(dis_skill_id, 'Remove')} {part_name}"

            task_preview.append({
                "connection": conn_id,
                "parts": f"{conn['part1']} ↔ {conn['part2']}",
                "disassembly_task": dis_name,
                "dis_skill": dis_skill_id,
            })

        preview = {
            "components": len(data["components"]),
            "connections": len(data["connections"]),
            "transitions": len(data["transitions"]),
            "assemblies": len(assemblies),
            "tasks": len(data["connections"]),
            "derived_tasks": task_preview,
            "assembly_states": sorted([_derive_assembly_id(p) for p in assemblies]),
        }

    return jsonify({"valid": ok, "errors": errors, "warnings": warnings, "preview": preview})


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Debug mode is OFF by default — Werkzeug's debug console is an RCE vector.
    # Bind is 127.0.0.1 by default — opt-in to 0.0.0.0 via FLASK_HOST if you
    # really need network exposure.
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    host  = os.getenv("FLASK_HOST", "127.0.0.1")
    app.logger.info("KG Platform starting on http://%s:%d (debug=%s)",
                    host, config.PORT, debug)
    app.run(host=host, port=config.PORT, debug=debug, threaded=False)
