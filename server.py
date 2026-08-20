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
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
# 0.6.0 — ROADMAP v0.6 (UI v3 visual + auto real-time analysis) complete;
# bumped from 0.5.0 which had drifted behind the milestone (iter 67).
UI_VERSION = "0.6.0"

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
# Schema gate: the engine report carries schema_version (0.21.0 emits int 2).
# Exact numeric match against SUPPORTED_SCHEMA, per request — a future schema
# 3 that renames fields must fail loud here, not misrender silently
# (ROADMAP v0.4c). Missing/None/unparseable → reject (fail-loud default);
# escape valve for hypothetical pre-schema engines mirrors PHASE_D.
SUPPORTED_SCHEMA = (2,)
ALLOW_ANY_SCHEMA = os.environ.get("STRATUM_UI_ALLOW_ANY_SCHEMA", "0") == "1"


def schema_supported(report):
    if not isinstance(report, dict):
        return False
    v = report.get("schema_version")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    # exact numeric equality — no int() truncation (2.9 must NOT pass as 2)
    return v in SUPPORTED_SCHEMA

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


def engine_version(binary):
    """Read the SDK VERSION.txt that ships next to the binary (bundle root
    is one level above bin/). Fall back to 'unknown' without failing."""
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
            argv = [sys.executable, "-c", "import time; time.sleep(%d)" % _ANALYZE_DELAY]
        else:
            argv = [BINARY] + args
        return _run_proc_with_inflight(argv, token, gen)
    # unreachable


def _run_proc_with_inflight(argv, token, gen):
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with _inflight_lock:
        _inflight[token] = {"proc": proc, "gen": gen}
    was_cancelled = False
    try:
        out, err = proc.communicate(timeout=180)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return 124, b"", b"stratum.exe timed out"
    finally:
        with _inflight_lock:
            was_cancelled = gen in _cancelled_gens  # read BEFORE discard
            cur = _inflight.get(token)
            if cur and cur["gen"] == gen:
                del _inflight[token]
            _cancelled_gens.discard(gen)
    if was_cancelled:
        return CANCELLED_RC, b"", b"cancelled"
    return rc, out, err


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
# engine's own "orientation" output)
_FALLBACK_FLAGS = ("--orca-suggest", "--optimize-orient", "--explain")


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
}

FALLBACK_PATTERNS = ["line", "gyroid", "cubic", "triangles", "honeycomb", "grid", "rectilinear"]
FALLBACK_MATERIALS = ["PLA", "PETG", "ABS", "CUSTOM"]
FALLBACK_LOADS = ["compression", "bending", "torsion", "cantilever"]
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
# UI). Static fallback mirrors the 0.21.0 usage; the live list comes from the
# usage probe. "load" is excluded here — it has its own select in the env
# panel, which now carries its own lock checkbox.
FALLBACK_EXTRA_LOCKS = ["layer_height", "outer_wall_speed", "extrusion_stability",
                        "retraction_length", "retraction_speed", "wipe",
                        "travel_speed"]


def _probe_surface():
    """One-shot subprocess probe at import. Never raises: a broken binary
    (unexecutable, AV quarantine, ...) must degrade to the fallback lists,
    not kill the server at startup."""
    if BINARY is None:
        return (FALLBACK_PATTERNS, FALLBACK_MATERIALS, FALLBACK_LOADS,
                "fallback", "fallback", "fallback", [],
                FALLBACK_EXTRA_LOCKS, "fallback")
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
]

PROFILES = ["safe", "balanced", "fast", "appearance"]

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
}


def validated_env(env):
    """Type-gate + normalize the env dict from the analyze body. Numbers
    only (bool rejected explicitly — bool is an int subclass), whole floats
    narrowed to int for clean argv ("50" not "50.0"). Returns a new dict."""
    if not isinstance(env, dict):
        raise ValueError("env 必须是对象")
    out = {}
    for name, value in env.items():
        spec = ENV_FLAGS.get(name)
        if spec is None:
            raise ValueError("unknown env: %r" % name)
        if spec[1] == "select":
            if value not in LOAD_TYPES:
                raise ValueError("load 必须是 %s 之一" % "|".join(LOAD_TYPES))
            out[name] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("env.%s 必须是数值" % name)
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        out[name] = value
    return out


