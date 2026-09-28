#!/usr/bin/env python3
"""Stratum WebUI — local tuning UI for the Stratum engine.

Thin local server (Python stdlib only, no dependencies) that shells out to
`stratum.exe --json` (the SDK CLI) and hands the JSON v2 report to a
self-contained HTML page. The UI renders the JSON only — the engine (C++) is
the single source of truth; no scoring/constraint rules are replicated in
Python or JavaScript.

Run:
    python server.py            # serve http://127.0.0.1:8765
    STRATUM_BIN=C:/path/stratum.exe python server.py
    StratumWebUI.exe             (frozen via PyInstaller; see packaging/)

Binary resolution (first match wins):
    1. $STRATUM_BIN
    2. <app dir>/bin/stratum.exe   (source: repo root; frozen: exe dir)
    3. stratum.exe on PATH
Version string is read from a VERSION.txt next to the binary (the SDK bundle
ships one at the bundle root) so /api/status can report the engine version
without a --version flag (the CLI has none).

Security posture: binds 127.0.0.1 only; subprocess uses a list argv (no
shell); the only CLI flags reachable from the UI are a fixed whitelist
(param flags + --lock + --optimize-3mf profile); models go to a private temp
dir. No code from the uploaded model is ever executed. In addition, every
request must carry a local Host header (127.0.0.1/localhost/[::1] — blocks
DNS-rebinding reads/writes), and POSTs to /api/* must send the custom
X-Stratum-UI: 1 header (browsers cannot attach custom headers to cross-site
simple requests, and preflights die on 501 — do_OPTIONS is absent on
purpose), which blocks cross-site request forgery from web pages.
"""

import atexit
import glob
import io
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, quote, urlparse

HOST = "127.0.0.1"


def _validated_int(raw, lo, hi):
    """int(raw) within [lo, hi] or None. Startup env values are validated
    once here so a typo fails fast in main() with a friendly message,
    not as an import-time traceback (PORT) or a misleading per-analyze
    502 (GRID — the engine rejects out-of-domain values at run time)."""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


# UI version (semver-ish, single source). Exposed via /api/status and the
# banner so bug reports from a distributed build are diagnosable — before
# this, two installs of different vintages were indistinguishable (D1
# groundwork, iter 65). Bump on user-visible change; the engine version is
# reported separately (it moves independently).
# 0.11.0 — ROADMAP v0.11 (light professional theme visual refresh).
# 0.8.1 — engine 0.24 full-surface pass: render-gap batch (fast_mode/
#         filament_slots/input_overrides/printability/thermal_speed/weld/
#         ZZ-SPR/Tsai-Wu/mesh_quality/precond/skipped_reasons/fatigue-life/
#         Weibull numbers/rec confidence/candidate provenance), appearance/
#         rheology/est-error/resolution-check phases, voxel-vote+precond,
#         retraction/travel/wipe send-value rows, prony + heatmap-bins +
#         per-run grid, cal-time/mass estimator calibration, --base-profile,
#         supports/stress-modifier artifact downloads, --apply-orca mode.
# 0.8.0 — Stratum 0.24.0 integration: schema v3 gate, --schema-driven param
#         surface, layer_height/z_ratio/fill_angle sliders, machine/validate/
#         repair/fast flags, heatmap viewer, real progress (ROADMAP v0.8).
# 0.7.0 — ROADMAP v0.7 (one-click presets, simple-mode "0 参数" entry).
# 0.6.0 — ROADMAP v0.6 (UI v3 visual + auto real-time analysis) complete;
# bumped from 0.5.0 which had drifted behind the milestone (iter 67).
# 0.12.0 — UX interaction alignment (task-language panel titles, grouped
# sliders, collapsible analysis options, mode switch, run-delta chips).
# 0.13.0 — task-flow layout (simple-mode single column + step strip,
# sticky verdict bar, dirty-count chip, preset-comparison opened to simple).
# 0.14.0 — risk disclosure: summary risk card aggregates phase_a.risks +
# warnings (severity-ranked), geometric risk list collapses behind a
# count/max-severity toggle, verdict-gated default (⚠/❌ expand, ✅ fold),
# engine severity 1..5 shown verbatim (was clamped to 3).
# 0.15.0 — one-click zh⇄en UI language toggle (header button, persisted);
# engine-authored report text stays Chinese by design (single source of
# truth); 500 errors now carry the real exception for diagnosis.
# 0.16.0 — engine 0.26 suggestion channel (motivation badges + suppression
# disclosures, forward-compatible tokens), self-contained HTML report
# snapshot export (client-side Blob, zero new endpoints), run-history
# per-row param diff + SF/score inline-SVG sparklines, persistent rolling
# log (%LOCALAPPDATA%\StratumWebUI\logs, 5MB×3) + 「打开日志目录」button.
# 0.17.0 — snapshot embeds the model preview as of the export click
# (preserveDrawingBuffer capture, honest degrade line, zh-mode snapshot
# text fixed), 3MF live preview via GET /api/model-mesh (stdlib zip+XML
# triangle soup in the stlParse buffer shape; capped, token-gated,
# refuse-not-truncate) feeding the existing WebGL pipeline.
UI_VERSION = "0.17.0"

# PORT is consumed by the bind call (int); GRID is consumed by argv (kept as
# the original string — a list argv with an int element raises TypeError and
# every analyze would 500).
PORT_RAW = os.environ.get("STRATUM_UI_PORT", "8765")
PORT = _validated_int(PORT_RAW, 1, 65535)  # 0 would bind an ephemeral port but print/open :0
GRID_RAW = os.environ.get("STRATUM_UI_GRID", "16")
# 4..128 is the engine's own domain (its validation error text; probed on
# 0.21.0: grid=0/1/1000/65536 all "Invalid --grid; expected integer 4..128").
GRID = GRID_RAW if _validated_int(GRID_RAW, 4, 128) is not None else None
# Session cap: FIFO eviction of the oldest upload (this is not LRU — reads
# do not refresh). 32 default ≈ 64 MB max body × 32 ≈ 2 GB temp-disk bound.
MAX_SESSIONS_RAW = os.environ.get("STRATUM_UI_MAX_SESSIONS", "32")
MAX_SESSIONS = _validated_int(MAX_SESSIONS_RAW, 1, 10 ** 9)
# Phase D (buckling/fatigue/fracture/Weibull) costs ~35ms extra on the beam
# fixture; escape hatch for older engine builds without the flag (probed
# against SDK 0.21.0: accepted for stl, 3mf and combined with
# --compare-profiles, all rc=0).
PHASE_D = os.environ.get("STRATUM_UI_PHASE_D", "1") != "0"
# Engine concurrency: every heavy engine invocation (analyze/batch/export/
# preview) takes one slot; requests beyond the queue bound are rejected 503
# instead of queueing unboundedly (a 16-tab worst case of 180s runs each
# would leave the tail waiting >20min with no feedback).
MAX_CONCURRENCY_RAW = os.environ.get("STRATUM_UI_MAX_CONCURRENCY", "2")
MAX_CONCURRENCY = _validated_int(MAX_CONCURRENCY_RAW, 1, 16)
MAX_QUEUE_RAW = os.environ.get("STRATUM_UI_MAX_QUEUE", "8")
MAX_QUEUE = _validated_int(MAX_QUEUE_RAW, 0, 64)
# History retention per session (entries are ~1-2KB summaries; the full
# last_report JSON is NOT capped by this). Floor is 2: a cap of 1 would make
# the A/B diff permanently unusable (it needs two entries).
MAX_HISTORY_RAW = os.environ.get("STRATUM_UI_MAX_HISTORY", "10")
MAX_HISTORY = _validated_int(MAX_HISTORY_RAW, 2, 100)
# Schema gate: the engine report carries schema_version (0.21.0 emits int 2;
# 0.22.0+ emits int 3 — v3 moved the five uncertainty fields to scalar +
# *_envelope twins, docs/schema/report-v3.md; report.js numEnv handles both
# shapes). Exact numeric match against SUPPORTED_SCHEMA, per request — a
# future schema that renames fields must fail loud here, not misrender
# silently (ROADMAP v0.4c). Missing/None/unparseable → reject (fail-loud
# default); escape valve for hypothetical pre-schema engines mirrors PHASE_D.
SUPPORTED_SCHEMA = (2, 3)
ALLOW_ANY_SCHEMA = os.environ.get("STRATUM_UI_ALLOW_ANY_SCHEMA", "0") == "1"


def schema_supported(report):
    if not isinstance(report, dict):
        return False
    v = report.get("schema_version")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    # exact numeric equality — no int() truncation (2.9 must NOT pass as 2)
    return v in SUPPORTED_SCHEMA


# Status markers (engine 0.22+): when cancellation is honored at a stage
# boundary the engine writes {"status":"cancelled", ...} into the --json file
# and exits 130; when --validate strict/paranoid refuses the input topology it
# writes {"status":"validation_refused", "validation":{tier,findings}, ...}
# and exits 1 (findings entries: {code, fatal, count, hint}). Both carry
# schema_version, so the schema gate alone cannot catch them — `status` is
# the discriminator and must be checked BEFORE any rendering.
REPORT_MARKER_STATUSES = ("validation_refused", "cancelled")


def load_report_marker(path):
    """Return the parsed marker dict when `path` holds a status-marker JSON
    rather than a normal report; None when missing/unparseable/normal. Never
    raises — callers fall through to the generic rc!=0 error path."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    status = data.get("status")
    if isinstance(status, str) and status in REPORT_MARKER_STATUSES:
        return data
    return None


def refusal_text(marker):
    """User-facing one-liner for a validation_refused marker (shared by the
    single-analyze and per-batch-combo paths)."""
    validation = marker.get("validation")
    tier = validation.get("tier") if isinstance(validation, dict) else None
    if isinstance(tier, str):
        return ("输入拓扑校验拒绝（--validate %s）——"
                "改用 standard 档可继续分析（仅披露、不拒绝）" % tier)
    return "输入拓扑校验拒绝——改用 standard 档可继续分析（仅披露、不拒绝）"


def send_marker_response(handler, marker):
    """Translate an engine status marker into its HTTP response at the trust
    boundary: cancelled → 502 (same message as the local cancel path),
    validation_refused → 422 with the structured validation findings the UI
    renders inline. Unknown statuses fail loud with the raw marker."""
    status = marker.get("status")
    if status == "cancelled":
        _send_json(handler, 502, {"ok": False, "error": "已取消"})
        return
    if status == "validation_refused":
        validation = marker.get("validation")
        topo = marker.get("mesh_topology")
        _send_json(handler, 422, {
            "ok": False, "error": refusal_text(marker),
            "status": "validation_refused",
            "validation": validation if isinstance(validation, dict) else {},
            "mesh_topology": topo if isinstance(topo, dict) else {}})
        return
    _send_json(handler, 502, {"ok": False,
                              "error": "引擎返回未知状态标记: %r" % status})

# Frozen layout (PyInstaller onedir): resources live in _internal/ next to the
# exe; the app dir (for bin/stratum.exe) is the exe's own directory.
FROZEN = bool(getattr(sys, "frozen", False))
HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else HERE
RESOURCE_DIR = getattr(sys, "_MEIPASS", None) or HERE
INDEX_PATH = os.path.join(RESOURCE_DIR, "index.html")
# zero-build UI split: index.html + classic <script src> modules served from
# RESOURCE_DIR (same layout as the PyInstaller datas). Explicit whitelist —
# no directory traversal, no content-type guessing.
UI_STATIC = {
    "/report.js": ("report.js", "application/javascript; charset=utf-8"),
    "/stl-preview.js": ("stl-preview.js",
                        "application/javascript; charset=utf-8"),
}
WORK_DIR = tempfile.mkdtemp(prefix="stratum_ui_")
# belt for sys.exit-style exits (a FORCE kill — TerminateProcess — can never
# run in-process cleanup; those orphans are reclaimed by the startup sweep in
# main() instead). Runs during interpreter shutdown: ignore_errors mandatory.
atexit.register(shutil.rmtree, WORK_DIR, ignore_errors=True)

# v0.16 persistent log: stderr stays the live channel; this rolling file is
# the post-mortem one (bug reports from a distributed install need the
# request/engine trail after the console is gone). %LOCALAPPDATA%\StratumWebUI\
# logs, 5 MB x 3 files (stratum-webui.log + .1 + .2). STRATUM_UI_LOG_DIR and
# STRATUM_UI_LOG_MAX_BYTES exist so the test suite never touches the real
# profile dir. Any setup failure degrades to console-only — the file is a
# bonus channel, never a startup blocker (same contract as the heatmap).
LOG_DIR = os.environ.get(
    "STRATUM_UI_LOG_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                 "StratumWebUI", "logs"))
LOG_MAX_BYTES = _validated_int(
    os.environ.get("STRATUM_UI_LOG_MAX_BYTES", str(5 * 1024 * 1024)),
    1000, 100 * 1024 * 1024) or (5 * 1024 * 1024)
LOG_FILE = None  # None = file logging degraded/off


class _TeeStderr(object):
    """sys.stderr wrapper: every existing stderr write lands in the console
    AND the rolling file — zero call-site changes, engine subprocess stderr
    (captured via PIPE before it ever reaches sys.stderr) stays out."""

    def __init__(self, orig, logger):
        self._orig = orig
        self._logger = logger

    def write(self, s):
        try:
            self._orig.write(s)
        except Exception:
            pass  # console gone (window closed): file copy still matters
        if s and s.strip():
            try:
                self._logger.critical(s.rstrip("\r\n"))
            except Exception:
                pass  # disk full / file held open elsewhere — console copy went
        return len(s)

    def flush(self):
        try:
            self._orig.flush()
        except Exception:
            pass

    def __getattr__(self, name):  # isatty / encoding / fileno passthrough
        return getattr(self._orig, name)


def _setup_file_logging():
    global LOG_FILE
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        # raiseExceptions=False: on a rollover failure (another instance
        # holds the file — Windows rename needs exclusive access) logging's
        # handleError would write to sys.stderr, which is the tee, which
        # logs again → unbounded recursion. Silently dropping that one
        # record is the honest degradation for a bonus channel.
        logging.raiseExceptions = False
        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, "stratum-webui.log"),
            maxBytes=LOG_MAX_BYTES, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger = logging.getLogger("stratum.webui.file")
        logger.addHandler(handler)
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False
        LOG_FILE = handler.baseFilename
        sys.stderr = _TeeStderr(sys.stderr, logger)
    except Exception:
        LOG_FILE = None
# Installed in main(), NOT at import time: tests import this module for
# helpers (_sweep_orphan_workdirs) and must not touch the real profile dir;
# only an actually-running server logs to file.
# owner tag for the startup orphan sweep (dead-owner dirs get reclaimed;
# note: token*/out_token* evict globs never match "owner.pid")
try:
    with open(os.path.join(WORK_DIR, "owner.pid"), "w", encoding="ascii") as fh:
        fh.write(str(os.getpid()))
except OSError:
    pass  # sweep degrades to the 24h staleness rule for this instance


def _pid_alive(pid):
    """Windows-only liveness check via OpenProcess (os.kill on Windows only
    offers TerminateProcess-flavoured signals — using it to probe would KILL
    the process). Returns True when unsure (a false 'alive' only skips a
    sweep; a false 'dead' would delete a live instance's dir)."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == 259  # STILL_ACTIVE
            return False
        finally:
            k32.CloseHandle(h)
    except Exception:
        return True


def _sweep_orphan_workdirs():
    """Startup reclaim of stratum_ui_* temp dirs whose owning process is dead
    (force-killed instances can never clean up themselves — refuter-verified
    iter 40: SIGTERM/SIGBREAK handlers never fire on real kill paths). Never
    touches a dir owned by a LIVE instance; untagged dirs (pre-feature
    orphans) need >24h staleness."""
    now = time.time()
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "stratum_ui_*")):
        if os.path.abspath(d) == os.path.abspath(WORK_DIR):
            continue
        pid_file = os.path.join(d, "owner.pid")
        pid = None
        try:
            with open(pid_file, "r", encoding="ascii") as fh:
                pid = int(fh.read().strip())
        except (OSError, ValueError):
            pid = None
        if pid is not None:
            if _pid_alive(pid):
                continue  # live sibling instance
        else:
            try:
                if now - os.path.getmtime(d) < 24 * 3600:
                    continue  # untagged but recent: might be mid-creation
            except OSError:
                continue
        shutil.rmtree(d, ignore_errors=True)
