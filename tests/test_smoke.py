#!/usr/bin/env python3
"""End-to-end smoke/regression suite for server.py (stdlib only, no deps).

Greenfield baseline: the repo had no test suite before this file — the
"regression" cases below were verified to FAIL against the pre-fix code by
direct curl evidence (see loop-journal iter 1), not by this script's history.

Run:  python tests/test_smoke.py
Spawns server.py on a free port with STRATUM_UI_NO_BROWSER=1, exercises the
HTTP surface against test_data/ fixtures, asserts, and tears down.
"""

import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import zipfile
import io
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STL = os.path.join(ROOT, "test_data", "beam_100x10x4.stl")
TMF = os.path.join(ROOT, "test_data", "beam_100x10x4.3mf")

FAILURES = []
TOTAL = 0


def check(name, cond, detail=""):
    global TOTAL
    TOTAL += 1
    print("%-52s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        FAILURES.append(name)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def request(port, method, path, body=None, headers=None, ui_header=True):
    h = dict(headers or {})
    if ui_header:
        h.setdefault("X-Stratum-UI", "1")  # required by the server's POST gate
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def jrequest(port, method, path, obj):
    status, data = request(port, method, path, json.dumps(obj),
                           {"Content-Type": "application/json"})
    try:
        return status, json.loads(data)
    except ValueError:
        return status, {"_raw": data[:200]}


def upload(port, qname, path):
    with open(path, "rb") as fh:
        data = fh.read()
    # browsers always send the name percent-encoded (encodeURIComponent);
    # http.client requires an ASCII request line, so mirror that here.
    status, body = request(port, "POST", "/api/upload?name=" + quote(qname), data)
    return status, json.loads(body)


def main():
    # CI/no-engine precheck: without this the suite comes up, the server
    # serves /api/status fine, and every engine-dependent check fails with
    # no hint that the real cause is a missing binary (stderr is DEVNULL).
    if not os.path.isfile(os.path.join(ROOT, "bin", "stratum.exe")):
        print("bin/stratum.exe not found — copy it from the Stratum SDK "
              "release (see README) before running the suite")
        return 2
    port = free_port()
    env = dict(os.environ, STRATUM_UI_PORT=str(port), STRATUM_UI_NO_BROWSER="1")
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                            env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                status, body = request(port, "GET", "/api/status")
                if status == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            print("server did not come up"); return 2

        # T1 — happy path: STL upload + analyze with a param and a lock
        st, up = upload(port, "beam.stl", STL)
        check("T1 upload stl", st == 200 and up["ok"])
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"], "params": {"walls": 4},
                           "locks": ["walls"]})
        inp = (an.get("report") or {}).get("input") or {}
        check("T1 analyze applies walls+lock",
              st == 200 and an.get("ok") and inp.get("walls") == 4
              and inp.get("locked_parameters") == ["walls"],
              "got %s %r" % (st, inp.get("walls")))

        # T51 — REGRESSION (iter 58): /api/history on a FRESH session (upload
        # done, no successful analyze yet — "history" key doesn't exist yet)
        # crashed the GET with KeyError -> empty reply. The runBatch progress
        # timer polls this endpoint, so the crash also killed batch progress.
        st, up51 = upload(port, "beam.stl", STL)
        st51_raw = request(port, "GET",
                           "/api/history?token=" + up51["token"])
        h51 = json.loads(st51_raw[1])
        st51 = st51_raw[0]
        check("T51 fresh-session /api/history answers 200 empty",
              st51 == 200 and h51.get("ok") and h51.get("entries") == []
              and h51.get("batch") is None,
              "got %s %r" % (st51, h51))

        # T52 — REGRESSION (iter 62): --explain is in the analyze argv — the
        # engine prints per-suggestion trust grounding ("grounding: kb_module=
        # ... trust_source=...") to stdout only (JSON identical with/without,
        # probed 0.21.0). If the flag silently drops out of the argv, the UI's
        # engine-console loses the grounding lines with no other symptom.
        st52, an52 = jrequest(port, "POST", "/api/analyze",
                              {"token": up51["token"], "params": {},
                               "locks": []})
        check("T52 --explain grounding lines in analyze console",
              st52 == 200 and an52.get("ok")
              and "grounding:" in (an52.get("console") or ""),
              "st=%s has=%s" % (st52,
                                "grounding:" in (an52.get("console") or "")))

        # T2 — REGRESSION (iter 1 blocker): CJK 3MF filename export must be a
        # well-formed single-status response with an RFC 5987 encoded header.
        st, up = upload(port, "测试梁3d.3mf", TMF)
        check("T2 upload cjk 3mf", st == 200 and up["ok"] and up["is_3mf"])
        raw = io.BytesIO()
        with socket.create_connection(("127.0.0.1", port), timeout=180) as s:
            s.sendall(("POST /api/export HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       "X-Stratum-UI: 1\r\n"
                       "Content-Type: application/json\r\n"
                       "Content-Length: %d\r\n\r\n" % len(json.dumps(
                           {"token": up["token"], "profile": "balanced"}))
                       ).encode() + json.dumps(
                           {"token": up["token"], "profile": "balanced"}).encode())
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                raw.write(chunk)
        data = raw.getvalue()
        head, _, body = data.partition(b"\r\n\r\n")
        check("T2 single status line 200", head.count(b"HTTP/1") == 1
              and head.startswith(b"HTTP/1."))
        check("T2 rfc5987 filename* header",
              b"filename*=UTF-8''" in head and b"%E6%B5%8B" in head,
              head.decode("latin-1", "replace")[:120])
        check("T2 body is 3mf zip", body[:4] == b"PK\x03\x04"
              and "3D/3dmodel.model" in zipfile.ZipFile(io.BytesIO(body)).namelist())

        # T3 — REGRESSION: control chars in the upload name are rejected
        st, body = request(port, "POST", "/api/upload?name=evil%0Ainj.3mf", b"x")
        check("T3 ctrl-char name rejected 400", st == 400)

        # T4 — REGRESSION: locks must be a list (was 502 w/ misleading error)
        st, up = upload(port, "b.stl", STL)
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"], "locks": "walls"})
        check("T4 string locks rejected 400", st == 400)

        # T5 — REGRESSION: same-name sessions must not collide (token-keyed
        # report paths): both sessions analyze fine
        st, u1 = upload(port, "same.stl", STL)
        st, u2 = upload(port, "same.stl", STL)
        ok1 = jrequest(port, "POST", "/api/analyze",
                       {"token": u1["token"], "params": {"walls": 2}})
        ok2 = jrequest(port, "POST", "/api/analyze",
                       {"token": u2["token"], "params": {"walls": 8}})
        check("T5 same-name dual sessions",
              ok1[0] == 200 and ok2[0] == 200
              and ok1[1]["report"]["input"]["walls"] == 2
              and ok2[1]["report"]["input"]["walls"] == 8)

        # T6 — existing guard: unknown param name rejected
        st, up = upload(port, "b.stl", STL)
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"], "params": {"evil": 1}})
        check("T6 unknown param rejected 400", st == 400)

        # T7 — REGRESSION (iter 2): non-local Host header (DNS rebinding)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request("GET", "/api/status", headers={"Host": "evil.com"})
        resp = conn.getresponse(); resp.read(); st7 = resp.status; conn.close()
        check("T7 evil host rejected 403", st7 == 403, "got %s" % st7)

        # T8 — REGRESSION (iter 2): POST without the UI header (cross-site
        # simple requests cannot attach custom headers)
        st, body = request(port, "POST", "/api/upload?name=x.stl", b"x",
                           ui_header=False)
        check("T8 headerless POST rejected 403", st == 403, "got %s" % st)

        # T9 — REGRESSION (iter 3): the server must pass --phase-d so the
        # report carries buckling/fatigue/fracture data (was: run=false forever)
        st, up = upload(port, "b.stl", STL)
        st, an = jrequest(port, "POST", "/api/analyze", {"token": up["token"]})
        pd = (an.get("report") or {}).get("phase_d") or {}
        buck = pd.get("buckling_safety_factor")
        check("T9 phase_d runs via --phase-d",
              st == 200 and pd.get("run") is True
              and isinstance(buck, (int, float)),
              "got run=%r buckling=%r" % (pd.get("run"), buck))

        # T10 — html hook (iter 4): the served page carries the phase-c
        # render block (string-level only — the repo has no JS runtime)
        st, body = request(port, "GET", "/")
        check("T10 html contains phase-c hook",
              st == 200 and b'id="phase-c-detail"' in body
              and b'id="trust-list"' in body)

        # T11 — shape pins (iter 4): the null-gating the UI relies on.
        # Default PLA: aging group all-null ("not evaluated", never 0).
        # ABS: hill48 fields are null (PLA-only calibration) — the UI must
        # skip those rows, not render 0/NaN.
        pc = (an.get("report") or {}).get("phase_c") or {}
        aging = [pc.get("moisture_uptake_pct"), pc.get("modulus_retention"),
                 pc.get("strength_retention"), pc.get("is_degraded"),
                 pc.get("aging_safety_factor")]
        check("T11 PLA aging group all null",
              pc.get("run") is True and all(v is None for v in aging)
              and pc.get("hill48_safety_factor") is not None)
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"], "params": {"material": "ABS"}})
        pc = (an.get("report") or {}).get("phase_c") or {}
        check("T11 ABS hill48 null / plastic SF present",
              st == 200 and pc.get("hill48_safety_factor") is None
              and isinstance(pc.get("plastic_safety_factor"), (int, float)))

        # T12 — REGRESSION (iter 5): the pattern select the UI actually builds
        # from (params[].options, NOT the dead top-level pm.patterns field)
        # must carry the engine's real enum, parsed from usage at startup
        # (was: 7 hardcoded, engine 0.21.0 has 10).
        st, body = request(port, "GET", "/api/params")
        pm = json.loads(body)
        pat = next((p for p in pm["params"] if p["name"] == "pattern"), {})
        opts = pat.get("options") or []
        sf = pm.get("surface") or {}
        check("T12 pattern options synced from engine usage",
              st == 200 and "tri-hexagon" in opts and len(opts) == 10
              and "gyroid" in opts and pat.get("default") in opts
              and sf.get("patterns_source") == "engine-usage",
              "opts=%s src=%r" % (opts, sf.get("patterns_source")))
        check("T12 presets field present (4 entries)",
              len(pm.get("presets") or []) == 4,
              "presets=%r" % (pm.get("presets"),))

        # T13 — parse_usage_enums unit cases (pure function; the probe itself
        # already ran once at this test process's server import)
        sys.path.insert(0, ROOT)
        import server as srv
        sample = ("  --pattern <p>     gyroid|grid|line|triangles|\n"
                  "                    tri-hexagon|3dhoneycomb (legacy spellings\n"
                  "  --material <m>    PLA|PETG|CUSTOM (default PLA). \n")
        p, m, l, dropped = srv.parse_usage_enums(sample)
        check("T13 parse multiline + tail notes",
              p == ["gyroid", "grid", "line", "triangles", "tri-hexagon",
                    "3dhoneycomb"]
              and m == ["PLA", "PETG", "CUSTOM"] and dropped == [])
        p2, m2, l2, d2 = srv.parse_usage_enums("  --pattern <p> a|b (x)\n")
        check("T13 short enum -> None", p2 is None and m2 is None and l2 is None)
        p3, _, _, d3 = srv.parse_usage_enums(
            "  --pattern <p> a|b|3D-Hex|c (legacy)\n")
        check("T13 mixed-case token filtered, not silent",
              p3 == ["a", "b", "c"] and d3 == ["3D-Hex"])
        _, _, l4, _ = srv.parse_usage_enums(
            "  --load <type> compression|bending|torsion|cantilever (axis Z)\n")
        check("T13 loads enum parsed",
              l4 == ["compression", "bending", "torsion", "cantilever"]
              and srv.LOAD_TYPES == l4,
              "loads=%r live=%r" % (l4, srv.LOAD_TYPES))

        # T59 — one-click presets (v0.7): /api/params serves 4 presets in
        # PROFILES order, each covering every PARAM_META name with a value
        # inside the served slider range (or a legal select option).
        pres = pm.get("presets") or []
        by_name = {}
        for m in pm["params"]:
            by_name[m["name"]] = m
        ok59 = (len(pres) == 4
                and [p["name"] for p in pres] == srv.PROFILES
                and all(p.get("label") and p.get("desc") for p in pres))
        for p in pres:
            if len(p.get("params", {})) != len(by_name):
                ok59 = False
            for name, val in (p.get("params") or {}).items():
                m = by_name.get(name)
                if m is None:
                    ok59 = False
                elif m.get("kind") == "select":
                    if val not in (m.get("options") or []):
                        ok59 = False
                elif not (m["min"] <= val <= m["max"]):
                    ok59 = False
        check("T59 presets served in PROFILES order, values in range",
              ok59, json.dumps(pres)[:200])

        # T60 — a preset click sends exactly the preset's params and the
        # engine applies them (T1-style round-trip with the full "safe" set,
        # as the UI's applyPreset collects them).
        st60, up60 = upload(port, "beam.stl", STL)
        safe60 = next((p for p in pres if p["name"] == "safe"), {})
        st60, an60 = jrequest(port, "POST", "/api/analyze",
                              {"token": up60["token"],
                               "params": safe60.get("params", {}),
                               "locks": []})
        inp60 = (an60.get("report") or {}).get("input") or {}
        check("T60 analyze applies safe preset params",
              st60 == 200 and an60.get("ok")
              and inp60.get("walls") == 5
              and inp60.get("infill_density") == 0.4  # 40% echoed as fraction
              and inp60.get("infill_pattern") == "tri-hexagon"
              and inp60.get("material") == "PLA",
              "st=%s input=%r" % (st60, inp60))

        # T61 — presets_for() drift-proofing (pure function): a select value
        # missing from the live enum falls back to that param's default, an
        # out-of-range numeric falls back to its default, and the input
        # PRESETS table is never mutated (returns sanitized copies).
        orig61 = [dict(p, params=dict(p["params"])) for p in srv.PRESETS]
        try:
            srv.PRESETS[0]["params"]["walls"] = 999       # out of range (max 20)
            srv.PRESETS[0]["params"]["print_speed"] = -5  # out of range (min 1)
            dr = srv.presets_for(materials=["PETG"], patterns=["line"])
        finally:
            srv.PRESETS = orig61
        safe61 = dr[0]["params"]
        live61 = srv.presets_for(srv.MATERIALS, srv.PATTERNS)
        check("T61 presets_for drift fallback + no mutation",
              safe61["pattern"] == srv.PATTERN_DEFAULT   # tri-hexagon not in ["line"]
              and safe61["material"] == srv.MATERIAL_DEFAULT  # PLA not in ["PETG"]
              and safe61["walls"] == 2 and safe61["print_speed"] == 50
              and live61[0]["params"]["walls"] == 5      # real enum: original kept
              and live61[0]["params"]["pattern"] == "tri-hexagon"
              and srv.PRESETS[0]["params"]["walls"] == 5,  # input table untouched
              "safe61=%r live=%r" % (safe61, live61[0]["params"]))

        # T14/T15 — REGRESSION (iter 6): invalid startup env must fail fast
        # with a friendly message, never an import traceback. (Pre-fix PORT
        # crashed with a traceback; GRID started "fine" and 502'd per run.)
        def run_server_env(extra, timeout=10):
            env2 = dict(os.environ, STRATUM_UI_NO_BROWSER="1", **extra)
            env2.setdefault("STRATUM_UI_PORT", str(free_port()))
            p2 = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                                  env=env2, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            try:
                out2, err2 = p2.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                p2.kill()
                out2, err2 = p2.communicate()
                return p2.returncode, err2 + b"<TIMEOUT: server kept running>"
            return p2.returncode, err2

        rc14, err14 = run_server_env({"STRATUM_UI_PORT": "abc"})
        check("T14 bad PORT exits friendly",
              rc14 not in (0, None) and b"Traceback" not in err14
              and b"STRATUM_UI_PORT" in err14 and b"abc" in err14,
              "rc=%r err=%r" % (rc14, err14[:120]))
        rc15, err15 = run_server_env({"STRATUM_UI_GRID": "1000"})
        check("T15 bad GRID exits friendly",
              rc15 not in (0, None) and b"Traceback" not in err15
              and b"STRATUM_UI_GRID" in err15,
              "rc=%r err=%r" % (rc15, err15[:120]))

        # T16 — REGRESSION (iter 6): session cap evicts oldest (FIFO)
        port16 = free_port()
        env16 = dict(os.environ, STRATUM_UI_PORT=str(port16),
                     STRATUM_UI_NO_BROWSER="1", STRATUM_UI_MAX_SESSIONS="2")
        proc16 = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                                  env=env16, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    st, body = request(port16, "GET", "/api/status")
                    if st == 200:
                        break
                except OSError:
                    time.sleep(0.2)
            toks = [upload(port16, "m%d.stl" % i, STL)[1]["token"]
                    for i in range(3)]
            st_old, an_old = jrequest(port16, "POST", "/api/analyze",
                                      {"token": toks[0]})
            st_new, an_new = jrequest(port16, "POST", "/api/analyze",
                                      {"token": toks[2]})
            check("T16 session cap FIFO eviction",
                  st_old == 400 and st_new == 200,
                  "old=%s new=%s" % (st_old, st_new))
        finally:
            proc16.terminate()
            proc16.wait(timeout=10)

        # T17 — export carries the sidecar audit header (engine counts only)
        st, up = upload(port, "aud.3mf", TMF)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
        conn.request("POST", "/api/export",
                     body=json.dumps({"token": up["token"]}),
                     headers={"X-Stratum-UI": "1",
                              "Content-Type": "application/json"})
        resp = conn.getresponse(); resp.read()
        audit = resp.getheader("X-Stratum-Sidecar") or ""
        conn.close()
        check("T17 export audit header",
              resp.status == 200 and re.match(r"applied=\d+ skipped=\d+ verified=(true|false)$",
                                              audit),
              "audit=%r" % audit)

        # T18 — dry-run preview endpoint (no 3MF written, engine table back)
        st, pv = jrequest(port, "POST", "/api/export-preview",
                          {"token": up["token"], "profile": "balanced"})
        check("T18 export preview dry-run console",
              st == 200 and pv.get("ok") and "dry-run" in (pv.get("console") or ""),
              "st=%s console=%r" % (st, (pv.get("console") or "")[:80]))

        # T19 — strict-tier writeback still succeeds with the audit header
        st, body = request(port, "POST", "/api/export", json.dumps(
            {"token": up["token"], "profile": "balanced", "strict_tier": True}),
            {"Content-Type": "application/json"})
        # re-request via http.client to read the header
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
        conn.request("POST", "/api/export",
                     body=json.dumps({"token": up["token"], "profile": "balanced",
                                      "strict_tier": True}),
                     headers={"X-Stratum-UI": "1",
                              "Content-Type": "application/json"})
        resp = conn.getresponse(); resp.read()
        audit19 = resp.getheader("X-Stratum-Sidecar") or ""
        conn.close()
        check("T19 strict-tier export audited",
              resp.status == 200 and audit19.startswith("applied="),
              "st=%r audit=%r" % (resp.status, audit19))

        # T20 — _sidecar_header defensive shapes (missing / bad json / good)
        good = os.path.join(ROOT, "test_data", "tmp_sidecar_good.json")
        with open(good, "w", encoding="utf-8") as fh:
            json.dump({"writeback": {"applied_count": 2, "skipped_count": 1,
                                     "verified": True}}, fh)
        bad = os.path.join(ROOT, "test_data", "tmp_sidecar_bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("T20 sidecar header shapes",
              srv._sidecar_header(good) == "applied=2 skipped=1 verified=true"
              and srv._sidecar_header(bad) is None
              and srv._sidecar_header(os.path.join(ROOT, "nope.json")) is None)
        os.remove(good); os.remove(bad)

        # T21 — env flags reach the engine (echo fields prove it)
        st, up = upload(port, "e.stl", STL)
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"],
                           "env": {"load": "torsion", "force": 25}})
        inp = (an.get("report") or {}).get("input") or {}
        check("T21 env load/force echoed",
              st == 200 and inp.get("load_type") == "torsion"
              and inp.get("force_N") == 25,
              "load=%r force=%r" % (inp.get("load_type"), inp.get("force_N")))

        # T22 — server whitelists the load enum (the engine itself only
        # warns and silently falls back to compression — intent would be lost)
        st, body = jrequest(port, "POST", "/api/analyze",
                            {"token": up["token"], "env": {"load": "sideways"}})
        check("T22 unknown load rejected 400", st == 400)

        # T23 — aging inputs unlock phase_c aging group (iter 4 branches)
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"],
                           "params": {"material": "ABS"},
                           "env": {"service_time_s": 7200, "humidity": 90}})
        pc = (an.get("report") or {}).get("phase_c") or {}
        check("T23 ABS aging group populated",
              st == 200 and pc.get("moisture_uptake_pct") is not None
              and pc.get("aging_safety_factor") is not None
              and pc.get("abs_wlf_shift_factor") is not None)

        # T24 — fatigue exponent passthrough + float→int argv hygiene
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"],
                           "env": {"fatigue_cycles": 1000000.0}})
        inp = (an.get("report") or {}).get("input") or {}
        check("T24 fatigue cycles echoed",
              st == 200 and inp.get("requested_fatigue_cycles") == 1000000,
              "got %r" % inp.get("requested_fatigue_cycles"))

        # T25 — schema gate shapes (strict numeric equality; fail-loud on
        # missing/unparseable — a future schema 3 must not misrender)
        ck = srv.schema_supported
        check("T25 schema gate shapes",
              ck({"schema_version": 2}) is True
              and ck({"schema_version": 2.0}) is True
              and ck({"schema_version": 3}) is False
              and ck({"schema_version": 2.9}) is False
              and ck({"schema_version": "2"}) is False
              and ck({}) is False
              and ck(None) is False
              and ck([2]) is False)

        # T26 — --orca-suggest reaches the JSON (structural orca_suggestions,
        # not just console text) on both analyze and compare paths
        st, up = upload(port, "orca.stl", STL)
        st, an = jrequest(port, "POST", "/api/analyze", {"token": up["token"]})
        items = ((an.get("report") or {}).get("orca_suggestions") or {}).get("items")
        st2, an2 = jrequest(port, "POST", "/api/analyze",
                            {"token": up["token"], "compare": True})
        items2 = ((an2.get("report") or {}).get("orca_suggestions") or {}).get("items")
        check("T26 orca_suggestions in analyze+compare",
              st == 200 and isinstance(items, list) and len(items) >= 1
              and st2 == 200 and isinstance(items2, list) and len(items2) >= 1,
              "analyze=%r compare=%r" % (type(items), type(items2)))

        # T27 — orca fallback unit: an old engine whose error names the flag
        # must be retried without --orca-suggest (bonus flag, never fatal)
        import server as srv
        calls = []
        def fake_run(args, timeout=180):
            calls.append(list(args))
            if "--orca-suggest" in args:
                return 1, b"", b"unrecognized argument: --orca-suggest"
            return 0, b"ok", b""
        orig = srv.run_stratum
        srv.run_stratum = fake_run
        try:
            rc, out, err = srv.run_analyze_with_fallback(
                ["m.stl", "--phase-c", "--orca-suggest", "--json", "r.json"])
        finally:
            srv.run_stratum = orig
        check("T27 orca fallback retry",
              rc == 0 and len(calls) == 2 and "--orca-suggest" not in calls[1],
              "calls=%d rc=%d" % (len(calls), rc))

        # T53 — REGRESSION (iter 62): --explain is also a bonus flag — an old
        # engine rejecting it must be retried without it, not fail the run.
        calls53 = []
        def fake_run53(args, timeout=180):
            calls53.append(list(args))
            if "--explain" in args:
                return 1, b"", b"unrecognized argument: --explain"
            return 0, b"ok", b""
        srv.run_stratum = fake_run53
        try:
            rc53, _, _ = srv.run_analyze_with_fallback(
                ["m.stl", "--phase-c", "--orca-suggest", "--explain",
                 "--json", "r.json"])
        finally:
            srv.run_stratum = orig
        check("T53 --explain fallback retry",
              rc53 == 0 and len(calls53) == 2 and "--explain" not in calls53[1],
              "calls=%d rc=%d" % (len(calls53), rc53))

        # T28 — parse_usage_locks unit: the Core: list spans lines (charset
        # must include \s) and a truncated text falls back (iter 14 blocker)
        sample = ("--lock <p[,p..]> Pin parameters ...\n"
                  "Core: walls infill layer_height pattern print_speed\n"
                  "                    nozzle_temperature material load\n"
                  "                    outer_wall_speed retraction_length\n"
                  "                    retraction_speed wipe travel_speed.\n"
                  "  OrcaSlicer keys also accepted")
        lk = srv.parse_usage_locks(sample)
        lk2 = srv.parse_usage_locks("usage without the lock section")
        lk3 = srv.parse_usage_locks("Core: only two names.\n")
        check("T28 parse_usage_locks shapes",
              lk == ["walls", "infill", "layer_height", "pattern", "print_speed",
                     "nozzle_temperature", "material", "load", "outer_wall_speed",
                     "retraction_length", "retraction_speed", "wipe", "travel_speed"]
              and lk2 is None and lk3 is None,
              "got %r / %r / %r" % (lk, lk2, lk3))

        # T29 — layer_height lock reaches the engine and echoes back
        st, up = upload(port, "lock.stl", STL)
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"], "locks": ["layer_height"]})
        inp = (an.get("report") or {}).get("input") or {}
        check("T29 layer_height lock echoed",
              st == 200 and "layer_height" in (inp.get("locked_parameters") or []),
              "locked=%r" % inp.get("locked_parameters"))

        # T30 — session history: two runs with different params snapshot into
        # entries with unique increasing seqs; unknown token is a 400
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"], "params": {"walls": 6}})
        st, hist = jrequest(port, "POST", "/api/analyze",
                            {"token": up["token"], "params": {"walls": 8}})
        import http.client as _hc
        def _get(path):
            c = _hc.HTTPConnection("127.0.0.1", port, timeout=60)
            c.request("GET", path)
            r = c.getresponse()
            data = json.loads(r.read())
            c.close()
            return r.status, data
        st_h, hist = _get("/api/history?token=" + up["token"])
        dead_code, _ = _get("/api/history?token=deadbeef")
        entries = hist.get("entries") or []
        seqs = [e["seq"] for e in entries]
        walls_snap = [e["params"].get("walls") for e in entries]
        check("T30 history entries + bad token 400",
              st == 200 and st_h == 200 and len(entries) >= 2
              and seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
              and {w for w in walls_snap if w is not None} >= {6, 8}
              and all(e["summary"].get("safety_factor") is not None for e in entries)
              and dead_code == 400,
              "entries=%d seqs=%r walls=%r dead=%d"
              % (len(entries), seqs, walls_snap, dead_code))

        # T31 — cancel: a second server with STRATUM_UI_ANALYZE_DELAY=8 runs
        # a deterministic sleep process instead of the engine (the real one
        # finishes in ~0.03s — too short for a non-flaky cancel window).
        port2 = free_port()
        env2 = dict(env, STRATUM_UI_PORT=str(port2),
                    STRATUM_UI_ANALYZE_DELAY="8")
        proc2 = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                                 env=env2, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    st, body = request(port2, "GET", "/api/status", ui_header=False)
                    if st == 200:
                        break
                except OSError:
                    time.sleep(0.2)
            st, up2 = upload(port2, "slow.stl", STL)
            ana_result = {}
            def _slow_analyze():
                ana_result["resp"] = jrequest(
                    port2, "POST", "/api/analyze", {"token": up2["token"]})
            t = threading.Thread(target=_slow_analyze)
            t.start()
            time.sleep(1.5)  # let the analyze register in _inflight
            st, cx = jrequest(port2, "POST", "/api/cancel", {"token": up2["token"]})
            t.join(timeout=20)
            st3, cx3 = jrequest(port2, "POST", "/api/cancel", {"token": up2["token"]})
            r_ = ana_result.get("resp") or ({}, {})
            check("T31 analyze cancel kills run",
                  st == 200 and cx.get("cancelled") is True
                  and not t.is_alive()
                  and r_[0] == 502 and "已取消" in (r_[1].get("error") or "")
                  and st3 == 200 and cx3.get("cancelled") is False,
                  "cancel=%r ana=%r late=%r" % (cx, r_[1].get("error") if len(r_) > 1 else None, cx3))
        finally:
            proc2.terminate()
            proc2.wait(timeout=10)

        # T32 — custom candidate batch: two combos run, labels echo, history
        # grows by 2, a bad combo is a 400 with NO execution (pre-validation)
        st, up3 = upload(port, "batch.stl", STL)
        st, bt = jrequest(port, "POST", "/api/batch", {
            "token": up3["token"],
            "combos": [
                {"label": "厚壁", "params": {"walls": 4}},
                {"label": "薄壁", "params": {"walls": 8}},
            ]})
        oks = [r for r in (bt.get("results") or []) if r.get("ok")]
        st_h2, hist2 = None, None
        import http.client as _hc2
        c = _hc2.HTTPConnection("127.0.0.1", port, timeout=60)
        c.request("GET", "/api/history?token=" + up3["token"])
        hist2 = json.loads(c.getresponse().read())["entries"]
        c.close()
        labels = {e.get("label") for e in hist2}
        st_bad, bt_bad = jrequest(port, "POST", "/api/batch", {
            "token": up3["token"],
            "combos": [{"label": "ok", "params": {"walls": 4}},
                       {"label": "bad", "params": {"nope": 1}}]})
        st_h3, hist3 = None, None
        c = _hc2.HTTPConnection("127.0.0.1", port, timeout=60)
        c.request("GET", "/api/history?token=" + up3["token"])
        hist3 = json.loads(c.getresponse().read())["entries"]
        c.close()
        check("T32 batch combos + pre-validation 400",
              st == 200 and bt.get("ok") and len(bt.get("results") or []) == 2
              and len(oks) == 2
              and {r["label"] for r in bt["results"]} == {"厚壁", "薄壁"}
              and len(hist2) == 2 and labels == {"厚壁", "薄壁"}
              and st_bad == 400 and len(hist3) == 2,
              "st=%s results=%r hist2=%d bad=%s hist3=%d"
              % (st, [r.get("ok") for r in bt.get("results") or []], len(hist2), st_bad, len(hist3))
              )

        # T33 — concurrent same-token analyzes no longer stomp report files:
        # real engine (default sem=2 lets both run), each response must echo
        # ITS OWN walls value
        st, up4 = upload(port, "race.stl", STL)
        r33 = {}
        def _race(w):
            r33[w] = jrequest(port, "POST", "/api/analyze",
                              {"token": up4["token"], "params": {"walls": w}})
        t1 = threading.Thread(target=_race, args=(4,))
        t2 = threading.Thread(target=_race, args=(9,))
        t1.start(); t2.start(); t1.join(60); t2.join(60)
        w4 = ((r33.get(4) or [None, {}])[1].get("report") or {}).get("input", {}).get("walls")
        w9 = ((r33.get(9) or [None, {}])[1].get("report") or {}).get("input", {}).get("walls")
        check("T33 concurrent analyze distinct reports",
              r33.get(4, (0,))[0] == 200 and r33.get(9, (0,))[0] == 200
              and w4 == 4 and w9 == 9,
              "w4=%r w9=%r" % (w4, w9))

        # T34 — bad engine-concurrency env fails fast (symmetry with PORT/GRID)
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, "server.py")],
            env=dict(env, STRATUM_UI_PORT=str(free_port()),
                     STRATUM_UI_MAX_CONCURRENCY="abc"),
            capture_output=True, timeout=30)
        check("T34 bad MAX_CONCURRENCY fail-fast",
              p.returncode != 0 and b"Traceback" not in p.stderr,
              "rc=%d" % p.returncode)

        # T35 — bounded queue: sem=1 + queue=0 + delay runner -> the second
        # concurrent analyze is rejected 503 (not silently queued)
        port3 = free_port()
        env3 = dict(env, STRATUM_UI_PORT=str(port3),
                    STRATUM_UI_ANALYZE_DELAY="3",
                    STRATUM_UI_MAX_CONCURRENCY="1", STRATUM_UI_MAX_QUEUE="0")
        proc3 = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                                 env=env3, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    st, body = request(port3, "GET", "/api/status", ui_header=False)
                    if st == 200:
                        break
                except OSError:
                    time.sleep(0.2)
            st, up5 = upload(port3, "q.stl", STL)
            r35 = {}
            def _q():
                r35["second"] = jrequest(port3, "POST", "/api/analyze",
                                         {"token": up5["token"]})
            tq = threading.Thread(target=_q)
            slow = threading.Thread(target=lambda: jrequest(
                port3, "POST", "/api/analyze", {"token": up5["token"]}))
            slow.start(); time.sleep(1.0); tq.start()
            slow.join(60); tq.join(60)
            check("T35 queue bound rejects 503",
                  r35.get("second", (0,))[0] == 503,
                  "second=%r" % (r35.get("second", (0,))[0],))
        finally:
            proc3.terminate()
            proc3.wait(timeout=10)

        # T36 — sidecar detail endpoint: null before export, populated after
        st, up6 = upload(port, "sc.3mf", TMF)
        import http.client as _hc3
        def _get_sidecar(tok):
            c = _hc3.HTTPConnection("127.0.0.1", port, timeout=180)
            c.request("GET", "/api/sidecar?token=" + tok)
            r = c.getresponse()
            data = json.loads(r.read())
            c.close()
            return r.status, data
        st0, sc0 = _get_sidecar(up6["token"])
        st_e, ex = jrequest(port, "POST", "/api/export",
                            {"token": up6["token"], "profile": "balanced"})
        st1, sc1 = _get_sidecar(up6["token"])
        sc = sc1.get("sidecar") or {}
        check("T36 sidecar detail endpoint",
              st0 == 200 and sc0.get("sidecar") is None
              and st_e == 200
              and st1 == 200 and sc.get("writeback", {}).get("success") is True
              and "writeback_rerun_safety_factor" in sc
              and isinstance(sc.get("pareto_frontier", {}).get("points"), list),
              "before=%r after=%r" % (sc0.get("sidecar"), type(sc)))

        # T37 — first-run wizard: bad path / non-engine exe -> 400; the real
        # engine -> 200 + config persisted (STRATUM_UI_CONFIG keeps the test
        # out of the real home)
        import tempfile as _tf
        cfg_path = os.path.join(_tf.gettempdir(), "stratum_ui_test_cfg.json")
        if os.path.exists(cfg_path):
            os.remove(cfg_path)
        st1, b1 = jrequest(port, "POST", "/api/set-binary",
                           {"path": "C:/no/such/stratum.exe"})
        st2, b2 = jrequest(port, "POST", "/api/set-binary",
                           {"path": sys.executable})  # a REPL, not the engine
        real = os.path.join(ROOT, "bin", "stratum.exe")
        # main test server has no STRATUM_UI_CONFIG; setting rebinds its
        # BINARY in-process — use a dedicated instance to isolate the config
        port4 = free_port()
        env4 = dict(env, STRATUM_UI_PORT=str(port4), STRATUM_UI_CONFIG=cfg_path)
        proc4 = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                                 env=env4, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    st, body = request(port4, "GET", "/api/status", ui_header=False)
                    if st == 200:
                        break
                except OSError:
                    time.sleep(0.2)
            st, b3 = jrequest(port4, "POST", "/api/set-binary", {"path": real})
            cfg_ok = False
            try:
                with open(cfg_path, "r", encoding="utf-8") as fh:
                    cfg_ok = json.load(fh).get("binary") == os.path.abspath(real)
            except (OSError, ValueError):
                pass
            check("T37 set-binary validates + persists",
                  st1 == 400 and b1.get("ok") is False
                  and st2 == 400 and b2.get("ok") is False
                  and st is not None and b3.get("ok") is True
                  and b3.get("engine_version") != "unknown"
                  and cfg_ok,
                  "b1=%r b2=%r b3=%r cfg=%r" % (b1.get("error"), b2.get("error"),
                                                b3.get("ok"), cfg_ok))
        finally:
            proc4.terminate()
            proc4.wait(timeout=10)
            if os.path.exists(cfg_path):
                os.remove(cfg_path)
        # T38 — client-gone writes are silent (iter 23): _send_json must not
        # raise when the client disconnected, at EITHER the header-flush point
        # (end_headers flushes the buffered headers) or the body write.
        # Red-mechanism proof: the pre-fix code shape (bare sequence) is
        # replicated inline and asserted to RAISE, so the test can fail for
        # the reported mechanism, not just pass vacuously.
        sys.path.insert(0, ROOT)
        import server as srv

        class _Gone(object):
            def __init__(self, fail_at):
                self.fail_at = fail_at
                self.wfile = self
            def send_response(self, code): pass
            def send_header(self, k, v): pass
            def end_headers(self):
                if self.fail_at == "headers":
                    raise ConnectionAbortedError()
            def write(self, b):
                if self.fail_at == "body":
                    raise ConnectionAbortedError()

        def _old_send_json(handler, code, payload):  # pre-iter-23 shape
            handler.send_response(code)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            handler.wfile.write(b"{}")

        def raises(fn):
            try:
                fn(); return False
            except ConnectionError:
                return True
        old_raises = raises(lambda: _old_send_json(_Gone("body"), 200, {}))
        ok1 = not raises(lambda: srv._send_json(_Gone("headers"), 200, {}))
        ok2 = not raises(lambda: srv._send_json(_Gone("body"), 200, {}))
        st38, body38 = request(port, "GET", "/api/status")
        j38 = json.loads(body38)
        check("T38 client-gone silent + allow_any_schema key",
              old_raises and ok1 and ok2 and st38 == 200
              and j38.get("allow_any_schema") is False,
              "old_raises=%s ok1=%s ok2=%s" % (old_raises, ok1, ok2))

        # T39 — UNC network path rejected at BOTH producers of the persisted
        # engine path: the wizard endpoint (here) and the config loader
        # (unit-level, below). Existing-share reachability: isfile() is true
        # for a live share, so without the gate the server would EXECUTE the
        # binary from the network.
        st39, b39 = jrequest(port, "POST", "/api/set-binary",
                             {"path": "\\\\server\\share\\stratum.exe"})
        import tempfile as _tf
        cfgp39 = os.path.join(_tf.mkdtemp(prefix="stratum_t39_"), "cfg.json")
        with open(cfgp39, "w", encoding="utf-8") as fh:
            json.dump({"binary": "\\\\server\\share\\stratum.exe"}, fh)
        srv.CONFIG_PATH = cfgp39  # module read CONFIG_PATH at import; patch it
        loaded39 = srv._load_config_binary()
        check("T39 UNC path rejected (wizard + config)",
              st39 == 400 and "UNC" in (b39.get("error") or "")
              and loaded39 is None,
              "st=%s err=%r loaded=%r" % (st39, b39.get("error"), loaded39))
        # positive branch of the same loader: a local path in the config loads
        with open(cfgp39, "w", encoding="utf-8") as fh:
            json.dump({"binary": os.path.abspath(os.path.join(ROOT, "bin",
                                                              "stratum.exe"))}, fh)
        loaded_pos = srv._load_config_binary()
        import shutil as _sh39
        _sh39.rmtree(os.path.dirname(cfgp39), ignore_errors=True)
        srv.CONFIG_PATH = os.environ.get(
            "STRATUM_UI_CONFIG",
            os.path.join(os.path.expanduser("~"), ".stratum-webui.json"))
        check("T39b config loader accepts local path", loaded_pos is not None)

        # T40 — upload extension face: the engine parses by EXTENSION, so the
        # server must keep the real one (an .obj body saved as .stl dies with
        # a misleading "STL: truncated file"). Unknown extension → 400 here.
        obj_body = ("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n"
                    "f 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n").encode()
        st40a, _ = request(port, "POST", "/api/upload?name=tetra.obj", obj_body)
        j40 = json.loads(request(port, "POST", "/api/upload?name=tetra.obj",
                                 obj_body)[1])
        st_an40, an40 = jrequest(port, "POST", "/api/analyze",
                                 {"token": j40.get("token"), "params": {}})
        st40b, b40b_raw = request(port, "POST", "/api/upload?name=" + quote("part.step"),
                                   b"garbage")
        b40b = json.loads(b40b_raw)
        check("T40 obj upload analyzes / step rejected",
              st40a == 200 and st_an40 == 200 and an40.get("ok") is True
              and st40b == 400 and "格式" in (b40b.get("error") or ""),
              "up=%s an=%s err=%r" % (st40a, st_an40, b40b.get("error")))

        # T41 — report download endpoint: null before analyze, full report
        # (schema gate already passed) after, RFC 5987 disposition on
        # download=1, dead token 400
        st41u, up41 = upload(port, "rep.stl", STL)
        q41 = "?token=" + quote(up41["token"])
        st41a, b41a = request(port, "GET", "/api/report" + q41, ui_header=False)
        j41a = json.loads(b41a)
        st41an, _ = jrequest(port, "POST", "/api/analyze",
                             {"token": up41["token"], "params": {}})
        st41b, b41b = request(port, "GET", "/api/report" + q41, ui_header=False)
        j41b = json.loads(b41b)
        st41c, b41c = request(port, "GET", "/api/report" + q41 + "&download=1",
                              ui_header=False)
        cd41 = None
        if st41c == 200:
            # pull the disposition out of a raw exchange
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
            conn.request("GET", "/api/report" + q41 + "&download=1")
            r = conn.getresponse(); r.read()
            cd41 = r.getheader("Content-Disposition"); conn.close()
        st41d, _ = request(port, "GET", "/api/report?token=deadbeefdeadbeef",
                           ui_header=False)
        check("T41 report endpoint lifecycle",
              st41a == 200 and j41a.get("report") is None
              and st41b == 200 and (j41b.get("report") or {}).get("schema_version") == 2
              and st41c == 200 and cd41 and "stratum-report.json" in cd41
              and st41d == 400,
              "a=%s b=%s c=%s cd=%r d=%s" % (st41a, st41b, st41c, cd41, st41d))

        # T42 — STRATUM_UI_MAX_HISTORY: cap 2 keeps the last 2 of 3 runs and
        # the seq stays monotonic (no len+1 repeat after eviction)
        port5 = free_port()
        proc5 = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")],
            env=dict(env, STRATUM_UI_PORT=str(port5),
                     STRATUM_UI_MAX_HISTORY="2"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    st, body = request(port5, "GET", "/api/status", ui_header=False)
                    if st == 200:
                        break
                except OSError:
                    time.sleep(0.2)
            st5, up5 = upload(port5, "h.stl", STL)
            for w in (4, 6, 9):
                jrequest(port5, "POST", "/api/analyze",
                         {"token": up5["token"], "params": {"walls": w}})
            st42, b42 = request(port5, "GET", "/api/history?token="
                                + quote(up5["token"]), ui_header=False)
            j42 = json.loads(b42)
            seqs = [e["seq"] for e in (j42.get("entries") or [])]
            cap_note = json.loads(request(port5, "GET", "/api/status",
                                          ui_header=False)[1]).get("history_cap")
            check("T42 MAX_HISTORY cap + monotonic seq",
                  st42 == 200 and len(seqs) == 2 and seqs == sorted(seqs)
                  and len(set(seqs)) == 2 and cap_note == 2,
                  "seqs=%r cap=%r" % (seqs, cap_note))
        finally:
            proc5.terminate()
            proc5.wait(timeout=10)

        # T43 — --optimize-orient wiring: body.orient adds the engine's
        # orientation block; absent body key keeps the report without one
        st43u, up43 = upload(port, "ori.stl", STL)
        st43a, an43a = jrequest(port, "POST", "/api/analyze",
                                {"token": up43["token"], "params": {},
                                 "orient": True})
        ori43 = ((an43a.get("report") or {}).get("orientation") or {})
        st43b, an43b = jrequest(port, "POST", "/api/analyze",
                                {"token": up43["token"], "params": {}})
        check("T43 optimize-orient wiring",
              st43a == 200 and an43a.get("ok") is True
              and ori43.get("assessable") is True
              and len(ori43.get("candidates") or []) >= 1
              and st43b == 200
              and "orientation" not in (an43b.get("report") or {}),
              "assessable=%r cands=%r" % (ori43.get("assessable"),
                                          len(ori43.get("candidates") or [])))
        # batch top-level orient applies to all combos and lands in history
        st43c, an43c = jrequest(port, "POST", "/api/batch",
                                {"token": up43["token"],
                                 "orient": True,
                                 "combos": [{"label": "o1",
                                             "params": {"walls": 5}}]})
        hist43 = json.loads(request(port, "GET", "/api/history?token="
                                    + quote(up43["token"]),
                                    ui_header=False)[1])
        last43 = (hist43.get("entries") or [{}])[-1]
        check("T43b batch orient end-to-end",
              st43c == 200 and (an43c.get("results") or [{}])[0].get("ok") is True
              and last43.get("orient") is True,
              "st=%s last.orient=%r" % (st43c, last43.get("orient")))

        # T44 — /api/model: dead token 400; STL token round-trips the exact
        # bytes (the repo's beam fixture is ASCII — a tiny BINARY stl is
        # generated inline so the size formula 84+50n is exercised too)
        st44a, b44a = request(port, "GET", "/api/model?token=deadbeefdeadbeef",
                              ui_header=False)
        st44u, up44 = upload(port, "view.stl", STL)
        st44c, b44c = request(port, "GET", "/api/model?token="
                              + quote(up44["token"]), ui_header=False)
        import struct as _st
        tri = _st.pack("<12f", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0) \
            + _st.pack("<H", 0)
        bin44 = b"\x00" * 80 + _st.pack("<I", 2) + tri + tri
        st44d, b44d = request(port, "POST", "/api/upload?name=binstl.stl", bin44)
        up44b = json.loads(b44d)
        st44e, b44e = request(port, "GET", "/api/model?token="
                              + quote(up44b["token"]), ui_header=False)
        with open(STL, "rb") as fh:
            stl_bytes = fh.read()
        check("T44 model bytes round-trip",
              st44a == 400 and st44c == 200 and b44c == stl_bytes
              and st44d == 200 and st44e == 200 and b44e == bin44
              and len(bin44) == 84 + 2 * 50,
              "a=%s c=%s d=%s e=%s" % (st44a, st44c, st44d, st44e))

        # T45 — startup orphan sweep (isolated TMP for the child server):
        # dead-owner dir reclaimed, stale untagged dir reclaimed, LIVE-owner
        # dir untouched. Force kills can never clean up in-process, so the
        # next startup reclaims them (iter 40).
        import tempfile as _t45
        tmp45 = _t45.mkdtemp(prefix="stratum_t45_")
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        os.makedirs(os.path.join(tmp45, "stratum_ui_dead"))
        with open(os.path.join(tmp45, "stratum_ui_dead", "owner.pid"), "w") as fh:
            fh.write(str(dead.pid))
        os.makedirs(os.path.join(tmp45, "stratum_ui_stale"))  # untagged, old
        os.utime(os.path.join(tmp45, "stratum_ui_stale"), (time.time() - 25 * 3600,) * 2)
        os.makedirs(os.path.join(tmp45, "stratum_ui_live"))
        with open(os.path.join(tmp45, "stratum_ui_live", "owner.pid"), "w") as fh:
            fh.write(str(os.getpid()))  # this test process = alive owner
        port6 = free_port()
        proc6 = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")],
            env=dict(env, STRATUM_UI_PORT=str(port6),
                     TMP=tmp45, TEMP=tmp45),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    st, body = request(port6, "GET", "/api/status", ui_header=False)
                    if st == 200:
                        break
                except OSError:
                    time.sleep(0.2)
            g1 = os.path.isdir(os.path.join(tmp45, "stratum_ui_dead"))
            g2 = os.path.isdir(os.path.join(tmp45, "stratum_ui_stale"))
            g3 = os.path.isdir(os.path.join(tmp45, "stratum_ui_live"))
            check("T45 orphan sweep (dead/stale reclaimed, live kept)",
                  not g1 and not g2 and g3,
                  "dead=%s stale=%s live=%s" % (g1, g2, g3))
        finally:
            proc6.terminate()
            proc6.wait(timeout=10)
            import shutil as _sh45
            _sh45.rmtree(tmp45, ignore_errors=True)

        # T46 — REGRESSION (iter 44): a LATE /api/cancel (nothing in flight,
        # cancelled=false) must not leave a sticky flag that swallows the
        # NEXT single analyze with a spurious "已取消" before the engine runs.
        st, up = upload(port, "late.stl", STL)
        st, cx = jrequest(port, "POST", "/api/cancel", {"token": up["token"]})
        check("T46 late cancel answers cancelled=false",
              st == 200 and cx.get("ok") and cx.get("cancelled") is False,
              "got %s %r" % (st, cx))
        st, an = jrequest(port, "POST", "/api/analyze",
                          {"token": up["token"]})
        check("T46 analyze after late cancel runs (not spurious 已取消)",
              st == 200 and an.get("ok"),
              "got %s %r" % (st, an.get("error")))

        # T47 — REGRESSION (iter 47): /api/history must ALWAYS carry the
        # "batch" key (null when idle — consumers must not distinguish
        # missing-key vs null) and report done/total while a batch runs.
        st, _raw = request(port, "GET", "/api/history?token=" + up["token"])
        h = json.loads(_raw)
        check("T47 history carries batch key (null when idle)",
              st == 200 and "batch" in h and h["batch"] is None,
              "got %s %r" % (st, h.get("batch")))
        st, b = jrequest(port, "POST", "/api/batch",
                         {"token": up["token"],
                          "combos": [{"label": "c1", "params": {}},
                                     {"label": "c2", "params": {}}]})
        check("T47 batch 2-combo ok and uncancelled",
              st == 200 and b.get("ok") and b.get("cancelled") is False
              and len(b.get("results") or []) == 2,
              "got %s %r" % (st, b))
        st, _raw2 = request(port, "GET", "/api/history?token=" + up["token"])
        h2 = json.loads(_raw2)
        check("T47 batch counter cleared after completion (null again)",
              st == 200 and h2.get("batch") is None,
              "got %s %r" % (st, h2.get("batch")))

        # T48 — REGRESSION (iter 53, dogfooded on a real CAD-bare export):
        # a .3mf with no Metadata/*.config uploads fine (analysis works) but
        # /api/export must 400 BEFORE the engine call; --dry-run preview is
        # NOT gated (engine rc=0 without settings).
        st, up48 = upload(port, "bare.3mf",
                          os.path.join(ROOT, "test_data", "bare_no_metadata.3mf"))
        check("T48 bare 3mf uploads, writable=false",
              st == 200 and up48.get("ok") and up48.get("writable") is False,
              "got %s %r" % (st, up48.get("writable")))
        st, ex48 = jrequest(port, "POST", "/api/export",
                            {"token": up48["token"], "profile": "balanced"})
        check("T48 bare 3mf export gated 400",
              st == 400 and "无切片设置" in (ex48.get("error") or ""),
              "got %s %r" % (st, ex48.get("error")))
        st, pv48 = jrequest(port, "POST", "/api/export-preview",
                            {"token": up48["token"], "profile": "balanced"})
        check("T48 bare 3mf preview not gated (dry-run runs)",
              st == 200 and pv48.get("ok"),
              "got %s %r" % (st, str(pv48)[:120]))
        # writable fixture pins the positive flag (T17 covers its export)
        st, up49 = upload(port, "w.3mf", TMF)
        check("T48 fixture 3mf writable=true",
              st == 200 and up49.get("writable") is True,
              "got %s %r" % (st, up49.get("writable")))

        # T49 — REGRESSION (iter 53/55): PK magic but broken central directory
        # is CORRUPT, not a CAD-bare export — distinct 400 message (the
        # bare-export hint would send the user hunting for a "source 3MF"
        # that cannot fix a broken zip).
        broken49 = os.path.join(ROOT, "test_data", "tmp_broken_zip.3mf")
        with open(broken49, "wb") as fh49:
            fh49.write(bytes([0x50, 0x4B, 3, 4]) + bytes(64))
        try:
            st, up49b = upload(port, "broken.3mf", broken49)
        finally:
            try:
                os.remove(broken49)
            except OSError:
                pass
        check("T49 PK-magic broken zip -> distinct 400",
              st == 400 and "结构损坏" in (up49b.get("error") or ""),
              "got %s %r" % (st, up49b.get("error")))

        # T50 — UI split modules are served (REGRESSION: index.html now loads
        # report.js / stl-preview.js via <script src>; a missing route breaks
        # the whole UI after refresh even though / serves fine). GET paths are
        # not behind the POST header gate, so plain GETs suffice.
        st_js, body_js = request(port, "GET", "/report.js")
        check("T50 report.js served as javascript",
              st_js == 200 and body_js.startswith(b'"use strict";')
              and b"renderReport" in body_js,
              "got %s %d bytes" % (st_js, len(body_js)))
        st_pv, body_pv = request(port, "GET", "/stl-preview.js")
        check("T50 stl-preview.js served as javascript",
              st_pv == 200 and b"stlParse" in body_pv,
              "got %s %d bytes" % (st_pv, len(body_pv)))
        # T54 — REGRESSION (iter 63): orientation overlay wiring survives —
        # renderer declares the entry points AND report.js actually calls
        # them (a silent de-wire leaves the ④ rows clickable with no effect)
        check("T54 orientation overlay wired",
              st_pv == 200
              and b"function stlSetOrient" in body_pv
              and b"function stlSelectOrient" in body_pv
              and b"function stlOrientToDir" in body_pv
              and b"stlSetOrient(" in body_js
              and b"stlSelectOrient(" in body_js,
              "pv=%s js=%s" % (st_pv, st_js))
        st_trav, _ = request(port, "GET", "/server.py")
        check("T50 static whitelist blocks other files (404)",
              st_trav == 404, "got %s" % st_trav)

        # T55 — REGRESSION (iter 65): /api/status carries ui_version (bug
        # reports from distributed installs need the build vintage; dropped
        # key silently reverts the banner to "UI …")
        st55, st_body55 = request(port, "GET", "/api/status")
        j55 = json.loads(st_body55)
        _, idx55 = request(port, "GET", "/")
        check("T55 /api/status exposes ui_version",
              st55 == 200 and isinstance(j55.get("ui_version"), str)
              and j55["ui_version"] and b"ui-ver" in idx55,
              "got %r / banner wired=%s"
              % (j55.get("ui_version"), b"ui-ver" in idx55))

        # T56 — REGRESSION (iter 67): non-finite vertices (NaN via malformed
        # ASCII token / NaN-Inf float32 patterns in binary) must be skipped
        # by stlParse, else NaN reaches bbox → radius/dist broken → preview
        # silently renders blank instead of degrading. Tooth-verified: 4/5
        # sub-checks FAIL on the pre-guard code.
        r56 = subprocess.run(
            ["node", os.path.join(ROOT, "tests", "stl_nan_check.js")],
            capture_output=True, text=True, timeout=60)
        check("T56 stlParse non-finite vertex guard (node)",
              r56.returncode == 0 and "PASS" in r56.stdout
              and "FAIL" not in r56.stdout,
              (r56.stdout + r56.stderr).strip()[-200:])

        # T57 — REGRESSION (iter 68): phase_b.diagnostics three-state render
        # (cg_converged true→hint / false→warning / absent→silent; real
        # sample's part_visibility_warning must surface with "Phase B: "
        # prefix). Tooth-verified: 4/6 sub-checks FAIL pre-render code.
        r57 = subprocess.run(
            ["node", os.path.join(ROOT, "tests", "report_render_check.js")],
            capture_output=True, text=True, timeout=60)
        check("T57 phase_b.diagnostics render (node)",
              r57.returncode == 0 and "PASS" in r57.stdout
              and "FAIL" not in r57.stdout,
              (r57.stdout + r57.stderr).strip()[-200:])

        # T58 — BROWSER E2E (iter 78): real headless Chrome over CDP runs
        # the real page's renderReport with the real sample report. The vm
        # stubs in T57 cannot catch real-DOM/real-script-order breakage.
        # rc 3 = no Chrome present (loud SKIP); rc 0 requires all green.
        r58 = subprocess.run(
            ["node", os.path.join(ROOT, "tests", "browser_render_check.js")],
            capture_output=True, text=True, timeout=120)
        check("T58 browser renderReport E2E (chrome)",
              r58.returncode in (0, 3),
              ("SKIP(no chrome)" if r58.returncode == 3 else
               (r58.stdout + r58.stderr).strip()[-200:]))
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    # hard-killed servers never run their shutdown rmtree — reclaim the
    # leaked stratum_ui_* work dirs via the SERVER'S OWN orphan sweep
    # (owner.pid liveness check). A bare glob-rmtree here once deleted the
    # WORK_DIR of a CONCURRENTLY RUNNING WebUI instance (live-reproduced
    # iter 58: another session's test run killed this suite's server mid-
    # test, every later analyze failed "miniz: cannot open ZIP"). Not a
    # zero-kill guarantee: an OpenProcess permission denial reads as dead
    # (same-user CI concurrency — the actual threat model — is safe).
    srv._sweep_orphan_workdirs()

    print("\n%d/%d checks passed%s" % (TOTAL - len(FAILURES), TOTAL,
          "" if not FAILURES else " — failed: %s" % ", ".join(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