def build_analyze_args(model_path, params, locks, compare, json_path, env=None,
                       orient=False):
    """Build the whitelisted argv for an analyze/compare run."""
    # --explain: engine prints per-suggestion trust grounding (kb_module /
    # trust_source) to stdout only — JSON is byte-identical with/without it
    # (probed 0.21.0, iter 62). The UI shows engine console verbatim, so this
    # is the only wiring needed; no render-side contract.
    args = [model_path, "--phase-c", "--grid", GRID, "--orca-suggest",
            "--explain"]
    if orient:
        args.append("--optimize-orient")
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
        args.append(ENV_FLAGS[name][0])
        args.append(str(value))
    if locks:
        args.append("--lock")
        args.append(",".join(locks))
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
                "surface": {
                    "patterns_source": PATTERNS_SOURCE,
                    "materials_source": MATERIALS_SOURCE,
                    "loads_source": LOADS_SOURCE,
                    "loads": LOAD_TYPES,
                    "extra_locks": EXTRA_LOCKS,
                    "extra_locks_source": EXTRA_LOCKS_SOURCE,
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
            elif path == "/api/export":
                self._export()
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
            self._log("error: %r" % exc)
            _send_json(self, 500, {"ok": False, "error": "internal error"})

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
        # Keyed on the server-generated hex token, not the user-supplied name:
        # two concurrent sessions with the same filename no longer overwrite
        # each other's report, and odd names never reach the filesystem.
        # per-run suffix: two concurrent runs of the same token (two tabs,
        # or a batch racing a single analyze) must not stomp each other's
        # report file (iter 17/18 backlog). Evict glob token* still covers.
        report_path = os.path.join(WORK_DIR, "%s.a%s%s.json" % (
            session["token"], secrets.token_hex(4),
            ".compare" if compare else ".analyze"))
        args = build_analyze_args(session["path"], params, locks, compare,
                                  report_path, env=env, orient=orient)
        self._log("run: %s ..." % os.path.basename(BINARY))
        rc, out, err = run_analyze_with_fallback(
            args, run=lambda a: run_analyze_cancelable(a, session["token"]))
        if rc == CANCELLED_RC:
            _send_json(self, 502, {"ok": False, "error": "已取消"})
            return
        if rc != 0:
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
        # console: pass through the engine's own stdout so the UI can show the
        # CLI's "Recommended:" line verbatim (no recommendation logic in JS).
        _send_json(self, 200, {"ok": True, "report": report,
                               "console": out.decode("utf-8", "replace")})

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
        args = [session["path"], "--optimize-3mf", profile,
                "--out", out_path, "--grid", GRID,
                "--sidecar-json", sidecar_path]
        if strict:
            args.append("--strict-tier")
        with _engine_slot():
            rc, out, err = run_stratum(args)
        if rc != 0 and "sidecar" in err.decode("utf-8", "replace").lower():
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
        download_name = "%s_optimized_%s.3mf" % (session["name"][:-4], profile)
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
        self.send_header(
            "Content-Disposition",
            "attachment; filename=\"model_optimized_%s.3mf\"; "
            "filename*=UTF-8''%s" % (profile, quote(download_name)))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)  # large binary body — same client-gone rule
        except ConnectionError:
            return

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
        # two sources for one flag would drift (refuter b', iter 38).
        orient = bool(body.get("orient", False))
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
                                      report_path, env=env, orient=orient)
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

        _send_json(self, 200, {"ok": True, "cancelled": cancelled,
                               "results": results})

    def _set_binary(self):
        """First-run wizard target (ROADMAP v0.4a). Validates the path REALLY
        is the engine (usage probe), then rebinds the module globals the
        import-time probe filled (a stale enum surface would keep serving
        the fallback lists after a successful setup)."""
        global BINARY, PATTERNS, MATERIALS, LOAD_TYPES, PATTERNS_SOURCE,             MATERIALS_SOURCE, LOADS_SOURCE, SURFACE_FILTERED, EXTRA_LOCKS,             EXTRA_LOCKS_SOURCE
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
         LOADS_SOURCE, SURFACE_FILTERED, EXTRA_LOCKS, EXTRA_LOCKS_SOURCE) =             _probe_surface()
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


def _open_browser_later():
    """Open the default browser once the server is about to accept requests.
    Skippable via STRATUM_UI_NO_BROWSER=1 (smoke tests, second instances)."""
    if os.environ.get("STRATUM_UI_NO_BROWSER") == "1":
        return
    threading.Timer(0.5, lambda: webbrowser.open("http://%s:%d" % (HOST, PORT))
                    ).start()


def main():
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
            "stratum.exe 未找到——浏览器打开后在 ① 面板粘贴 stratum.exe 路径完成设置，\n"
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
