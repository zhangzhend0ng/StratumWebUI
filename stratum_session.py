"""Stratum engine session client (W1 D3/D4 consumption; engine 0.28.0+).

The engine's `--session-serve tcp:<port>` mode keeps geometry+voxelization
warm and answers NDJSON queries: {op, query_id, ...} -> {query_id, ok, ...}.
Protocol facts (probed 2026-10-29 against 0.28.0):

  hello    -> {ok, version, schema_version, ops, cached_models, cached_gcodes}
  analyze  -> {ok, report{schema-4 same shape as CLI --json}, cached_grid,
              fem_cache_hit}; params/env replace-not-stack per query
  estimate -> same report shape, input.estimate_mode=True marks the run
  errors   -> {ok: false, error: {code, message}}; a failed query leaves
              the session alive (probed with a missing model path)

Scope note: this is a SERVER-side sibling (imported by server.py, never by
the agent modules — those receive it through the registry ctx). It touches
no orca/plugin symbols.
"""

import json
import secrets
import socket
import subprocess
import threading
import time

QUERY_TIMEOUT_S = 200.0  # the CLI budget is 180s + margin
SPAWN_TIMEOUT_S = 10.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class StratumSession(object):
    """One long-lived engine session process + connection. Lazily spawned;
    transparently respawned after the engine's idle timeout (default 30min)
    or a crash. All calls serialized under a lock — engine slot semantics
    are serial anyway and one socket is one conversation."""

    def __init__(self, binary):
        self._binary = binary
        self._lock = threading.Lock()
        self._proc = None
        self._sock = None

    # -- lifecycle (caller holds the lock) --------------------------------

    def _stop_locked(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            self._proc = None

    def _spawn_locked(self):
        port = _free_port()
        try:
            self._proc = subprocess.Popen(
                [self._binary, "--session-serve", "tcp:%d" % port],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW)
        except OSError:
            return False
        deadline = time.monotonic() + SPAWN_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                self._sock = socket.create_connection(
                    ("127.0.0.1", port), timeout=5.0)
                return True
            except OSError:
                if self._proc.poll() is not None:
                    break
                time.sleep(0.1)
        self._stop_locked()
        return False

    # -- queries -----------------------------------------------------------

    def call(self, op, **kw):
        """One query -> the parsed reply dict. Never raises: transport
        failures (idle death, crash) answer {ok: false, error{code,message}}
        after ONE respawn attempt, so callers can fall back to the CLI."""
        with self._lock:
            for attempt in (0, 1):
                if self._sock is None and not self._spawn_locked():
                    return {"ok": False, "error": {
                        "code": "session_spawn",
                        "message": "engine session process did not start"}}
                req = dict(kw)
                req["op"] = op
                req["query_id"] = "q%s" % secrets.token_hex(4)
                try:
                    self._sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
                    self._sock.settimeout(QUERY_TIMEOUT_S)
                    buf = b""
                    while not buf.endswith(b"\n"):
                        chunk = self._sock.recv(65536)
                        if not chunk:
                            raise ConnectionError("session closed mid-reply")
                        buf += chunk
                    return json.loads(buf.decode("utf-8", "replace"))
                except (OSError, ValueError):
                    self._stop_locked()
                    if attempt == 1:
                        return {"ok": False, "error": {
                            "code": "session_transport",
                            "message": "engine session unreachable after "
                                       "one respawn attempt"}}
        return {"ok": False, "error": {"code": "unreachable",
                                       "message": "unreachable"}}

    def shutdown(self):
        with self._lock:
            self._stop_locked()
