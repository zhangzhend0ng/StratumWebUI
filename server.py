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

Binary resolution (first match wins):
    1. $STRATUM_BIN
    2. ./bin/stratum.exe            (a convenience copy next to this file)
    3. stratum.exe on PATH
Version string is read from a VERSION.txt next to the binary (the SDK bundle
ships one at the bundle root) so /api/status can report the engine version
without a --version flag (the CLI has none).

Security posture: binds 127.0.0.1 only; subprocess uses a list argv (no
shell); the only CLI flags reachable from the UI are a fixed whitelist
(param flags + --lock + --optimize-3mf profile); models go to a private temp
dir. No code from the uploaded model is ever executed.
"""

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("STRATUM_UI_PORT", "8765"))
GRID = os.environ.get("STRATUM_UI_GRID", "16")

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "index.html")
WORK_DIR = tempfile.mkdtemp(prefix="stratum_ui_")
_session_lock = threading.Lock()
_sessions = {}  # token -> {"path": str, "name": str, "is_3mf": bool}

# ---------------------------------------------------------------------------
# Binary resolution + version
# ---------------------------------------------------------------------------

def resolve_binary():
    env = os.environ.get("STRATUM_BIN")
    if env and os.path.isfile(env):
        return os.path.abspath(env)
    local = os.path.join(HERE, "bin", "stratum.exe")
    if os.path.isfile(local):
        return os.path.abspath(local)
    which = shutil.which("stratum.exe")
    if which:
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
# Param surface (mirrors the CLI flags; the engine hard-rejects invalid values)
# ---------------------------------------------------------------------------

PATTERNS = ["line", "gyroid", "cubic", "triangles", "honeycomb", "grid", "rectilinear"]
MATERIALS = ["PLA", "PETG", "ABS", "CUSTOM"]

# name -> (CLI flag, kind) ; kind in {int, float, select}
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

PARAM_META = [
    {"name": "walls", "label": "壁数", "kind": "int",
     "min": 1, "max": 20, "step": 1, "unit": "", "hint": "1-20"},
    {"name": "infill", "label": "填充率", "kind": "float",
     "min": 0, "max": 100, "step": 1, "unit": "%", "hint": "0-100 %"},
    {"name": "pattern", "label": "填充图案", "kind": "select",
     "options": PATTERNS, "unit": ""},
    {"name": "material", "label": "材料", "kind": "select",
     "options": MATERIALS, "unit": ""},
    {"name": "nozzle_diameter", "label": "喷嘴直径", "kind": "float",
     "min": 0.1, "max": 2.0, "step": 0.05, "unit": "mm", "hint": "0.1-2.0 mm"},
    {"name": "nozzle_temperature", "label": "喷嘴温度", "kind": "float",
     "min": 150, "max": 350, "step": 5, "unit": "°C", "hint": "150-350 °C"},
    {"name": "bed_temperature", "label": "热床温度", "kind": "float",
     "min": 0, "max": 200, "step": 5, "unit": "°C", "hint": "0-200 °C"},
    {"name": "print_speed", "label": "打印速度", "kind": "float",
     "min": 1, "max": 1000, "step": 5, "unit": "mm/s", "hint": "1-1000 mm/s"},
    {"name": "cooling_fan", "label": "冷却风扇", "kind": "float",
     "min": 0, "max": 100, "step": 5, "unit": "%", "hint": "0-100 %"},
]

PROFILES = ["safe", "balanced", "fast", "appearance"]

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


def build_analyze_args(model_path, params, locks, compare, json_path):
    """Build the whitelisted argv for an analyze/compare run."""
    args = [model_path, "--phase-c", "--grid", GRID]
    if compare:
        args.append("--compare-profiles")
    for name, value in params.items():
        flag = PARAM_FLAGS.get(name)
        if flag is None:
            raise ValueError("unknown parameter: %r" % name)
        args.append(flag[0])
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

def _send_json(handler, code, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


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


class StratumHandler(BaseHTTPRequestHandler):
    server_version = "StratumWebUI/0.1"

    # ---- helpers ----------------------------------------------------------

    def _log(self, msg):
        sys.stderr.write("[%s] %s\n" % (self.address_string(), msg))

    # ---- GET ---------------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._serve_index()
        elif path == "/api/status":
            _send_json(self, 200, {
                "ok": True,
                "engine_version": engine_version(BINARY),
                "binary": BINARY or None,
                "binary_found": BINARY is not None,
                "grid": GRID,
            })
        elif path == "/api/params":
            _send_json(self, 200, {
                "ok": True,
                "params": PARAM_META,
                "materials": MATERIALS,
                "patterns": PATTERNS,
                "profiles": PROFILES,
            })
        else:
            _send_json(self, 404, {"ok": False, "error": "not found"})

    def _serve_index(self):
        try:
            with open(INDEX_PATH, "rb") as fh:
                body = fh.read()
        except OSError:
            _send_json(self, 500, {"ok": False, "error": "index.html missing"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- POST ---------------------------------------------------------------

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                self._upload()
            elif path == "/api/analyze":
                self._analyze()
            elif path == "/api/export":
                self._export()
            else:
                _send_json(self, 404, {"ok": False, "error": "not found"})
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
        is_3mf = basename.lower().endswith(".3mf")
        raw = _read_body(self)
        token = secrets.token_hex(8)
        path = os.path.join(WORK_DIR, token + (".3mf" if is_3mf else ".stl"))
        with open(path, "wb") as fh:
            fh.write(raw)
        with _session_lock:
            _sessions[token] = {"path": path, "name": basename, "is_3mf": is_3mf}
        _send_json(self, 200, {"ok": True, "token": token, "name": basename,
                               "is_3mf": is_3mf, "size": len(raw)})

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
        compare = bool(body.get("compare", False))
        for name in params:
            if name not in PARAM_FLAGS:
                raise ValueError("unknown parameter: %r" % name)
        report_path = os.path.join(WORK_DIR,
                                   session["name"] + (".compare" if compare else ".analyze") + ".json")
        args = build_analyze_args(session["path"], params, locks, compare, report_path)
        self._log("run: %s" % " ".join(os.path.basename(BINARY)) + " ...")
        rc, out, err = run_stratum(args)
        if rc != 0:
            _send_json(self, 502, {
                "ok": False,
                "error": "stratum.exe 失败 (rc=%d): %s" % (rc, err.decode("utf-8", "replace")[:400]),
            })
            return
        try:
            with open(report_path, "r", encoding="utf-8") as fh:
                report = json.load(fh)
        except (OSError, ValueError) as exc:
            _send_json(self, 502, {"ok": False, "error": "报告解析失败: %s" % exc})
            return
        # console: pass through the engine's own stdout so the UI can show the
        # CLI's "Recommended:" line verbatim (no recommendation logic in JS).
        _send_json(self, 200, {"ok": True, "report": report,
                               "console": out.decode("utf-8", "replace")})

    def _export(self):
        body = _read_json_body(self)
        session = self._session(body)
        if not session["is_3mf"]:
            _send_json(self, 400, {"ok": False,
                                   "error": "写回需要 .3mf 输入（STL 没有切片配置可写回）"})
            return
        profile = body.get("profile") or "balanced"
        if profile not in PROFILES:
            raise ValueError("unknown profile: %r" % profile)
        out_path = os.path.join(WORK_DIR, "out_" + session["name"])
        args = [session["path"], "--optimize-3mf", profile,
                "--out", out_path, "--grid", GRID]
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
        download_name = "%s_optimized_%s.3mf" % (session["name"][:-4], profile)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition",
                         "attachment; filename=%s" % download_name)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # keep the console clean; use _log for real events


def main():
    if BINARY is None:
        sys.stderr.write(
            "stratum.exe 未找到。请设置 STRATUM_BIN，或把 stratum.exe 放到 bin/ 下。\n"
            "（SDK 发布物 stratum-sdk-0.21.0 的 bin/ 内含 stratum.exe）\n")
        return 1
    sys.stderr.write("Stratum WebUI: engine=%s (%s)\n" % (engine_version(BINARY), BINARY))
    sys.stderr.write("  -> http://%s:%d  (Ctrl+C 退出)\n" % (HOST, PORT))
    httpd = ThreadingHTTPServer((HOST, PORT), StratumHandler)
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