_session_lock = threading.Lock()
# Insertion-ordered (FIFO eviction at MAX_SESSIONS). Values also carry the
# token itself so report/output paths can be keyed without re-trusting the
# client-supplied name later.
_sessions = {}  # token -> {"token", "path", "name", "is_3mf"}


def _evict_oldest_session_locked():
    """Drop the oldest session (dict entry + its token-keyed files). Caller
    must hold _session_lock. Accepted race: an in-flight analyze of the
    evicted session may 502 (engine holds the file handle on Windows and the
    file may be undeletable — the orphan is cleaned by the shutdown rmtree).
    token is a 16-hex prefix, so globbing token* cannot hit other sessions."""
    old_tok = next(iter(_sessions))
    old = _sessions.pop(old_tok)
    for pattern in (old_tok + "*", "out_" + old_tok + "*"):
        for p in glob.glob(os.path.join(WORK_DIR, pattern)):
            try:
                os.remove(p)
            except OSError:
                pass  # engine still holds it; shutdown rmtree is the backstop
    return old


# ---- v0.17 3MF live preview: mesh extraction for /api/model-mesh ----------
# Preview cap REFUSES instead of truncating (the STL preview truncates): the
# payload is a JSON triangle soup, a 5e5-tri response is already ~100 MB, and
# silently shipping a decimated mesh would invite treating the preview as
# geometry truth — it is a pure bonus that makes no geometry claims (§0).
MODEL_MESH_MAX_TRIS = 500000
# bounds the ElementTree parse (a hostile XML could carry millions of vertex
# elements with no triangles); the file is the user's own localhost upload
# and expat (py3.11) already refuses entity amplification, so this is a
# work-bound guard, not a security boundary.
MODEL_MESH_MAX_XML_BYTES = 64 * 1024 * 1024


