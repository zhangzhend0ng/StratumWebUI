#!/usr/bin/env python3
"""DOGFOOD (iter 53): real consumer 3MF from Downloads × the surfaces built
this session — batch progress (/api/history "batch"), export write-back +
sidecar audit, late-cancel-then-analyze. Run: python tests/dogfood_iter53.py
[sample.3mf ...]  (defaults to two known-fast real models)."""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = os.path.join(os.path.expanduser("~"), "Downloads")
DEFAULTS = ["20x3+Shelves.3mf", "blockmodel.3mf"]

FAILURES = []
TOTAL = 0


def check(name, cond, detail=""):
    global TOTAL
    TOTAL += 1
    print("%-56s %s %s" % (name, "PASS" if cond else "FAIL", "" if cond else detail))
    if not cond:
        FAILURES.append(name)


def req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=200)
    h = dict(headers or {})
    if body is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    if method == "POST":
        h["X-Stratum-UI"] = "1"
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    hdrs = dict(r.getheaders())
    c.close()
    return r.status, data, hdrs


def jreq(port, method, path, obj=None):
    st, data, hdrs = req(port, method, path,
                         json.dumps(obj) if obj is not None else None)
    try:
        return st, json.loads(data), hdrs
    except ValueError:
        return st, {"_raw": data[:300]}, hdrs


def main():
    samples = sys.argv[1:] or DEFAULTS
    port = 8877
    env = dict(os.environ, STRATUM_UI_NO_BROWSER="1",
               STRATUM_UI_PORT=str(port),
               STRATUM_UI_CONFIG=os.path.join(tempfile.mkdtemp(), "cfg.json"))
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                            env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                req(port, "GET", "/api/status")
                break
            except OSError:
                time.sleep(0.2)
        for name in samples:
            path = os.path.join(DL, name)
            tag = os.path.basename(name)[:18]
            if not os.path.exists(path):
                check("[%s] sample exists" % tag, False, path)
                continue
            with open(path, "rb") as fh:
                raw = fh.read()
            st, data, _ = req(port, "POST", "/api/upload?name=" + quote(name), raw,
                              {"Content-Type": "application/octet-stream"})
            try:
                up = json.loads(data)
            except ValueError:
                up = {}
            tok = (up or {}).get("token")
            check("[%s] upload real 3mf" % tag, st == 200 and up.get("ok") and tok,
                  "got %s %r" % (st, str(up)[:120]))
            if not tok:
                continue

            # -- batch with progress polling (iter 47 surface) --
            import threading
            seen_progress = []
            stop = [False]

            def poll():
                while not stop[0]:
                    try:
                        _, h, _ = jreq(port, "GET", "/api/history?token=" + tok)
                        b = h.get("batch")
                        if b:
                            seen_progress.append((b["done"], b["total"]))
                    except Exception:
                        pass
                    time.sleep(0.05)

            th = threading.Thread(target=poll)
            th.start()
            combos = [{"label": "d%02d" % i, "params": {"walls": 2 + i}}
                      for i in range(4)]
            t0 = time.time()
            st, bres, _ = jreq(port, "POST", "/api/batch",
                               {"token": tok, "combos": combos})
            dt = time.time() - t0
            stop[0] = True
            th.join()
            ok_all = [r for r in (bres.get("results") or []) if r.get("ok")]
            check("[%s] batch 4 real combos ok" % tag,
                  st == 200 and bres.get("ok") and len(ok_all) == 4,
                  "got %s %d/4 %.1fs %s" % (st, len(ok_all), dt,
                                            str(bres)[:150]))
            check("[%s] progress observed done/total (4)" % tag,
                  any(t == 4 for _, t in seen_progress),
                  "poll saw %s" % (seen_progress[-3:] if seen_progress else None))
            _, h2, _ = jreq(port, "GET", "/api/history?token=" + tok)
            check("[%s] batch key null after completion" % tag,
                  h2.get("batch") is None, "got %r" % h2.get("batch"))
            check("[%s] history has batch entries" % tag,
                  len(h2.get("entries") or []) >= 4)

            # -- export write-back + sidecar audit (iter 46 surface) --
            # iter 53: CAD-bare 3MF (no Metadata/*.config) is gated at the
            # server with a 400 BEFORE the engine call; write-back-capable
            # files still go through. upload reports writable=false for them.
            writable = up.get("writable")
            st, edata, ehdrs = req(port, "POST", "/api/export",
                                   json.dumps({"token": tok, "profile": "balanced"}),
                                   {"Content-Type": "application/json",
                                    "X-Stratum-UI": "1"})
            if writable is False:
                try:
                    emsg = json.loads(edata).get("error", "")
                except ValueError:
                    emsg = ""
                check("[%s] bare 3mf write-back gated 400" % tag,
                      st == 400 and "无切片设置" in emsg,
                      "got %s %r" % (st, emsg[:120]))
                st, pdata, _ = jreq(port, "POST", "/api/export-preview",
                                    {"token": tok, "profile": "balanced"})
                pok = st == 200 and pdata.get("ok")
                check("[%s] bare 3mf preview still works (dry-run)" % tag,
                      pok, "got %s %r" % (st, str(pdata)[:120]))
            else:
                audit = ehdrs.get("X-Stratum-Sidecar")
                check("[%s] export real 3mf write-back" % tag, st == 200,
                      "got %s" % st)
                check("[%s] sidecar audit header present" % tag,
                      bool(audit), "hdrs %s" % list(ehdrs))
                st, sc, _ = jreq(port, "GET", "/api/sidecar?token=" + tok)
                check("[%s] /api/sidecar populated" % tag,
                      st == 200 and isinstance(sc.get("sidecar"), dict),
                      "got %s %r" % (st, str(sc)[:120]))

            # -- late cancel then analyze (iter 44 surface) --
            st, cx, _ = jreq(port, "POST", "/api/cancel", {"token": tok})
            st, an, _ = jreq(port, "POST", "/api/analyze", {"token": tok})
            check("[%s] analyze after late cancel runs" % tag,
                  st == 200 and an.get("ok"),
                  "got %s %r" % (st, str(an)[:120]))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    print("\n%d/%d checks passed%s" % (TOTAL - len(FAILURES), TOTAL,
          "" if not FAILURES else " — failed: %s" % ", ".join(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