def extract_3mf_mesh(path):
    """Triangles from a 3MF's 3D/3dmodel.model as flat
    [ax,ay,az, bx,by,bz, cx,cy,cz, ...] pos/nrm lists — the same buffer
    shape the browser's stlParse produces for STL, so one WebGL pipeline
    renders both. Returns {"tris", "pos", "nrm", "dropped"}; raises
    ValueError with an honest user-facing message on any broken input
    (do_GET has no ValueError wrapper — the endpoint catches and 400s).

    Defensive by design: exporters vary the XML namespace, meshes may be
    split over multiple <object>s (unioned here; build-item transforms are
    deliberately ignored — no geometry claims), and each <mesh> owns its
    vertex table because triangle indices are mesh-relative."""
    with zipfile.ZipFile(path) as zf:
        model_names = [n for n in zf.namelist()
                       if n.lower().endswith(".model")]
        if not model_names:
            raise ValueError("3MF 内无 3D 模型数据（缺少 .model 部件），无法预览")
        model_names.sort(key=lambda n: (n.lower() != "3d/3dmodel.model", n))
        xml_bytes = zf.read(model_names[0])
    if len(xml_bytes) > MODEL_MESH_MAX_XML_BYTES:
        raise ValueError("3MF 模型 XML 超过 %d MB，预览不可用"
                         % (MODEL_MESH_MAX_XML_BYTES // (1024 * 1024)))
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError("3MF 模型 XML 解析失败: %s" % exc)

    def local(tag):
        # namespace-agnostic: exporters emit the 2015/02 core ns, variants,
        # or none at all — match on the local name only
        return tag.rpartition("}")[2] if isinstance(tag, str) else ""

    verts = []
    pos = []
    nrm = []
    dropped = 0
    for el in root.iter():
        t = local(el.tag)
        if t == "mesh" or t == "vertices":
            # a shared table would silently weld mesh2's low indices onto
            # mesh1's tail — indices are relative to the enclosing mesh
            verts = []
        elif t == "vertex":
            try:
                verts.append((float(el.get("x")), float(el.get("y")),
                              float(el.get("z"))))
            except (TypeError, ValueError):
                verts.append(None)  # hole: any triangle referencing it drops
        elif t == "triangle":
            if len(pos) // 9 >= MODEL_MESH_MAX_TRIS:
                raise ValueError("3MF 网格超过预览上限（%d 三角），未生成预览"
                                 % MODEL_MESH_MAX_TRIS)
            try:
                a = verts[int(el.get("v1"))]
                b = verts[int(el.get("v2"))]
                c = verts[int(el.get("v3"))]
            except (IndexError, TypeError, ValueError):
                dropped += 1
                continue
            if a is None or b is None or c is None or not (
                    math.isfinite(a[0]) and math.isfinite(a[1]) and math.isfinite(a[2])
                    and math.isfinite(b[0]) and math.isfinite(b[1]) and math.isfinite(b[2])
                    and math.isfinite(c[0]) and math.isfinite(c[1]) and math.isfinite(c[2])):
                # mirror the browser stlParse discipline: skip the tri, keep
                # counting, so bbox/GPU never see NaN (float() accepts "nan")
                dropped += 1
                continue
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            if ln > 0:
                nx, ny, nz = nx / ln, ny / ln, nz / ln
            else:
                nx, ny, nz = 0.0, 0.0, 1.0  # degenerate tri: any unit normal
            pos.extend((a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]))
            nrm.extend((round(nx, 6), round(ny, 6), round(nz, 6)) * 3)
    return {"tris": len(pos) // 9, "pos": pos, "nrm": nrm, "dropped": dropped}

# ---------------------------------------------------------------------------
# Binary resolution + version
# ---------------------------------------------------------------------------

# persisted user-set engine path (first-run wizard). STRATUM_UI_CONFIG
# override exists so tests never touch the real home directory.
CONFIG_PATH = os.environ.get(
    "STRATUM_UI_CONFIG",
    os.path.join(os.path.expanduser("~"), ".stratum-webui.json"))


def _load_config_binary():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        p = cfg.get("binary")
        if isinstance(p, str) and os.path.isfile(p) and not _reject_remote_path(p):
            return p
    except (OSError, ValueError, AttributeError):
        return None  # missing/corrupt config is never fatal


def _reject_remote_path(path):
    """A UNC path (\\\\server\\share\\...) makes the server execute an engine
    binary from the network on every analyze — code-execution surface that a
    local tuning tool should not gain silently (mapped network DRIVE letters
    are indistinguishable from local ones without WMI; documented limit).
    Applied at both producers of the persisted path: the wizard and the
    config loader (hand-edited config)."""
    return os.name == "nt" and path.startswith("\\\\")


def _looks_like_stratum(path):
    """Validate a user-supplied engine path: must exist and print the CLI
    usage when run with no args. stdin=DEVNULL — an interactive binary
    (e.g. a REPL) must not hang the request until timeout."""
    if not os.path.isfile(path):
        return False, "文件不存在"
    try:
        proc = subprocess.run([path], capture_output=True, timeout=10,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return False, "无法运行: %s" % exc
    text = (proc.stderr + proc.stdout).decode("utf-8", "replace")
    if "Usage:" in text and "--pattern" in text:
        return True, None
    return False, "该文件不输出 Stratum usage（不是 stratum.exe？）"


def resolve_binary():
    env = os.environ.get("STRATUM_BIN")
    if env and os.path.isfile(env):
        return os.path.abspath(env)
    local = os.path.join(APP_DIR, "bin", "stratum.exe")
    if os.path.isfile(local):
        return os.path.abspath(local)
    # first-run wizard's persisted choice — beats PATH (a PATH hit would
    # silently override what the user explicitly configured)
    cfg = _load_config_binary()
    if cfg:
        return os.path.abspath(cfg)
    which = shutil.which("stratum.exe")
    if which and not _reject_remote_path(which):
        return which
    return None


BINARY = resolve_binary()


# --schema probe cache (engine 0.22+): `stratum --schema` prints machine-
# readable flag domains as JSON, rc=0 — value ranges, enum values, lockable
# parameters and the engine's own version string. The version field beats the
# SDK VERSION.txt, which describes the bundle the binary SHIPPED in and can
# lag a synced binary (repo carried 0.21.0 text next to a 0.24.0 exe — the
# 2026-08-28 drift this fixes). Filled by _probe_surface (import time and
# /api/set-binary re-probe).
_SCHEMA_CACHE = {"binary": None, "doc": None, "version": None}


def engine_version(binary):
    """Engine version string. Preferred source: the --schema probe's own
    `version` field (exact, matches the running binary). Falls back to the
    SDK VERSION.txt regex, then 'unknown' — never fails."""
    if binary and _SCHEMA_CACHE["binary"] == binary and _SCHEMA_CACHE["version"]:
        return _SCHEMA_CACHE["version"]
    if not binary:
        return "unknown"
    candidates = [
        os.path.join(os.path.dirname(binary), "..", "VERSION.txt"),
        os.path.join(os.path.dirname(binary), "VERSION.txt"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    m = re.search(r"Stratum SDK ([0-9]+\.[0-9]+\.[0-9]+)", fh.read())
                if m:
                    return m.group(1)
            except OSError:
                pass
    return "unknown"


# ---------------------------------------------------------------------------
# Stratum invocation
# ---------------------------------------------------------------------------

def run_stratum(args, timeout=180):
    """Run stratum.exe with list argv (never a shell string). Returns
    (rc, stdout, stderr)."""
    try:
        proc = subprocess.run([BINARY] + args,
                              capture_output=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, b"", b"stratum.exe not found"
    except subprocess.TimeoutExpired:
        return 124, b"", b"stratum.exe timed out"


# ---- cancellable analyze runner (ROADMAP v0.3a) ---------------------------
_inflight = {}   # token -> {"proc": Popen, "gen": int}
_inflight_lock = threading.Lock()
_gen_counter = [0]
# Test hook: when set, the cancelable runner launches a deterministic sleep
# process instead of the engine (the real engine finishes in ~0.03s on the
# fixtures — far too short a window for a non-flaky cancel E2E).
_ANALYZE_DELAY = _validated_int(os.environ.get("STRATUM_UI_ANALYZE_DELAY", "0"),
                                 0, 3600) or 0
CANCELLED_RC = -999  # internal: killed via /api/cancel, not a crash/timeout


# import must survive a bad env (tests import server as a module); main()
# refuses to SERVE on invalid values, the `or 2` here is only the import-time
# placeholder (env-validation-symmetry + iter 6 T14 precedent)
_engine_sem = threading.Semaphore(MAX_CONCURRENCY if MAX_CONCURRENCY is not None else 2)
_queue_state = threading.Lock()
_waiting = [0]


class _BusyError(Exception):
    pass


class _engine_slot(object):
    """One slot per heavy engine run. Rejects with _BusyError once more than
    MAX_QUEUE requests are already waiting (bounded queue — the alternative
    is unbounded silent queueing behind 180s runs)."""
    def __enter__(self):
        with _queue_state:
            if _waiting[0] >= MAX_QUEUE:
                raise _BusyError()
            _waiting[0] += 1
        _engine_sem.acquire()
        with _queue_state:
            _waiting[0] -= 1
        return self

    def __exit__(self, *exc):
        _engine_sem.release()
        return False


# gens whose cancel arrived before the run finished (bounded: cleaned in the
# runner's finally when the run leaves the inflight table)
_cancelled_gens = set()


def run_analyze_cancelable(args, token):
    """Run an analyze argv as a cancellable Popen. Returns (rc, out, err).
    rc == CANCELLED_RC only when /api/cancel killed THIS run (explicit flag —
    a bare rc!=0 with empty stderr cannot distinguish kill/crash/timeout)."""
    with _inflight_lock:
        _gen_counter[0] += 1
        gen = _gen_counter[0]
    with _engine_slot():
        # queued-cancel recheck: a /api/cancel that arrived while we were
        # waiting for the slot must not run the engine at all
        with _inflight_lock:
            if token in _batch_cancel:
                _batch_cancel.discard(token)
                return CANCELLED_RC, b"", b"cancelled"
        if _ANALYZE_DELAY:
            # deterministic slow runner (cancel/progress E2E): also emits one
            # --progress-json NDJSON line so GET /api/progress can be polled
            # mid-run without a real long-running engine solve
            argv = [sys.executable, "-c",
                    "import sys, time; "
                    "sys.stderr.write('{\"type\": \"progress\", \"stage\": \"fem\", \"pct\": 42}\\n'); "
                    "sys.stderr.flush(); time.sleep(%d)" % _ANALYZE_DELAY]
        else:
            argv = [BINARY] + args
        return _run_proc_with_inflight(argv, token, gen)
    # unreachable


# per-token last engine progress (--progress-json NDJSON, engine 0.22+).
# Written by the stderr pump thread, read by GET /api/progress; entries are
# removed when the run leaves the inflight table (no stale percentages).
_progress = {}


def _parse_progress_line(raw):
    """Parse one --progress-json NDJSON line into {"stage","pct"}; None for
    anything else (non-JSON, other event types, malformed fields). The
    engine is our own subprocess but the line is still shape-checked before
    it reaches the API surface."""
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "progress":
        return None
    stage, pct = obj.get("stage"), obj.get("pct")
    if (not isinstance(stage, str) or isinstance(pct, bool)
            or not isinstance(pct, (int, float))):
        return None
    return {"stage": stage, "pct": int(pct)}


def _run_proc_with_inflight(argv, token, gen):
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with _inflight_lock:
        _inflight[token] = {"proc": proc, "gen": gen}
    err_chunks = []
    timed_out = []

    def _pump_stderr():
        # --progress-json emits per-line-flushed NDJSON on stderr; pumping
        # (instead of the old communicate()) is what makes the progress
        # channel exist at all. Full stderr is still reassembled for the
        # caller (error texts, engine console).
        try:
            for raw in iter(proc.stderr.readline, b""):
                err_chunks.append(raw)
                m = _parse_progress_line(raw)
                if m is not None:
                    with _inflight_lock:
                        # only the CURRENT generation may write this token's
                        # progress (a stale pump from a previous killed run
                        # must not overwrite the next run's percentage)
                        if _inflight.get(token, {}).get("gen") == gen:
                            _progress[token] = m
        except (OSError, ValueError):
            pass  # pipe closed on kill — remaining stderr is best-effort

    pump = threading.Thread(target=_pump_stderr, daemon=True)
    pump.start()

    def _on_timeout():
        timed_out.append(True)
        try:
            proc.kill()
        except OSError:
            pass
    timer = threading.Timer(180, _on_timeout)
    timer.start()
    was_cancelled = False
    try:
        out = proc.stdout.read()  # until EOF (kill/exit both end it)
        rc = proc.wait()
    finally:
        timer.cancel()
        pump.join(timeout=5)
        with _inflight_lock:
            was_cancelled = gen in _cancelled_gens  # read BEFORE discard
            cur = _inflight.get(token)
            if cur and cur["gen"] == gen:
                del _inflight[token]
            _progress.pop(token, None)
            _cancelled_gens.discard(gen)
    if was_cancelled:
        return CANCELLED_RC, b"", b"cancelled"
    if timed_out:
        return 124, out, b"".join(err_chunks)
    return rc, out, b"".join(err_chunks)


# per-token "a cancel was requested" sticky flag — a cancel arriving in the
# gap BETWEEN two batch combos (no in-flight proc) must still stop the batch
_batch_cancel = set()


def cancel_analyze(token):
    """Kill the in-flight analyze for token, if any. Idempotent: answers
    cancelled=false when nothing is running (a late cancel after completion
    races nothing). terminate() on Windows is a hard kill (TerminateProcess),
    which is what we want for a C++ engine."""
    with _inflight_lock:
        cur = _inflight.get(token)
        _batch_cancel.add(token)
        if not cur:
            return False
        _cancelled_gens.add(cur["gen"])
        try:
            cur["proc"].terminate()
        except OSError:
            pass  # already gone — the cancelled-gen flag still marks the rc
        return True


# bonus flags: stripped+retried once on old engines that reject them (their
# error text is "unrecognized argument: <flag>", so the match is on the FULL
# flag string — a bare "orca"/"orient" substring would false-positive on the
# engine's own "orientation" output). --progress-json/--heatmap-json are v0.8
# bonus channels (0.22+): losing them on an old engine degrades gracefully.
# --appearance/--rheology join in v0.8.1 (0.24-era diagnostics phases), and
# the two solver diagnostics likewise; --voxel-vote is an env-path bool but
# belongs to the same degrade-don't-fail family. --precond is deliberately
# NOT in this list: it is an explicit user choice, and an engine too old to
# know it should fail loud rather than silently run the default.
_FALLBACK_FLAGS = ("--orca-suggest", "--optimize-orient", "--explain",
                   "--progress-json", "--heatmap-json", "--appearance",
                   "--rheology", "--est-error-profile", "--resolution-check",
                   "--voxel-vote", "--heatmap-bins")


def run_analyze_with_fallback(args, run=None):
    """Run an analyze argv; on an old engine without a bonus flag (its error
    names the flag) retry once without it — suggestions/orientation are
    bonuses and must not break the analysis. `run` lets the caller inject the
    cancellable runner (token-bound)."""
    run = run or run_stratum
    rc, out, err = run(args)
    if rc not in (0, CANCELLED_RC):
        text = err.decode("utf-8", "replace")
        drop = [f for f in _FALLBACK_FLAGS
                if f in args and ("unrecognized argument: %s" % f) in text]
        if drop:
            args = [a for a in args if a not in drop]
            rc, out, err = run(args)
    return rc, out, err


# ---------------------------------------------------------------------------
# Param surface (mirrors the CLI flags; the engine hard-rejects invalid values)
# ---------------------------------------------------------------------------
# The engine is the single source of truth for its own enum surface, so the
# lists below are only a FALLBACK: at import time the server runs the binary
# with no args and parses the usage text (stderr, rc=1) for the real enums
# (ROADMAP E2: 0.21.0 shipped 10 patterns vs 7 hardcoded). A parse that loses
# the UI defaults or barely overlaps the fallback is treated as a broken
# parse (truncation/rename), not a valid new surface.
# name -> (CLI flag, kind) ; kind in {int, float, select}
# Defined BEFORE _probe_surface's module-level call — the lock-surface filter
# below needs it (module-level-def-order, loop-journal iter 5).
PARAM_FLAGS = {
    "walls": ("--walls", "int"),
    "infill": ("--infill", "float"),              # percent on the CLI
    "pattern": ("--pattern", "select"),
    "material": ("--material", "select"),
    "nozzle_diameter": ("--nozzle", "float"),
    "nozzle_temperature": ("--nozzle-temp", "float"),
    "bed_temperature": ("--bed-temp", "float"),
    "print_speed": ("--speed", "float"),
    "cooling_fan": ("--cooling", "float"),
    # v0.8 (engine 0.22+ surface): layer height gained a real CLI flag (the
    # value also PINS the dimension engine-side, same semantics as
    # --lock layer_height); z-ratio and CLT fill-angle are verdict-affecting
    # physics knobs with input echoes (z_strength_ratio /
    # requested+applied_fill_angle_deg).
    "layer_height": ("--layer-height", "float"),
    "z_ratio": ("--z-ratio", "float"),
    "fill_angle": ("--fill-angle", "float"),
}

FALLBACK_PATTERNS = ["line", "gyroid", "cubic", "triangles", "honeycomb", "grid", "rectilinear"]
FALLBACK_MATERIALS = ["PLA", "PETG", "ABS", "CUSTOM"]
FALLBACK_LOADS = ["compression", "bending", "torsion", "cantilever"]
# v0.8 select surfaces (engine --schema enum_flags; fallbacks mirror 0.24.0)
FALLBACK_AXES = ["x", "y", "z"]
FALLBACK_MACHINES = ["A250", "A350", "Artisan", "J1", "U1", "A1", "A1mini",
                     "P1P", "P1S", "X1", "X1C"]
FALLBACK_VALIDATE_TIERS = ["minimal", "standard", "strict", "paranoid"]
FALLBACK_PRECOND = ["ic0", "jacobi"]
PATTERN_DEFAULT = "gyroid"
MATERIAL_DEFAULT = "PLA"
LOAD_DEFAULT = "compression"


def parse_usage_enums(text):
    """Extract the pattern/material enums from the CLI no-arg usage text.
    Handles the multi-line enum with a trailing "(legacy ...)" note. Returns
    (patterns, materials, filtered) — an enum is None when not found or when
    fewer than 3 tokens survive; `filtered` lists tokens dropped by the
    charset filter (future engine tokens must not disappear silently)."""
    def enum_after(flag, tokre):
        m = re.search(re.escape(flag) + r"\s*<[^>]*>\s*(.*?)(?:\(|\n\s*\n|$)",
                      text, re.S)
        if not m:
            return None, []
        good, dropped = [], []
        for t in m.group(1).split("|"):
            t = t.strip()
            if t and re.fullmatch(tokre, t):
                good.append(t)
            elif t:
                dropped.append(t)
        return (good if len(good) >= 3 else None), dropped
    patterns, d1 = enum_after("--pattern", r"[a-z0-9][a-z0-9\-]*")
    materials, d2 = enum_after("--material", r"[A-Z][A-Z0-9\-]*")
    loads, d3 = enum_after("--load", r"[a-z]+")
    return patterns, materials, loads, d1 + d2 + d3


def parse_usage_locks(text):
    """Extract the core lockable-name list from the --lock usage section.
    The list spans multiple lines ("Core: walls infill layer_height\\n
    pattern ..."), so the charset must include \\s (a single-line [a-z_ ]
    class dies at the first newline — probed on real 0.21.0 usage).
    Returns a name list or None when the section is missing/truncated."""
    m = re.search(r"Core:\s*([a-z_\s]+?)\.", text)
    if not m:
        return None
    names = m.group(1).split()
    # guard: the section must be intact (has layer_height and a real list)
    return names if "layer_height" in names and len(names) >= 5 else None


# Extra lock surface (core lockables that have NO param slider row in this
# UI). Static fallback mirrors the 0.21.0 usage minus what became a slider in
# v0.8 (layer_height). The live list comes from the --schema lockable table
# (or the usage probe on old engines) minus PARAM_FLAGS; it includes the
# engine's full Orca-key lock surface (brim_width, support_angle, ...).
# "load" is excluded — it has its own select in the env panel with a lock
# checkbox.
FALLBACK_EXTRA_LOCKS = ["outer_wall_speed", "extrusion_stability",
                        "retraction_length", "retraction_speed", "wipe",
                        "travel_speed"]


def probe_schema(binary, timeout=5):
    """Run `stratum --schema` and return (doc, version). (None, None) when
    the binary is missing, the flag is unsupported (pre-0.22 engine), or the
    output is not the expected JSON shape — callers fall back to the usage
    probe. Semi-trusted input (our own binary's stdout): shape-checked before
    any use, never exec'd."""
    if not binary:
        return None, None
    try:
        rc, out, _err = run_stratum(["--schema"], timeout=timeout)
        if rc != 0:
            return None, None
        doc = json.loads(out.decode("utf-8", "replace"))
    except Exception:
        return None, None
    if not isinstance(doc, dict) or not isinstance(doc.get("value_flags"), list):
        return None, None
    ver = doc.get("version")
    return doc, (ver if isinstance(ver, str) else None)


def _enum_from_schema(doc, flag, fallback, default):
    """Pull one enum list from --schema enum_flags with the same guards as
    the usage probe: well-typed strings, must contain the UI default and
    overlap the fallback by >=2 (a renamed/truncated enum degrades to the
    fallback instead of serving garbage). Returns (values|None, source)."""
    for e in doc.get("enum_flags") or []:
        if isinstance(e, dict) and e.get("name") == flag:
            values = e.get("values")
            if (isinstance(values, list) and len(values) >= 3
                    and all(isinstance(v, str) for v in values)
                    and default in values
                    and len(set(values) & set(fallback)) >= 2):
                return values, "engine-schema"
            return None, "fallback"
    return None, "fallback"


def _probe_surface():
    """One-shot subprocess probe at import. Never raises: a broken binary
    (unexecutable, AV quarantine, ...) must degrade to the fallback lists,
    not kill the server at startup. Preferred source: `--schema` JSON
    (0.22+; exact lists, no text parsing). Legacy fallback: no-arg usage
    text regex (pre-0.22 engines)."""
    if BINARY is None:
        return (FALLBACK_PATTERNS, FALLBACK_MATERIALS, FALLBACK_LOADS,
                "fallback", "fallback", "fallback", [],
                FALLBACK_EXTRA_LOCKS, "fallback")
    global _SCHEMA_CACHE
    doc, ver = probe_schema(BINARY)
    _SCHEMA_CACHE = {"binary": BINARY if doc is not None else None,
                     "doc": doc, "version": ver}
    if doc is not None:
        patterns, psrc = _enum_from_schema(doc, "--pattern",
                                           FALLBACK_PATTERNS, PATTERN_DEFAULT)
        materials, msrc = _enum_from_schema(doc, "--material",
                                            FALLBACK_MATERIALS, MATERIAL_DEFAULT)
        loads, lsrc = _enum_from_schema(doc, "--load",
                                        FALLBACK_LOADS, LOAD_DEFAULT)
        if patterns and materials and loads:
            locks = doc.get("lockable_parameters")
            extra = None
            if (isinstance(locks, list) and len(locks) >= 5
                    and all(isinstance(n, str) for n in locks)):
                param_names = set(PARAM_FLAGS) | {"load"}
                extra = [n for n in locks if n not in param_names]
            return (patterns, materials, loads, psrc, msrc, lsrc,
                    [],  # structured JSON: no charset-filtered tokens
                    extra if extra is not None else FALLBACK_EXTRA_LOCKS,
                    "engine-schema" if extra is not None else "fallback")
        # partial schema parse: degrade to the usage probe below
    try:
        rc, out, err = run_stratum([], timeout=5)
        text = err.decode("utf-8", "replace") + out.decode("utf-8", "replace")
        patterns, materials, loads, filtered = parse_usage_enums(text)
        core_locks = parse_usage_locks(text)
    except Exception:
        return (FALLBACK_PATTERNS, FALLBACK_MATERIALS, FALLBACK_LOADS,
                "fallback", "fallback", "fallback", [],
                FALLBACK_EXTRA_LOCKS, "fallback")
    # Guards: the served list must contain the UI default and overlap the
    # fallback by >=2, else the parse silently truncated or renamed the enum.
    if patterns is None or PATTERN_DEFAULT not in patterns \
            or len(set(patterns) & set(FALLBACK_PATTERNS)) < 2:
        patterns = None
    if materials is None or MATERIAL_DEFAULT not in materials \
            or len(set(materials) & set(FALLBACK_MATERIALS)) < 2:
        materials = None
    # --load guard: len>=3 tokens keeps a truncated parse out
    if loads is None or LOAD_DEFAULT not in loads \
            or len(set(loads) & set(FALLBACK_LOADS)) < 2:
        loads = None
    pats = patterns if patterns is not None else FALLBACK_PATTERNS
    mats = materials if materials is not None else FALLBACK_MATERIALS
    lds = loads if loads is not None else FALLBACK_LOADS
    param_names = set(PARAM_FLAGS) | {"load"}
    extra = ([n for n in core_locks if n not in param_names]
             if core_locks is not None else None)
    return (pats, mats, lds,
            "engine-usage" if patterns is not None else "fallback",
            "engine-usage" if materials is not None else "fallback",
            "engine-usage" if loads is not None else "fallback",
            filtered,
            extra if extra is not None else FALLBACK_EXTRA_LOCKS,
            "engine-usage" if extra is not None else "fallback")


(PATTERNS, MATERIALS, LOAD_TYPES, PATTERNS_SOURCE, MATERIALS_SOURCE,
 LOADS_SOURCE, SURFACE_FILTERED, EXTRA_LOCKS, EXTRA_LOCKS_SOURCE) = _probe_surface()

# "default" mirrors the engine's built-in defaults (shown when the engine
# reports no baseline of its own, e.g. for STL input): 0.4mm nozzle, 2 walls,
# 15% gyroid infill, PLA, 200/60°C, 50mm/s, fan 100%.
PARAM_META = [
    {"name": "walls", "label": "壁数", "kind": "int",
     "min": 1, "max": 20, "step": 1, "unit": "", "hint": "1-20", "default": 2},
    {"name": "infill", "label": "填充率", "kind": "float",
     "min": 0, "max": 100, "step": 1, "unit": "%", "hint": "0-100 %", "default": 15},
    {"name": "pattern", "label": "填充图案", "kind": "select",
     "options": PATTERNS, "unit": "", "default": PATTERN_DEFAULT},
    {"name": "material", "label": "材料", "kind": "select",
     "options": MATERIALS, "unit": "", "default": MATERIAL_DEFAULT},
    {"name": "nozzle_diameter", "label": "喷嘴直径", "kind": "float",
     "min": 0.1, "max": 2.0, "step": 0.05, "unit": "mm", "hint": "0.1-2.0 mm",
     "default": 0.4},
    {"name": "nozzle_temperature", "label": "喷嘴温度", "kind": "float",
     "min": 150, "max": 350, "step": 5, "unit": "°C", "hint": "150-350 °C",
     "default": 200},
    {"name": "bed_temperature", "label": "热床温度", "kind": "float",
     "min": 0, "max": 200, "step": 5, "unit": "°C", "hint": "0-200 °C",
     "default": 60},
    {"name": "print_speed", "label": "打印速度", "kind": "float",
     "min": 1, "max": 1000, "step": 1, "unit": "mm/s", "hint": "1-1000 mm/s",
     "default": 50},
    {"name": "cooling_fan", "label": "冷却风扇", "kind": "float",
     "min": 0, "max": 100, "step": 5, "unit": "%", "hint": "0-100 %",
     "default": 100},
    # v0.8 rows (engine 0.22+): domains from --schema value_flags via
    # _apply_schema_domains below; the values here mirror 0.24.0 exactly and
    # stay as the offline fallback.
    {"name": "layer_height", "label": "层高", "kind": "float",
     "min": 0.01, "max": 5.0, "step": 0.02, "unit": "mm",
     "hint": "0.01-5.0 mm；设值即钉住该维（搜索/写回不漂移）", "default": 0.2},
    {"name": "z_ratio", "label": "层间强度比 Z/XY", "kind": "float",
     "min": 0.1, "max": 2.0, "step": 0.01, "unit": "",
     "hint": "0.1-2.0；不设=随材料（PLA 0.46 / PETG 0.55 / ABS 0.50）",
     "default": 0.46},
    {"name": "fill_angle", "label": "填充角（CLT）", "kind": "float",
     "min": 0, "max": 360, "step": 5, "unit": "°",
     "hint": "0-360 °；0=不旋转（回显 applied_fill_angle_deg）", "default": 0},
]

# Select surfaces beyond pattern/material/load, resolved from the --schema
# probe (exact) with hardcoded fallbacks. Recomputed by _set_binary after a
# wizard re-probe.
def _enum_values(doc, flag, fallback):
    """Pull one enum list from a --schema doc; fallback when the doc is
    missing or the entry is malformed (well-typed strings, >=2 values)."""
    if doc:
        for e in doc.get("enum_flags") or []:
            if isinstance(e, dict) and e.get("name") == flag:
                values = e.get("values")
                if (isinstance(values, list) and len(values) >= 2
                        and all(isinstance(v, str) for v in values)):
                    return values
    return fallback


def _refresh_select_surfaces():
    """Recompute the schema-derived select surfaces. Returns the new tuple —
    callers rebind the module globals (import time and /api/set-binary)."""
    doc = _SCHEMA_CACHE.get("doc")
    return (_enum_values(doc, "--axis", FALLBACK_AXES),
            _enum_values(doc, "--machine", FALLBACK_MACHINES),
            _enum_values(doc, "--validate", FALLBACK_VALIDATE_TIERS),
            _enum_values(doc, "--precond", FALLBACK_PRECOND))


(AXIS_VALUES, MACHINE_VALUES, VALIDATE_TIERS, PRECOND_VALUES) = \
    _refresh_select_surfaces()


def _apply_schema_domains():
    """Overlay exact numeric domains from the --schema probe onto the v0.8
    param rows. The 9 legacy rows keep their authored domains (identical to
    --schema as of 0.24.0, verified 2026-08-28) — overlaying them too would
    need a drift channel for zero current benefit. Mutates PARAM_META rows in
    place (they are dicts); safe to call again after a wizard re-probe."""
    doc = _SCHEMA_CACHE.get("doc")
    if not doc:
        return
    domains = {}
    for f in doc.get("value_flags") or []:
        if (isinstance(f, dict) and isinstance(f.get("name"), str)
                and isinstance(f.get("min"), (int, float))
                and isinstance(f.get("max"), (int, float))
                and f["max"] > f["min"]):
            domains[f["name"]] = f
    overlay = {"layer_height": "--layer-height",
               "z_ratio": "--z-ratio",
               "fill_angle": "--fill-angle"}
    for row in PARAM_META:
        flag = overlay.get(row["name"])
        d = domains.get(flag) if flag else None
        if d:
            row["min"], row["max"] = d["min"], d["max"]


_apply_schema_domains()

PROFILES = ["safe", "balanced", "fast", "appearance"]

# One-click tuning presets — the simple-mode "0 参数" entry for new users.
# Each preset sets the 9 core print params PLUS layer_height (which the
# engine tiers themselves vary). z_ratio is deliberately NOT preset-authored:
# it is material-relative (PLA 0.46 / PETG 0.55 / ABS 0.50) and pinning one
# value would override the material default the preset's own material choice
# implies. fill_angle likewise stays untouched (0 = no rotation). Values are
# server-authored constants inside the PARAM_META ranges (product defaults,
# engine decides the real outcome). Served via /api/params and applied
# client-side through the ordinary analyze path (no dedicated endpoint).
PRESETS = [
    {"name": "safe", "label": "安全",
     "desc": "厚壁高填充，强度优先",
     "params": {"walls": 5, "infill": 40, "pattern": "tri-hexagon",
                "material": "PLA", "nozzle_diameter": 0.4,
                "nozzle_temperature": 210, "bed_temperature": 65,
                "print_speed": 30, "cooling_fan": 60, "layer_height": 0.16}},
    {"name": "balanced", "label": "均衡",
     "desc": "接近引擎默认，强度与速度兼顾",
     "params": {"walls": 3, "infill": 20, "pattern": "gyroid",
                "material": "PLA", "nozzle_diameter": 0.4,
                "nozzle_temperature": 200, "bed_temperature": 60,
                "print_speed": 50, "cooling_fan": 100, "layer_height": 0.2}},
    {"name": "fast", "label": "高速",
     "desc": "低填充高速度，出件最快",
     "params": {"walls": 2, "infill": 10, "pattern": "gyroid",
                "material": "PLA", "nozzle_diameter": 0.4,
                "nozzle_temperature": 210, "bed_temperature": 60,
                "print_speed": 80, "cooling_fan": 100, "layer_height": 0.28}},
    {"name": "appearance", "label": "外观",
     "desc": "慢速细表面，外观优先",
     "params": {"walls": 4, "infill": 15, "pattern": "gyroid",
                "material": "PLA", "nozzle_diameter": 0.4,
                "nozzle_temperature": 205, "bed_temperature": 60,
                "print_speed": 40, "cooling_fan": 80, "layer_height": 0.12}},
]


def presets_for(materials, patterns):
    """Return PRESETS with each param checked against PARAM_META and the live
    enums — a fallback probe (engine offline) must never serve a select value
    the UI cannot hold, and numeric values stay inside the slider ranges.
    Server-authored constants, so this is drift-proofing, not user-input
    fixing. Returns new dicts; never mutates PRESETS."""
    out = []
    for p in PRESETS:
        params = {}
        for name, value in p["params"].items():
            meta = next((m for m in PARAM_META if m["name"] == name), None)
            if meta is None:
                continue  # unknown key: drop (defensive; PRESETS is ours)
            if meta["kind"] == "select":
                options = {"pattern": patterns, "material": materials}[name]
                value = value if value in options else meta["default"]
            elif not (meta["min"] <= value <= meta["max"]):
                value = meta["default"]
            params[name] = value
        out.append({"name": p["name"], "label": p["label"],
                    "desc": p["desc"], "params": params})
    return out


# v0.9 "applyable" — server-derived, executable view of the engine's
# recommendation items. Name-space evidence (0.24.0 real runs,
# test_data/real3mf-results/report.json:645-647): observed
# recommendations.items[].parameter (nozzle_diameter / print_speed /
# cooling_fan) is IDENTITY with its PARAM_META slider key. Engine 0.25.0
# alignment (docs/webui-alignment-response-2026-09.md, 2026-09-02):
# recommendations.items[].parameter uses the engine-native keys walls /
# infill / pattern (the wall_count / infill_pct / infill_pattern rename
# space belongs to process_optimization only — those keys are correctly
# rejected below), infill is percent (0-100; fraction appears only in the
# input echo input.infill_density), and a real walls/infill sample now
# exists (test_data/webui-alignment-2026-09/report-walls-infill-
# suggestions.json: walls 2->3 P1, infill 15->35 P1). The whitelist below is
# therefore the FULL PARAM_META numeric-slider face; selects stay excluded
# (their action space is change, no real sample yet — pattern/material).
# Everything below is UI-side orchestration (ROADMAP red line 2 allows it):
# filtering by the UI's OWN control semantics (slider range/step/no-op) —
# no engine scoring/clamping rule is copied or re-implemented.
_APPLYABLE_ACTIONS = ("increase", "decrease")  # observed action space (0.24.0)


def applyable_suggestions(report):
    """Project recommendations.items onto the UI slider face. Returns one
    entry per engine item, SAME order (the engine order is its priority
    order — never re-sorted), so applyable[i] pairs with items[i] on the
    client. applicable:false entries carry the reason. Never raises: any
    surprise shape degrades to applicable:false — bonus channel, same
    discipline as the heatmap passthrough (must not fail a good analysis).
    Duplicates on one UI key keep the FIRST applicable hit (earlier engine
    order = higher priority)."""
    out = []
    if not isinstance(report, dict):
        return out
    rec = report.get("recommendations")
    items = rec.get("items") if isinstance(rec, dict) else None
    if not isinstance(items, list):
        return out
    seen_keys = set()
    for it in items:
        entry = {"parameter": None, "action": None, "current_value": None,
                 "recommended_value": None, "priority": None,
                 "applicable": False, "reason": "", "ui_key": None}
        out.append(entry)
        if not isinstance(it, dict):
            entry["reason"] = "建议项形状异常"
            continue
        name = it.get("parameter")
        val = it.get("recommended_value")
        cur = it.get("current_value")
        if isinstance(name, str):
            entry["parameter"] = name
        if isinstance(it.get("action"), str):
            entry["action"] = it["action"]
        for k, v in (("current_value", cur), ("recommended_value", val)):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                entry[k] = v
        if isinstance(it.get("priority"), int) and not isinstance(it["priority"], bool):
            entry["priority"] = it["priority"]
        # PARAM_META numeric-slider face: engine-native key + numeric slider
        # (selects have no real sample yet — see block comment above). Keys
        # from other engine spaces (wall_count/infill_pct/infill_pattern) are
        # not PARAM_META names and land here as reasoned refusals.
        meta = next((m for m in PARAM_META
                     if m["name"] == name and m["kind"] != "select"), None)
        if meta is None:
            entry["reason"] = "参数不可一键应用（UI 无对应数值滑杆）"
            continue
        if entry["action"] not in _APPLYABLE_ACTIONS:
            entry["reason"] = "非设值型建议（action=%s）" % (entry["action"],)
            continue
        if entry["recommended_value"] is None:
            entry["reason"] = "建议值缺失"
            continue
        if (entry["current_value"] is not None
                and entry["recommended_value"] == entry["current_value"]):
            entry["reason"] = "已等于当前值"
            continue
        # step pre-snap: a range input snaps to step on assignment and the
        # client sends the control value — snapping HERE keeps the listed
        # value identical to the value that will actually be sent. This is
        # the UI's own control semantics, not an engine rule.
        val = entry["recommended_value"]
        snapped = meta["min"] + round((val - meta["min"]) / meta["step"]) * meta["step"]
        snapped = round(snapped, 6)  # 0.05/0.02-step float drift
        if not (meta["min"] <= snapped <= meta["max"]):
            entry["reason"] = ("建议值 %s 超出滑杆域 %s..%s"
                               % (val, meta["min"], meta["max"]))
            continue
        if meta["name"] in seen_keys:
            entry["reason"] = "同参数多项建议，保留引擎顺序在前的一项"
            continue
        seen_keys.add(meta["name"])
        entry["applicable"] = True
        entry["ui_key"] = meta["name"]
        entry["recommended_value"] = snapped
    return out


# Physical / environmental inputs (analyze-only; engine domains are enforced
# by the engine itself — the ranges below are only for argv hygiene and the
# UI sliders, sourced from engine validation-error texts probed 2026-08-18:
# --force 0..1e6 (0 legal), --service-time 0..1e10 s, --service-temp
# -100..250, --humidity 0..100, --fatigue-cycles 1..1e9, --anneal-hours
# 0..1e5). --load is whitelisted HERE because the engine only warns and
# silently falls back to compression on unknown values (rc=0) — the user's
# intent would be silently dropped otherwise.
ENV_FLAGS = {
    "force": ("--force", "float"),
    "load": ("--load", "select"),
    "service_time_s": ("--service-time", "float"),
    "service_temp_c": ("--service-temp", "float"),
    "ambient_temp_c": ("--ambient-temp", "float"),
    "humidity": ("--humidity", "float"),
    "anneal_hours": ("--anneal-hours", "float"),
    "fatigue_cycles": ("--fatigue-cycles", "float"),
    # --- v0.8 (engine 0.22+ surface) ---
    # --layer-time: consumed by the Orca weld-bond model + AutoSuggester
    # layer-bonding; echoed consumption-gated as input.layer_time_s.
    "layer_time_s": ("--layer-time", "float"),
    # --axis: torsion axis override (input.torsion_axis echo is null unless
    # load=torsion — the engine ignores it otherwise, with a console warning).
    "torsion_axis": ("--axis", "select"),
    # --machine: firmware-limits clamp identity (speed suggestions and
    # optimize candidates clamp; disclosure in report machine_limits.clamps).
    # Absent = 3MF printer_model auto-detect — the UI sends nothing then.
    "machine": ("--machine", "select"),
    # --validate: input-topology ENFORCEMENT tier (standard = audit only;
    # strict/paranoid refuse → status:"validation_refused" marker, rendered
    # inline in 「分析结果」).
    "validate_tier": ("--validate", "select"),
    # bool flags (no value in argv; validated_env only passes True through)
    "repair_orientation": ("--repair-orientation", "bool"),
    "fast": ("--fast", "bool"),
    # --- v0.8.1 solver/mesh robustness switches ---
    # --voxel-vote: three-axis parity voting voxel fill for cracked/non-
    # watertight meshes (triples voxelization cost — disclosed in the hint).
    # No JSON block of its own; an old engine without the flag fails loud.
    "voxel_vote": ("--voxel-vote", "bool"),
    # --precond: CG preconditioner identity (ic0 default; Jacobi fallback on
    # non-positive pivots is automatic and disclosed via
    # phase_b.diagnostics.preconditioner/precond_fallback_count). "" = auto:
    # nothing is sent, same convention as the machine select.
    "precond": ("--precond", "select"),
    # --- v0.8.1 send-value channels WITHOUT engine echo ---
    # retraction/travel/wipe feed the Orca suggestion + appearance channels
    # and setting a value PINS the dimension engine-side (same semantics as
    # --lock), but the report's input block does NOT echo them — the UI sends
    # them as-is and the row hints say the value is unverifiable from the
    # report. Ranges below are argv hygiene from --schema value_flags.
    "retraction_length": ("--retraction-length", "float"),
    "retraction_speed": ("--retraction-speed", "float"),
    "travel_speed": ("--travel-speed", "float"),
    "wipe": ("--wipe", "bool"),
    # --- v0.8.1 misc knobs ---
    # --prony-duration: Prony load duration for the long-term (viscoelastic)
    # modulus; requested/applied echo in input.requested_prony_duration_s /
    # applied_prony_duration_s (echo-synced like other 「环境与载荷」 numeric rows).
    "prony_duration_s": ("--prony-duration", "float"),
    # --- v0.8.1 estimator calibration (iter 582 surface) ---
    # --cal-time/--cal-mass: measured print time / material mass from a real
    # run; the engine derives multiplicative calibration factors for its
    # time/mass estimates and discloses them in the top-level `calibration`
    # block (applied/reason/time_factor/mass_factor/measured_*/predicted_*/
    # notes). Engine domains 1..1e6 s / 0.01..1e6 g (its own range errors).
    "cal_time_s": ("--cal-time", "float"),
    "cal_mass_g": ("--cal-mass", "float"),
}

# select whitelists, resolved at call time (the lists rebind after a wizard
# re-probe, so indirection through lambdas is required)
_ENV_SELECT_ALLOWED = {
    "load": lambda: LOAD_TYPES,
    "torsion_axis": lambda: AXIS_VALUES,
    "machine": lambda: MACHINE_VALUES,
    "validate_tier": lambda: VALIDATE_TIERS,
    "precond": lambda: PRECOND_VALUES,
}


def validated_env(env):
    """Type-gate + normalize the env dict from the analyze body. Numbers
    only (bool rejected explicitly — bool is an int subclass), whole floats
    narrowed to int for clean argv ("50" not "50.0"); selects are whitelisted
    against the live engine enums (the engine either rejects unknown values
    or — worse for --load — silently falls back, so the UI must not forward
    them); bool flags only pass `True` through. Returns a new dict."""
    if not isinstance(env, dict):
        raise ValueError("env 必须是对象")
    out = {}
    for name, value in env.items():
        spec = ENV_FLAGS.get(name)
        if spec is None:
            raise ValueError("unknown env: %r" % name)
        kind = spec[1]
        if kind == "select":
            allowed = _ENV_SELECT_ALLOWED[name]()
            if value not in allowed:
                raise ValueError("%s 必须是 %s 之一" % (name, "|".join(allowed)))
            out[name] = value
            continue
        if kind == "bool":
            if value is not True:
                raise ValueError("%s 仅接受 true" % name)
            out[name] = True
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("env.%s 必须是数值" % name)
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        out[name] = value
    return out


BASE_PROFILE_MAX_BYTES = 256 * 1024


def validated_base_profile(raw):
    """Validate the client-supplied base-profile JSON TEXT (untrusted input
    crossing a trust boundary — same harness as uploads): size cap, must
    parse, must be a JSON object. Returns the original text; the file write
    happens at the call site into the private temp dir. The engine remains
    the authority on which KEYS it accepts (unknown keys → engine rc=1 with
    its own message, surfaced as-is)."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("base_profile 需为非空 JSON 文本")
    if len(raw.encode("utf-8")) > BASE_PROFILE_MAX_BYTES:
        raise ValueError("base_profile 过大（上限 256 KB）")
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError("base_profile 不是有效 JSON: %s" % exc)
    if not isinstance(parsed, dict):
        raise ValueError("base_profile 需为 JSON 对象（flat Orca project_settings 键）")
    return raw


def build_analyze_args(model_path, params, locks, compare, json_path, env=None,
                       orient=False, heatmap_path=None, appearance=False,
                       rheology=False, est_error=False, res_check=False,
                       grid=None, heatmap_bins=None, base_profile_path=None):
    """Build the whitelisted argv for an analyze/compare run."""
    # --explain: engine prints per-suggestion trust grounding (kb_module /
    # trust_source) to stdout only — JSON is byte-identical with/without it
    # (probed 0.21.0, iter 62). The UI shows engine console verbatim, so this
    # is the only wiring needed; no render-side contract.
    # grid: per-run override (int 4..128, pre-validated by callers); None =
    # the server-level STRATUM_UI_GRID default. Kept a string in argv (a list
    # argv with an int element raises TypeError).
    args = [model_path, "--phase-c", "--grid",
            str(grid) if grid else GRID, "--orca-suggest", "--explain"]
    # progress channel: NDJSON stage boundaries on stderr → GET /api/progress
    # (v0.8, engine 0.22+; old engines drop it via the fallback retry)
    args.append("--progress-json")
    if orient:
        args.append("--optimize-orient")
    # v0.8.1 diagnostics phases: --appearance implies --phase-c (already on);
    # both blocks are absent from the report entirely when the flag is not
    # passed (absent-not-null), so the render side gates on block presence.
    if appearance:
        args.append("--appearance")
    if rheology:
        args.append("--rheology")
    # v0.8.1 solver diagnostics (opt-in; --resolution-check re-runs the FEM
    # at 2x grid → roughly doubles solve time, --est-error-profile probes
    # several dims; both only meaningful with FEM, which analyze always runs)
    if est_error:
        args.append("--est-error-profile")
    if res_check:
        args.append("--resolution-check")
    if PHASE_D:
        args.append("--phase-d")
    if compare:
        args.append("--compare-profiles")
    for name, value in params.items():
        flag = PARAM_FLAGS.get(name)
        if flag is None:
            raise ValueError("unknown parameter: %r" % name)
        args.append(flag[0])
        args.append(str(value))
    for name, value in (env or {}).items():
        flag, kind = ENV_FLAGS[name]
        args.append(flag)
        if kind != "bool":
            args.append(str(value))  # bool flags are bare (--fast, no value)
    if locks:
        args.append("--lock")
        args.append(",".join(locks))
    if base_profile_path:
        # external baseline profile (v0.8.1): flat Orca project_settings
        # keys, precedence CLI > 3MF > base profile > default. The path
        # points at a server-written temp file holding the pre-validated
        # JSON text (the engine is the authority on the KEYS it accepts).
        args.append("--base-profile")
        args.append(base_profile_path)
    if heatmap_path:
        # spatial risk/stress heatmap (v0.8, engine 0.22+): FEM von Mises +
        # Phase A risk regions aggregated into a sparse bins³ grid; the UI
        # overlays it on the 3D preview. Bonus channel — stripped+retried on
        # old engines (see _FALLBACK_FLAGS).
        args.append("--heatmap-json")
        args.append(heatmap_path)
        # bins-per-axis knob (v0.8.1; --schema value_flags 2..64). Callers
        # pre-validate; None/16-equivalent = engine default, flag not sent.
        if heatmap_bins:
            args.append("--heatmap-bins")
            args.append(str(heatmap_bins))
    args.append("--json")
    args.append(json_path)
    return args


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

# A client that went away (AbortController cancel, tab close) surfaces as a
# ConnectionError on the next socket write. Both win32 ConnectionAbortedError
# and POSIX BrokenPipeError are ConnectionError subclasses, so one except
# covers them. Swallowing is the correct terminal state — the response has no
# reader — and keeps socketserver from printing a traceback per cancel
# (loop-journal iter 17 backlog). The try must span send_response..end_headers
# too: headers are only flushed to the socket inside end_headers, so a
# disconnect during the header phase raises there, not at wfile.write.
def _send_json(handler, code, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except ConnectionError:
        pass


def _read_body(handler, limit_mb=64):
    length = int(handler.headers.get("Content-Length", 0))
    if length <= 0 or length > limit_mb * 1024 * 1024:
        raise ValueError("bad content-length")
    return handler.rfile.read(length)


def _read_json_body(handler):
    raw = _read_body(handler)
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid JSON body: %s" % exc)


def _sidecar_header(path):
    """Build the X-Stratum-Sidecar summary from the engine's own audit JSON
    (pure passthrough of engine counts — no judgement here). None when the
    sidecar is missing/unreadable: the header is a bonus, never a failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            wb = (json.load(fh).get("writeback")) or {}
        if wb.get("applied_count") is None:
            return None
        return "applied=%s skipped=%s verified=%s" % (
            wb.get("applied_count"), wb.get("skipped_count"),
            str(bool(wb.get("verified"))).lower())
    except (OSError, ValueError, AttributeError):
        return None


def _history_summary(report):
    """Flatten a report into the small dict the history list / A-B diff
    consume. Envelope values {nominal,lo,hi} reduce to nominal (the diff
    compares medians only — the UI says so); missing fields stay None."""
    def nom(v):
        if isinstance(v, dict):
            # complete envelopes are {nominal, lo, hi} (probed 0.21.0: all 5
            # envelope fields, all shapes). A dict WITHOUT nominal must not
            # pass through raw — the UI's numEnv would render Number(dict)
            # as "NaN" (string-through-num-helper, display side).
            return v.get("nominal")
        return v
    rec = report.get("recommendations") or {}
    pb = report.get("phase_b") or {}
    pd = report.get("phase_d") or {}
    return {
        "overall_score": rec.get("overall_score"),
        "safety_factor": nom(pb.get("safety_factor")),
        "max_stress_mpa": nom(pb.get("max_stress_mpa")),
        "load_adequacy": pb.get("load_adequacy"),
        "buckling_sf": nom(pd.get("buckling_safety_factor")),
        "fatigue_sf": nom(pd.get("fatigue_safety_factor")),
        "fatigue_infinite_life": pd.get("fatigue_infinite_life"),
        "weibull_grade": pd.get("weibull_grade"),
    }


class StratumHandler(BaseHTTPRequestHandler):
    server_version = "StratumWebUI/0.1"

    # ---- request gate (CSRF / DNS rebinding) -------------------------------

    LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

    def _origin_allowed(self):
        """Local Host header + (for POSTs) the UI marker header.

        Host: after DNS rebinding the browser still sends the attacker's
        host, so an allowlist is the standard effective defense. X-Stratum-UI:
        cross-site simple requests (form/no-cors/sendBeacon) cannot carry
        custom headers, and a cross-site fetch that tries triggers a CORS
        preflight that dies on 501 (do_OPTIONS is intentionally absent)."""
        host = urlparse("//" + (self.headers.get("Host") or "")).hostname
        if not host or host.lower() not in self.LOCAL_HOSTS:
            return False
        if self.command == "POST" and self.headers.get("X-Stratum-UI") != "1":
            return False
        return True

    def _deny_origin(self):
        _send_json(self, 403, {"ok": False, "error":
            "仅接受本机访问（用 http://127.0.0.1 打开；API POST 需带 X-Stratum-UI: 1 头）"})

    # ---- helpers ----------------------------------------------------------

    def _log(self, msg):
        sys.stderr.write("[%s] %s\n" % (self.address_string(), msg))

    # ---- GET ---------------------------------------------------------------

    def do_GET(self):
        if not self._origin_allowed():
            self._deny_origin()
            return
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._serve_index()
        elif path in UI_STATIC:
            self._serve_ui_static(path)
        elif path == "/api/status":
            _send_json(self, 200, {
                "ok": True,
                "ui_version": UI_VERSION,
                "engine_version": engine_version(BINARY),
                "binary": BINARY or None,
                "binary_found": BINARY is not None,
                "grid": GRID,
                "schema_supported": list(SUPPORTED_SCHEMA),
                "allow_any_schema": ALLOW_ANY_SCHEMA,
                "history_cap": MAX_HISTORY,
                # v0.16: where the rolling log lives (tooltip copy); null
                # when file logging degraded to console-only
                "log_dir": LOG_DIR if LOG_FILE else None,
            })
        elif path == "/api/params":
            # surface tells the UI where the enums came from; drift lists
            # engine entries missing from the fallback (informational).
            _send_json(self, 200, {
                "ok": True,
                "params": PARAM_META,
                "materials": MATERIALS,
                "patterns": PATTERNS,
                "profiles": PROFILES,
                "presets": presets_for(MATERIALS, PATTERNS),
                "surface": {
                    "patterns_source": PATTERNS_SOURCE,
                    "materials_source": MATERIALS_SOURCE,
                    "loads_source": LOADS_SOURCE,
                    "loads": LOAD_TYPES,
                    "extra_locks": EXTRA_LOCKS,
                    "extra_locks_source": EXTRA_LOCKS_SOURCE,
                    # v0.8 select surfaces (schema-probed when available —
                    # the client builds the 「环境与载荷」 selects from these, not from
                    # hardcoded copies)
                    "axis_values": AXIS_VALUES,
                    "machine_values": MACHINE_VALUES,
                    "validate_tiers": VALIDATE_TIERS,
                    "precond_values": PRECOND_VALUES,
                    "drift": {
                        "patterns": [p for p in PATTERNS
                                     if p not in FALLBACK_PATTERNS],
                        "materials": [m for m in MATERIALS
                                      if m not in FALLBACK_MATERIALS],
                    },
                    "filtered": SURFACE_FILTERED,
                },
            })
        elif path == "/api/sidecar":
            query = parse_qs(urlparse(self.path).query)
            tk = (query.get("token") or [""])[0]
            with _session_lock:
                sess = _sessions.get(tk)
                sidecar = sess.get("last_sidecar") if sess else None
                found = sess is not None
            if not found:
                _send_json(self, 400, {"ok": False, "error": "unknown token"})
            else:
                _send_json(self, 200, {"ok": True, "sidecar": sidecar})
        elif path == "/api/progress":
            # last engine progress for a running analyze (v0.8). `running`
            # false + progress null = idle (no fake 100% tail).
            query = parse_qs(urlparse(self.path).query)
            tk = (query.get("token") or [""])[0]
            with _session_lock:
                found = tk in _sessions
            if not found:
                _send_json(self, 400, {"ok": False, "error": "unknown token"})
                return
            with _inflight_lock:
                running = tk in _inflight
                prog = _progress.get(tk)
            _send_json(self, 200, {"ok": True, "running": running,
                                   "progress": prog})
        elif path == "/api/report":
            # last successful run's full JSON (single analyze, compare, or
            # batch combo — last writer wins). token-gated like /api/history.
            query = parse_qs(urlparse(self.path).query)
            tk = (query.get("token") or [""])[0]
            with _session_lock:
                sess = _sessions.get(tk)
                report = sess.get("last_report") if sess else None
                name = sess.get("name") if sess else None
                found = sess is not None
            if not found:
                _send_json(self, 400, {"ok": False, "error": "unknown token"})
            elif query.get("download"):
                if report is None:
                    _send_json(self, 400, {"ok": False, "error": "尚无分析报告（先运行分析）"})
                    return
                body = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
                # name is user-controlled: RFC 5987 quote + fixed ASCII
                # fallback, same double-header shape as _export (latin-1 sink)
                base = os.path.splitext(name or "model")[0]
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header(
                        "Content-Disposition",
                        "attachment; filename=\"report.json\"; filename*=UTF-8''%s"
                        % quote(base + ".stratum-report.json"))
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except ConnectionError:
                    return  # client gone (iter 23 rule)
            else:
                _send_json(self, 200, {"ok": True, "report": report})
        elif path == "/api/model":
            # raw bytes of the stored upload (STL preview; other formats are
            # served too — the UI just doesn't render them). token-gated like
            # the other GET endpoints; bytes are the user's own upload.
            query = parse_qs(urlparse(self.path).query)
            tk = (query.get("token") or [""])[0]
            with _session_lock:
                sess = _sessions.get(tk)
                mpath = sess["path"] if sess else None
                mname = sess["name"] if sess else None
            if not mpath:
                _send_json(self, 400, {"ok": False, "error": "unknown token"})
                return
            try:
                with open(mpath, "rb") as fh:
                    data = fh.read()
            except OSError as exc:
                _send_json(self, 500, {"ok": False, "error": str(exc)})
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header(
                    "Content-Disposition", "inline; filename=\"model\"; "
                    "filename*=UTF-8''%s" % quote(mname or "model"))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)  # client-gone handled below
            except ConnectionError:
                return  # iter 23 rule
        elif path == "/api/model-mesh":
            # v0.17 3MF live preview: triangles for the WebGL pipeline, token-
            # gated like /api/model (the bytes are the user's own upload).
            # do_GET has no ValueError→400 wrapper (see /api/history note),
            # so every failure path here answers its own honest 400.
            query = parse_qs(urlparse(self.path).query)
            tk = (query.get("token") or [""])[0]
            with _session_lock:
                sess = _sessions.get(tk)
                mpath = sess["path"] if sess else None
                is_3mf = sess["is_3mf"] if sess else None
            if not mpath:
                _send_json(self, 400, {"ok": False, "error": "unknown token"})
            elif not is_3mf:
                _send_json(self, 400, {"ok": False,
                                       "error": "网格预览端点仅支持 3MF（STL 预览由 /api/model 提供）"})
            else:
                try:
                    mesh = extract_3mf_mesh(mpath)
                except (ValueError, OSError, zipfile.BadZipFile,
                        NotImplementedError) as exc:
                    # corrupt container / bad XML / over-cap: honest text for
                    # the UI's degrade note, never a half-empty 200
                    _send_json(self, 400, {"ok": False, "error": str(exc)})
                else:
                    _send_json(self, 200, {"ok": True, **mesh})
        elif path == "/api/history":
            # own token gate: do_GET has no ValueError→400 wrapper, so an
            # unknown token must be answered here, not via _session()
            query = parse_qs(urlparse(self.path).query)
            token = (query.get("token") or [""])[0]
            with _session_lock:
                session = _sessions.get(token)
                # "history" is created lazily on the first SUCCESSFUL analyze
                # (setdefault in _analyze/_batch) — a fresh session (upload
                # done, analyze still running/failed) has no key yet, and a
                # bare [..] here crashed the whole GET (empty reply, iter 58;
                # this is the runBatch progress timer's endpoint).
                entries = list(session.get("history", [])) if session else None
                # aggregated live batch progress. Key is ALWAYS present —
                # null when no batch runs; consumers must not distinguish
                # missing-key vs null (refuter minor-3, iter 47). Each
                # per-batch counter is monotonic, so the sum is too.
                batch = None
                if session:
                    progs = session.get("batch_prog") or {}
                    if progs:
                        batch = {"done": sum(x["done"] for x in progs.values()),
                                 "total": sum(x["total"] for x in progs.values())}
            if entries is None:
                _send_json(self, 400, {"ok": False, "error": "unknown token"})
            else:
                _send_json(self, 200, {"ok": True, "entries": entries,
                                       "batch": batch})
        elif path == "/api/logs-dir":
            # v0.16: diagnostics disclosure — where the rolling log lives.
            # file:None honestly reports the console-only degraded mode.
            _send_json(self, 200, {"ok": True, "dir": LOG_DIR,
                                   "file": LOG_FILE})
        else:
            _send_json(self, 404, {"ok": False, "error": "not found"})

    def _serve_index(self):
        try:
            with open(INDEX_PATH, "rb") as fh:
                body = fh.read()
        except OSError:
            _send_json(self, 500, {"ok": False, "error": "index.html missing"})
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)  # client-gone handled like _send_json
        except ConnectionError:
            pass

    def _serve_ui_static(self, path):
        fname, ctype = UI_STATIC[path]
        try:
            with open(os.path.join(RESOURCE_DIR, fname), "rb") as fh:
                body = fh.read()
        except OSError:
            _send_json(self, 500, {"ok": False, "error": fname + " missing"})
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)  # client-gone handled like _serve_index
        except ConnectionError:
            pass

    # ---- POST ---------------------------------------------------------------

    def do_POST(self):
        if not self._origin_allowed():
            self._deny_origin()
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                self._upload()
            elif path == "/api/analyze":
                self._analyze()
            elif path == "/api/open-logs":
                self._open_logs()
            elif path == "/api/export":
                self._export()
            elif path == "/api/export-artifact":
                self._export_artifact()
            elif path == "/api/export-preview":
                self._export_preview()
            elif path == "/api/cancel":
                body = _read_json_body(self)
                session = self._session(body)  # unknown token -> 400
                _send_json(self, 200, {"ok": True,
                                       "cancelled": cancel_analyze(session["token"])})
            elif path == "/api/batch":
                self._batch()
            elif path == "/api/set-binary":
                self._set_binary()
            else:
                _send_json(self, 404, {"ok": False, "error": "not found"})
        except _BusyError:
            _send_json(self, 503, {"ok": False,
                                   "error": "引擎忙（排队已满）——稍后重试或取消其他任务"})
        except ConnectionError:
            return  # client gone mid-request (abort/close) — nothing to answer
        except ValueError as exc:
            _send_json(self, 400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # defensive: never crash the worker
            # full stack to the console; the repr rides the 500 body so the
            # UI red card (and bug reports) carry the real cause — a bare
            # "internal error" is undiagnosable from the outside
            self._log("error: %s" % traceback.format_exc().strip())
            _send_json(self, 500, {"ok": False,
                                   "error": "internal error: %r" % (exc,)})

    def _upload(self):
        if BINARY is None:
            _send_json(self, 503, {"ok": False,
                                   "error": "stratum.exe 未找到（设置 STRATUM_BIN 或放 bin/stratum.exe）"})
            return
        query = parse_qs(urlparse(self.path).query)
        filename = (query.get("name") or ["model.stl"])[0]
        basename = os.path.basename(filename)
        # Control characters are never legitimate in a filename (a browser
        # file picker cannot produce them) — reject rather than silently
        # mangle. Everything else (CJK, quotes, ';') is legal on NTFS and is
        # handled per-consumer: token-keyed fs paths never see it, and the
        # download header encodes it (RFC 5987) at render time.
        if any(ord(c) < 0x20 or ord(c) == 0x7f for c in basename):
            raise ValueError("文件名含非法控制字符")
        # The engine picks its parser by EXTENSION (usage: <file.stl|file.3mf|
        # file.obj|file.ply|file.amf>, probed 2026-08-19: all five rc=0 on
        # tetrahedron fixtures). Saving an .obj body as token.stl used to end
        # in a misleading engine error ("STL: truncated file"), so the real
        # extension is preserved — and unknown extensions are rejected here.
        ext = basename.lower().rsplit(".", 1)[-1] if "." in basename else ""
        if ext not in ("stl", "3mf", "obj", "ply", "amf"):
            raise ValueError("支持的模型格式: stl / 3mf / obj / ply / amf")
        is_3mf = ext == "3mf"
        # Sliced-plate export (Bambu/Orca "*.gcode.3mf"): zip with gcode +
        # thumbnails but no mesh — the engine always rejects it after a full
        # parse, so fail fast at upload with the same advice (6 of 230 real
        # Downloads files hit this; batch 2026-08-19).
        if is_3mf and basename.lower().endswith(".gcode.3mf"):
            raise ValueError(
                "这是已切片导出的 .gcode.3mf（只含 gcode 和缩略图，没有原始网格），"
                "无法做几何分析。请在切片软件里另存为未切片的工程 3MF 后重新上传")
        raw = _read_body(self)
        # A .3mf is a ZIP container; anything else (e.g. a RAR renamed to
        # .3mf — seen in the wild) can only fail inside miniz with a cryptic
        # "cannot open ZIP". Two-byte "PK" covers local-file and EOCD sigs.
        if is_3mf and raw[:2] != b"PK":
            raise ValueError(
                "该文件不是 3MF（ZIP 容器）：魔数校验失败。"
                "文件可能被重命名过（如 RAR 改成 .3mf），请检查真实格式")
        # write-back needs at least ONE Metadata/*.config (engine-verified
        # iter 53: --dry-run rc=0 without any, but real write rc=1; and files
        # with only model_settings.config DO write back — do NOT "fix" this
        # to require project_settings.config, that would reject 5/231 real
        # files). namelist reads only the central directory — no zip-bomb
        # amplification. A PK-magic file with a broken central directory is
        # CORRUPT, not a bare CAD export — different message (3/231 real).
        writable = None
        if is_3mf:
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    names = zf.namelist()
                writable = any(n.startswith("Metadata/")
                               and n.endswith(".config") for n in names)
            except (zipfile.BadZipFile, NotImplementedError,
                    zipfile.LargeZipFile, OSError) as exc:
                raise ValueError("该 3MF 的 ZIP 结构损坏，无法解析: %s" % exc)
        token = secrets.token_hex(8)
        path = os.path.join(WORK_DIR, token + "." + ext)
        with open(path, "wb") as fh:
            fh.write(raw)
        with _session_lock:
            # "token" is echoed into the session so report/output paths can be
            # keyed on it without re-trusting the client-supplied token later.
            _sessions[token] = {"token": token, "path": path,
                                "name": basename, "is_3mf": is_3mf,
                                "writable": writable}
            while len(_sessions) > MAX_SESSIONS:
                _evict_oldest_session_locked()
        _send_json(self, 200, {"ok": True, "token": token, "name": basename,
                               "is_3mf": is_3mf, "writable": writable,
                               "size": len(raw)})

    def _session(self, body):
        token = body.get("token")
        with _session_lock:
            session = _sessions.get(token)
        if session is None:
            raise ValueError("unknown token (upload expired?)")
        return session

    def _analyze(self):
        body = _read_json_body(self)
        session = self._session(body)
        params = body.get("params") or {}
        locks = body.get("locks") or []
        if not isinstance(locks, list) or not all(isinstance(x, str) for x in locks):
            # Type gate only: the engine remains the authority on which lock
            # names are valid (it accepts names beyond this UI's param set,
            # e.g. layer_height, and rejects unknown ones with its own error).
            raise ValueError("locks 必须是参数名列表")
        compare = bool(body.get("compare", False))
        orient = bool(body.get("orient", False))
        # v0.8.1 diagnostics phases (bonus channels, whole-request switches
        # like orient; the old-engine fallback retry strips them if rejected)
        appearance = bool(body.get("appearance", False))
        rheology = bool(body.get("rheology", False))
        est_error = bool(body.get("est_error_profile", False))
        res_check = bool(body.get("resolution_check", False))
        # per-run FEM grid (v0.8.1): 4..128 is the engine's own domain (same
        # as the STRATUM_UI_GRID startup check). Absent/None = server default.
        grid = None
        if body.get("grid") is not None:
            grid = _validated_int(body.get("grid"), 4, 128)
            if grid is None:
                raise ValueError("grid 需为 4-128 整数（引擎域）")
        # heatmap bins-per-axis (v0.8.1): --schema domain 2..64; None = the
        # engine default 16, flag not sent.
        heatmap_bins = None
        if body.get("heatmap_bins") is not None:
            heatmap_bins = _validated_int(body.get("heatmap_bins"), 2, 64)
            if heatmap_bins is None:
                raise ValueError("heatmap_bins 需为 2-64 整数（引擎域）")
        # external baseline profile (v0.8.1): client sends the JSON TEXT,
        # server validates + writes it to the private temp dir and passes a
        # PATH to the engine (the engine parses/validates the keys itself).
        base_profile_path = None
        if body.get("base_profile") is not None:
            text = validated_base_profile(body["base_profile"])
            base_profile_path = os.path.join(WORK_DIR, "%s.b%s.json" % (
                session["token"], secrets.token_hex(4)))
            with open(base_profile_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        # clear a stale sticky-cancel flag (a late /api/cancel after the last
        # run finished leaves the token in _batch_cancel — the queued-cancel
        # recheck in run_analyze_cancelable would swallow THIS run with a
        # spurious "已取消"). Mirrors the batch path's start-of-request
        # discard; a cancel arriving AFTER this point is still honored by the
        # recheck (iter 44, refuter-reproduced).
        with _inflight_lock:
            _batch_cancel.discard(session["token"])
        for name in params:
            if name not in PARAM_FLAGS:
                raise ValueError("unknown parameter: %r" % name)
        env = validated_env(body.get("env") or {})
        if body.get("fast") is True:  # 「快速预览」--fast (preview-grade run)
            env["fast"] = True  # constant literal: already whitelist-valid
        # Keyed on the server-generated hex token, not the user-supplied name:
        # two concurrent sessions with the same filename no longer overwrite
        # each other's report, and odd names never reach the filesystem.
        # per-run suffix: two concurrent runs of the same token (two tabs,
        # or a batch racing a single analyze) must not stomp each other's
        # report file (iter 17/18 backlog). Evict glob token* still covers.
        report_path = os.path.join(WORK_DIR, "%s.a%s%s.json" % (
            session["token"], secrets.token_hex(4),
            ".compare" if compare else ".analyze"))
        heatmap_path = os.path.join(WORK_DIR, "%s.h%s.json" % (
            session["token"], secrets.token_hex(4)))
        args = build_analyze_args(session["path"], params, locks, compare,
                                  report_path, env=env, orient=orient,
                                  heatmap_path=heatmap_path,
                                  appearance=appearance, rheology=rheology,
                                  est_error=est_error, res_check=res_check,
                                  grid=grid, heatmap_bins=heatmap_bins,
                                  base_profile_path=base_profile_path)
        self._log("run: %s ..." % os.path.basename(BINARY))
        rc, out, err = run_analyze_with_fallback(
            args, run=lambda a: run_analyze_cancelable(a, session["token"]))
        if base_profile_path:
            # consumed by the engine run (either outcome) — best-effort delete
            try:
                os.remove(base_profile_path)
            except OSError:
                pass
        if rc == CANCELLED_RC:
            _send_json(self, 502, {"ok": False, "error": "已取消"})
            return
        if rc != 0:
            # status markers (engine writes marker JSON instead of a report):
            # cancelled-at-stage-boundary (rc=130) and --validate refusal
            # (rc=1). Both must surface structured responses, not a raw rc.
            marker = load_report_marker(report_path)
            if marker is not None:
                send_marker_response(self, marker)
                return
            # rc=124 is our own timeout kill. Real-world batch (2026-08-19,
            # 52-model sample): every >20MB high-poly multicolor model blew
            # the 180s budget, and load time alone (no phase flags, any
            # --grid) accounts for it — mesh parsing dominates. Point the
            # user at the two levers that exist today instead of a bare rc.
            if rc == 124:
                error = ("分析超时（180s）——模型过大/面数过高（%.1f MB）。"
                         "可尝试：① 用环境变量 STRATUM_UI_GRID 调低体素分辨率后重启；"
                         "② 换用更小/更简化的模型" % (os.path.getsize(session["path"]) / 1e6))
            else:
                error = "stratum.exe 失败 (rc=%d): %s" % (rc, err.decode("utf-8", "replace")[:400])
            _send_json(self, 502, {"ok": False, "error": error})
            return
        try:
            with open(report_path, "r", encoding="utf-8") as fh:
                report = json.load(fh)
        except (OSError, ValueError) as exc:
            _send_json(self, 502, {"ok": False, "error": "报告解析失败: %s" % exc})
            return
        # Defensive: the engine exits nonzero for its markers, but if a future
        # path ever exits 0 with a marker file, fail loud here rather than
        # render a marker as if it were a report.
        if isinstance(report, dict) and report.get("status") in REPORT_MARKER_STATUSES:
            send_marker_response(self, report)
            return
        if not ALLOW_ANY_SCHEMA and not schema_supported(report):
            _send_json(self, 502, {"ok": False, "error":
                "引擎报告 schema_version=%r 不受支持（本 WebUI 支持 %s）；"
                "请升级 WebUI 或换用匹配版本的 SDK"
                % ((report or {}).get("schema_version") if isinstance(report, dict) else report,
                   "/".join(str(s) for s in SUPPORTED_SCHEMA))})
            return
        # session history (ROADMAP v0.3b): keep the last K summaries so the UI
        # can list/diff runs. Mutex-protected: ThreadingHTTPServer means a
        # concurrent GET /api/history can traverse the list mid-mutation.
        with _session_lock:
            hist = session.setdefault("history", [])
            hist.append({
                "seq": session.get("hist_seq", 0) + 1,  # monotonic: NOT
                # len(hist)+1, which repeats once the cap starts evicting
                "ts": time.strftime("%H:%M:%S"),
                "compare": compare,
                "orient": orient,
                "params": params, "env": env, "locks": list(locks),
                "summary": _history_summary(report),
            })
            session["hist_seq"] = hist[-1]["seq"]
            # full report for the download endpoint (GET /api/report). Same
            # critical section as history; batch combos update it too (last
            # successful run wins, single or combo alike).
            session["last_report"] = report
            del hist[:-MAX_HISTORY]
        # heatmap passthrough (v0.8): the engine wrote a sparse bins³ grid —
        # shape-check minimally and embed. A missing/unparseable file is NOT
        # an error: this is a bonus channel (old engine, --fast without FEM
        # scope, disk hiccup) and must never fail an otherwise-good analysis.
        heatmap = None
        try:
            if os.path.isfile(heatmap_path):
                with open(heatmap_path, "r", encoding="utf-8") as fh:
                    hm = json.load(fh)
                if isinstance(hm, dict) and isinstance(hm.get("bins"), list):
                    heatmap = hm
        except (OSError, ValueError):
            heatmap = None
        finally:
            try:
                os.remove(heatmap_path)
            except OSError:
                pass
        # console: pass through the engine's own stdout so the UI can show the
        # CLI's "Recommended:" line verbatim (no recommendation logic in JS).
        # applyable (v0.9): top-level SIBLING key, deliberately NOT merged
        # into the report tree — session["last_report"] is stored by
        # reference and GET /api/report dumps it verbatim; injecting here
        # would fabricate an engine-authored field inside the downloaded
        # artifact. Builder is degrade-never-raise (bonus channel).
        _send_json(self, 200, {"ok": True, "report": report,
                               "console": out.decode("utf-8", "replace"),
                               "heatmap": heatmap,
                               "applyable": applyable_suggestions(report)})

    def _export(self):
        body = _read_json_body(self)
        session = self._session(body)
        if not session["is_3mf"]:
            _send_json(self, 400, {"ok": False,
                                   "error": "写回需要 .3mf 输入（STL/OBJ 等没有切片配置可写回）"})
            return
        if session.get("writable") is False:
            # engine rc=1 otherwise ("file not found in ZIP: Metadata/…config",
            # dogfooded on a real CAD-bare export iter 53). NOTE: --dry-run
            # (preview) succeeds on these, so _export_preview has NO gate.
            _send_json(self, 400, {"ok": False,
                                   "error": "该 3MF 无切片设置（CAD 裸导出，无 Metadata/*.config），"
                                            "没有可写回的参数。请在切片软件中另存为工程 3MF"})
            return
        profile = body.get("profile") or "balanced"
        if profile not in PROFILES:
            raise ValueError("unknown profile: %r" % profile)
        strict = bool(body.get("strict_tier", False))
        # mode (v0.8.1): "optimize" (default) = --optimize-3mf <profile>
        # (profile + Orca suggestions); "orca" = --apply-orca (Orca
        # suggestions ONLY — brim/support/PA/weld, no profile writeback).
        # Both need a writable project 3MF. --apply-orca accepts but does
        # not write --sidecar-json (probed 0.24.0 and 0.26.0), so orca mode has no
        # sidecar audit — the download itself is the product.
        mode = body.get("mode") or "optimize"
        if mode not in ("optimize", "orca"):
            raise ValueError("mode 必须是 optimize|orca 之一")
        # per-run suffix, same rationale as the analyze report path (two
        # concurrent exports of one token must not stomp each other's out
        # file — one would read the other's mid-write truncated 3mf, and the
        # sidecar pre-clear could delete a finished audit; iter 46,
        # refuter-verified). Files are deleted right after being read back
        # (a full 3mf can be 20MB+ — no unbounded accumulation between
        # evictions).
        run_hex = secrets.token_hex(4)
        out_path = os.path.join(WORK_DIR, "out_%s.%s.3mf" % (session["token"], run_hex))
        sidecar_path = os.path.join(WORK_DIR, "%s.s%s.json" % (session["token"], run_hex))
        if mode == "orca":
            args = [session["path"], "--apply-orca", out_path,
                    "--grid", GRID]
            if strict:
                args.append("--strict-tier")
            with _engine_slot():
                rc, out, err = run_stratum(args)
            sidecar_path = None
        else:
            args = [session["path"], "--optimize-3mf", profile,
                    "--out", out_path, "--grid", GRID,
                    "--sidecar-json", sidecar_path]
            if strict:
                args.append("--strict-tier")
            with _engine_slot():
                rc, out, err = run_stratum(args)
        if rc != 0 and mode == "optimize" and \
                "sidecar" in err.decode("utf-8", "replace").lower():
            # Older engine without --sidecar-json: retry once without it —
            # the audit is a bonus and must not break the export itself.
            sidecar_path = None
            args = [session["path"], "--optimize-3mf", profile,
                    "--out", out_path, "--grid", GRID]
            if strict:
                args.append("--strict-tier")
            with _engine_slot():
                rc, out, err = run_stratum(args)
        if rc != 0:
            _send_json(self, 502, {"ok": False,
                                   "error": "写回失败 (rc=%d): %s" % (rc, err.decode("utf-8", "replace")[:400])})
            return
        try:
            with open(out_path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            _send_json(self, 502, {"ok": False, "error": "输出读取失败: %s" % exc})
            return
        # [:-4] relies on is_3mf above: the name ends in exactly ".3mf".
        if mode == "orca":
            download_name = "%s_orca_suggestions.3mf" % session["name"][:-4]
        else:
            download_name = "%s_optimized_%s.3mf" % (session["name"][:-4],
                                                     profile)
        audit = _sidecar_header(sidecar_path) if sidecar_path else None
        # full sidecar for the detail view: keep the LAST SUCCESSFUL export
        # (failed exports/previews intentionally leave the previous value —
        # the panel says "Last Write-back"). Defensive parse: a corrupt file
        # stores null, never a partial dict.
        last_sidecar = None
        if sidecar_path:
            try:
                with open(sidecar_path, "r", encoding="utf-8") as fh:
                    parsed = json.load(fh)
                last_sidecar = parsed if isinstance(parsed, dict) else None
            except (OSError, ValueError):
                last_sidecar = None
        with _session_lock:
            session["last_sidecar"] = last_sidecar
        # both per-run artifacts are fully consumed (bytes + sidecar dict) —
        # delete now, best-effort: a failure only costs disk until the evict
        # glob (out_<token>* / <token>* both match the suffixed names) or the
        # shutdown rmtree runs.
        for stale in (out_path, sidecar_path):
            if stale:
                try:
                    os.remove(stale)
                except OSError:
                    pass
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        # audit values come from the engine's JSON numbers/bools only — no
        # user-controlled text, so no header-injection surface.
        if audit:
            self.send_header("X-Stratum-Sidecar", audit)
        # RFC 6266/5987: send_header encodes latin-1 strict, so a CJK
        # filename must not go in raw — percent-encode it and keep a fixed
        # ASCII fallback. (The browser download uses the JS-side name; this
        # header covers curl/direct-API consumers.)
        if mode == "orca":
            fallback_name = "model_orca_suggestions.3mf"
        else:
            fallback_name = "model_optimized_%s.3mf" % profile
        self.send_header(
            "Content-Disposition",
            "attachment; filename=\"%s\"; "
            "filename*=UTF-8''%s" % (fallback_name, quote(download_name)))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)  # large binary body — same client-gone rule
        except ConnectionError:
            return

    def _export_artifact(self):
        """Analysis-artifact downloads (v0.8.1): --generate-supports (support
        structure mesh) and --stress-modifier (P95 hot-zone voxel STL, the
        slicer-modifier export). Both run a real engine analysis at the
        server grid and stream the produced STL back. `kind` is whitelisted;
        files are token-keyed per-run and deleted after read. Works for every
        input format (STL included) — nothing here writes back into a 3MF."""
        body = _read_json_body(self)
        session = self._session(body)
        artifact_flags = {
            "supports": "--generate-supports",
            "stress_modifier": "--stress-modifier",
        }
        flag = artifact_flags.get(body.get("kind"))
        if flag is None:
            raise ValueError("kind 必须是 supports|stress_modifier 之一")
        run_hex = secrets.token_hex(4)
        out_path = os.path.join(WORK_DIR, "%s.k%s.stl" % (
            session["token"], run_hex))
        args = [session["path"], "--grid", GRID, flag, out_path]
        with _engine_slot():
            rc, out, err = run_stratum(args)
        if rc != 0:
            _send_json(self, 502, {"ok": False,
                                   "error": "导出失败 (rc=%d): %s" % (
                                       rc, err.decode("utf-8", "replace")[:400])})
            return
        try:
            with open(out_path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            _send_json(self, 502, {"ok": False, "error": "产物读取失败: %s" % exc})
            return
        # fully consumed — delete now, best-effort (evict glob is the backstop)
        try:
            os.remove(out_path)
        except OSError:
            pass
        base = os.path.splitext(session["name"] or "model")[0]
        # RFC 6266/5987: CJK-safe download name, fixed ASCII fallback — same
        # double-header shape as /api/report download
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            "attachment; filename=\"artifact_%s.stl\"; filename*=UTF-8''%s"
            % (body.get("kind"), quote(base + {
                "supports": "_supports.stl",
                "stress_modifier": "_stress_modifier.stl"}[body.get("kind")])))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except ConnectionError:
            return  # client gone mid-download

    def _export_preview(self):
        """Dry-run audit: what --optimize-3mf WOULD write, in the engine's
        own table (no 3MF written, no sidecar). Mirrors _export's gates and
        accepts the same strict_tier so the preview matches a real write."""
        body = _read_json_body(self)
        session = self._session(body)
        if not session["is_3mf"]:
            raise ValueError("写回预览需要 .3mf 输入（STL/OBJ 等没有切片配置可写回）")
        profile = body.get("profile") or "balanced"
        if profile not in PROFILES:
            raise ValueError("unknown profile: %r" % profile)
        strict = bool(body.get("strict_tier", False))
        # --dry-run still requires --out (probed 0.21.0) but writes nothing;
        # the placeholder name is token-keyed and never read back.
        dry_path = os.path.join(WORK_DIR, session["token"] + ".dry.3mf")
        args = [session["path"], "--optimize-3mf", profile, "--out", dry_path,
                "--grid", GRID, "--dry-run"]
        if strict:
            args.append("--strict-tier")
        with _engine_slot():
            rc, out, err = run_stratum(args)
        if rc != 0:
            _send_json(self, 502, {"ok": False,
                                   "error": "写回预览失败 (rc=%d): %s" % (rc, err.decode("utf-8", "replace")[:400])})
            return
        # console passthrough mirrors analyze: engine stdout verbatim
        _send_json(self, 200, {"ok": True,
                               "console": out.decode("utf-8", "replace")})

    def _batch(self):
        """Run user-defined param combos sequentially (ROADMAP v0.3c — pure
        orchestration of multiple engine calls, no rules in Python). All
        combos are validated and argv-built UP FRONT: a bad combo is a 400
        with zero side effects, never a half-executed batch. A failed combo
        marks only its own result; /api/cancel stops the whole batch (note
        the intentional difference from single-analyze: batch cancel answers
        200 with cancelled=true and the partial results)."""
        body = _read_json_body(self)
        session = self._session(body)
        combos = body.get("combos")
        if not isinstance(combos, list) or not (1 <= len(combos) <= 8):
            raise ValueError("combos 必须是 1-8 个组合的列表")
        # orient is a WHOLE-BATCH switch (top-level body key): the UI keeps a
        # single checkbox, and per-combo embedding is deliberately not read —
        # two sources for one flag would drift (refuter b', iter 38). The
        # v0.8.1 diagnostics phases follow the same pattern.
        orient = bool(body.get("orient", False))
        appearance = bool(body.get("appearance", False))
        rheology = bool(body.get("rheology", False))
        est_error = bool(body.get("est_error_profile", False))
        res_check = bool(body.get("resolution_check", False))
        # whole-batch per-run grid override, validated once up front (a bad
        # value must be a 400 before ANY combo runs — same zero-side-effect
        # contract as the combo validation)
        grid = None
        if body.get("grid") is not None:
            grid = _validated_int(body.get("grid"), 4, 128)
            if grid is None:
                raise ValueError("grid 需为 4-128 整数（引擎域）")
        # whole-batch base profile (v0.8.1), validated once up front
        base_profile_path = None
        if body.get("base_profile") is not None:
            text = validated_base_profile(body["base_profile"])
            base_profile_path = os.path.join(WORK_DIR, "%s.b%s.json" % (
                session["token"], secrets.token_hex(4)))
            with open(base_profile_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        plans = []
        for i, c in enumerate(combos):
            if not isinstance(c, dict):
                raise ValueError("combo %d 必须是对象" % i)
            label = c.get("label", "combo %d" % (i + 1))
            if not isinstance(label, str) or len(label) > 40:
                raise ValueError("combo %d label 需为 ≤40 字符" % i)
            params = c.get("params") or {}
            for name in params:
                if name not in PARAM_FLAGS:
                    raise ValueError("unknown parameter: %r" % name)
            env = validated_env(c.get("env") or {})
            locks = c.get("locks") or []
            if not isinstance(locks, list) or not all(isinstance(x, str) for x in locks):
                raise ValueError("locks 必须是参数名列表")
            report_path = os.path.join(WORK_DIR, "%s.b%s%d.json" % (
                session["token"], secrets.token_hex(4), i))
            argv = build_analyze_args(session["path"], params, locks, False,
                                      report_path, env=env, orient=orient,
                                      appearance=appearance,
                                      rheology=rheology,
                                      est_error=est_error,
                                      res_check=res_check,
                                      grid=grid,
                                      base_profile_path=base_profile_path)
            plans.append({"label": label, "argv": argv, "path": report_path,
                          "params": params, "env": env, "locks": locks})
        token = session["token"]
        with _inflight_lock:
            _batch_cancel.discard(token)
        # progress counter: one entry per ACTIVE batch (batch_id keyed — a
        # single shared slot would let one tab's batch finish wipe the other's
        # counter, and interleaved writes flip done/total between polls).
        # Incremented at loop top so FAILED combos (which never reach the
        # history append) still advance progress — the old UI counted history
        # entries and stalled on failures (iter 17, refuter-revised).
        batch_id = secrets.token_hex(4)
        with _session_lock:
            prog = session.setdefault("batch_prog", {})
            prog[batch_id] = {"done": 0, "total": len(plans)}
        results = []
        cancelled = False
        try:
            for plan in plans:
                with _session_lock:
                    session["batch_prog"][batch_id]["done"] += 1
                with _inflight_lock:
                    if token in _batch_cancel:
                        cancelled = True
                        break
                    _batch_cancel.discard(token)
                try:
                    rc, out, err = run_analyze_with_fallback(
                        plan["argv"], run=lambda a: run_analyze_cancelable(a, token))
                except _BusyError:
                    # queue full mid-batch: keep the completed results instead of
                    # losing them to a whole-request 503 (matches the cancel
                    # semantics of returning partial results)
                    results.append({"label": plan["label"], "ok": False,
                                    "error": "busy queue (this combo was not executed)"})
                    break
                if rc == CANCELLED_RC:
                    cancelled = True
                    break
                if rc != 0:
                    # marker first (cancelled/refused), then the generic rc
                    marker = load_report_marker(plan["path"])
                    if marker is not None:
                        if marker.get("status") == "cancelled":
                            cancelled = True
                            break
                        results.append({"label": plan["label"], "ok": False,
                                        "status": "validation_refused",
                                        "error": refusal_text(marker)})
                        continue
                    results.append({"label": plan["label"], "ok": False,
                                    "error": "rc=%d: %s" % (rc, err.decode("utf-8", "replace")[:200])})
                    continue
                try:
                    with open(plan["path"], "r", encoding="utf-8") as fh:
                        report = json.load(fh)
                except (OSError, ValueError) as exc:
                    results.append({"label": plan["label"], "ok": False,
                                    "error": str(exc)})
                    continue
                # defensive status-marker check (mirrors _analyze)
                if isinstance(report, dict) and report.get("status") in REPORT_MARKER_STATUSES:
                    if report.get("status") == "cancelled":
                        cancelled = True
                        break
                    results.append({"label": plan["label"], "ok": False,
                                    "status": "validation_refused",
                                    "error": refusal_text(report)})
                    continue
                if not ALLOW_ANY_SCHEMA and not schema_supported(report):
                    results.append({"label": plan["label"], "ok": False,
                                    "error": "schema_version 不受支持"})
                    continue
                summary = _history_summary(report)
                results.append({"label": plan["label"], "ok": True,
                                "summary": summary})
                with _session_lock:
                    hist = session.setdefault("history", [])
                    hist.append({"seq": session.get("hist_seq", 0) + 1,
                                 "ts": time.strftime("%H:%M:%S"),
                                 "compare": False,
                                 "orient": orient,
                                 "params": plan["params"], "env": plan["env"],
                                 "locks": plan["locks"], "label": plan["label"],
                                 "summary": summary})
                    session["hist_seq"] = hist[-1]["seq"]
                    session["last_report"] = report  # download endpoint (see _analyze)
                    del hist[:-MAX_HISTORY]
        finally:
            # MUST be try/finally (refuter major-2): an unexpected exception
            # mid-batch must not leak a ghost batch_prog that pins the UI at
            # a fake progress forever.
            with _session_lock:
                session.get("batch_prog", {}).pop(batch_id, None)
            if base_profile_path:
                try:
                    os.remove(base_profile_path)
                except OSError:
                    pass

        _send_json(self, 200, {"ok": True, "cancelled": cancelled,
                               "results": results})

    def _set_binary(self):
        """First-run wizard target (ROADMAP v0.4a). Validates the path REALLY
        is the engine (usage probe), then rebinds the module globals the
        import-time probe filled (a stale enum surface would keep serving
        the fallback lists after a successful setup)."""
        global BINARY, PATTERNS, MATERIALS, LOAD_TYPES, PATTERNS_SOURCE, \
            MATERIALS_SOURCE, LOADS_SOURCE, SURFACE_FILTERED, EXTRA_LOCKS, \
            EXTRA_LOCKS_SOURCE, AXIS_VALUES, MACHINE_VALUES, VALIDATE_TIERS, \
            PRECOND_VALUES
        body = _read_json_body(self)
        p = body.get("path")
        if not isinstance(p, str) or not p.strip():
            raise ValueError("path 必须是非空字符串")
        if _reject_remote_path(p):
            raise ValueError("不接受 UNC 网络路径（本地工具不执行网络二进制；请用本地盘路径）")
        ok, why = _looks_like_stratum(p)
        if not ok:
            raise ValueError(why or "无效的引擎路径")
        BINARY = os.path.abspath(p)
        # re-probe the enum surface with the new binary and rebind
        (PATTERNS, MATERIALS, LOAD_TYPES, PATTERNS_SOURCE, MATERIALS_SOURCE,
         LOADS_SOURCE, SURFACE_FILTERED, EXTRA_LOCKS, EXTRA_LOCKS_SOURCE) = \
            _probe_surface()
        (AXIS_VALUES, MACHINE_VALUES, VALIDATE_TIERS, PRECOND_VALUES) = \
            _refresh_select_surfaces()
        _apply_schema_domains()  # re-overlay numeric domains from the new probe
        try:
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"binary": BINARY}, fh)
            os.replace(tmp, CONFIG_PATH)
        except OSError as exc:
            self._log("config write failed: %r" % exc)  # session-only setup
        self._log("engine set: %s" % BINARY)
        _send_json(self, 200, {"ok": True, "binary": BINARY,
                               "engine_version": engine_version(BINARY)})

    def log_message(self, fmt, *args):
        pass  # keep the console clean; use _log for real events

    def _open_logs(self):
        """v0.16: open the log directory in Explorer (「打开日志目录」 button).
        os.startfile receives ONLY the server-computed LOG_DIR — no client
        input reaches the shell. STRATUM_UI_LOG_OPEN=0 is the test-mode skip
        (opening real windows during CI is noise, not coverage); non-Windows
        degrades honestly instead of failing loud."""
        if os.environ.get("STRATUM_UI_LOG_OPEN") == "0":
            _send_json(self, 200, {"ok": True, "opened": False,
                                   "dir": LOG_DIR, "skipped": "test-mode"})
            return
        if not hasattr(os, "startfile"):
            _send_json(self, 200, {"ok": True, "opened": False,
                                   "dir": LOG_DIR, "skipped": "no-startfile"})
            return
        try:
            os.startfile(LOG_DIR)
        except OSError as exc:
            self._log("open-logs failed: %r" % exc)
            _send_json(self, 500, {"ok": False, "error": str(exc),
                                   "dir": LOG_DIR})
            return
        self._log("open-logs: %s" % LOG_DIR)
        _send_json(self, 200, {"ok": True, "opened": True, "dir": LOG_DIR})


def _open_browser_later():
    """Open the default browser once the server is about to accept requests.
    Skippable via STRATUM_UI_NO_BROWSER=1 (smoke tests, second instances)."""
    if os.environ.get("STRATUM_UI_NO_BROWSER") == "1":
        return
    threading.Timer(0.5, lambda: webbrowser.open("http://%s:%d" % (HOST, PORT))
                    ).start()


def main():
    _setup_file_logging()  # see note at the def: import-time would leak into test imports
    problems = []
    if PORT is None:
        problems.append("STRATUM_UI_PORT=%r 无效（需 1-65535 整数）" % PORT_RAW)
    if GRID is None:
        problems.append("STRATUM_UI_GRID=%r 无效（需 4-128 整数，引擎域）" % GRID_RAW)
    if MAX_SESSIONS is None:
        problems.append("STRATUM_UI_MAX_SESSIONS=%r 无效（需 ≥1 整数）"
                        % MAX_SESSIONS_RAW)
    if MAX_CONCURRENCY is None:
        problems.append("STRATUM_UI_MAX_CONCURRENCY=%r 无效（需 1-16 整数）"
                        % MAX_CONCURRENCY_RAW)
    if MAX_QUEUE is None:
        problems.append("STRATUM_UI_MAX_QUEUE=%r 无效（需 0-64 整数）"
                        % MAX_QUEUE_RAW)
    if MAX_HISTORY is None:
        problems.append("STRATUM_UI_MAX_HISTORY=%r 无效（需 2-100 整数；下限 2 保 A/B 对比可用）"
                        % MAX_HISTORY_RAW)
    if problems:
        for p in problems:
            sys.stderr.write("配置错误: %s\n" % p)
        return 1
    if ALLOW_ANY_SCHEMA:
        # escape valve is opt-in and unverified by definition — leave a trace
        # (loop-journal iter 11 backlog)
        sys.stderr.write("警告: STRATUM_UI_ALLOW_ANY_SCHEMA=1 — schema 闸已关闭，"
                         "错版本报告将按原样渲染\n")
    if sys.platform == "win32":
        try:  # cosmetic: name the console window instead of the exe path
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("Stratum WebUI")
        except Exception:
            pass
    if BINARY is None:
        # serve anyway: the UI's first-run wizard (POST /api/set-binary) is
        # the guided path; /api/upload already answers 503 until then
        sys.stderr.write(
            "stratum.exe 未找到——浏览器打开后在「模型」面板粘贴 stratum.exe 路径完成设置，\n"
            "或设置 STRATUM_BIN / 放到 bin/ 下后重启。\n")
    # reclaim stratum_ui_* dirs orphaned by force kills (iter 40)
    _sweep_orphan_workdirs()
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), StratumHandler)
    except OSError as exc:
        sys.stderr.write(
            "无法监听 %s:%d（%s）。\n"
            "可能已有一个 Stratum WebUI 在运行；或设置 STRATUM_UI_PORT 换端口。\n"
            % (HOST, PORT, exc))
        return 1
    sys.stderr.write("Stratum WebUI v%s: engine=%s (%s)\n"
                     % (UI_VERSION, engine_version(BINARY), BINARY))
    sys.stderr.write("  -> http://%s:%d  (Ctrl+C 退出)\n" % (HOST, PORT))
    _open_browser_later()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
