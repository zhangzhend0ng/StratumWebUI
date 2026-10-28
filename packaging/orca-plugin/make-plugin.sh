#!/usr/bin/env bash
# Assemble the Stratum Orca plugin folder from this repo's working tree.
#
#   packaging/orca-plugin/make-plugin.sh [dest]
#
# Default dest: packaging/orca-plugin/dist/stratum (copy that folder — or pass
# it as dest — into <Orca data_dir>/orca_plugins/). Contents:
#
#   stratum.py             entry (single .py at the root, per the plugin
#                          discovery rule); spawns the server thread and opens
#                          the dock panel
#   app/                   vendored UNCHANGED from the repo root:
#     server.py            all paths derive from dirname(__file__), so this
#                          layout needs zero patching
#     index.html report.js stl-preview.js
#     sample/beam_100x10x4.stl
#     bin/stratum.exe      engine (MIT, ships with the product by design)
#   .install_state.json    enabled=true + threading pre-grant ("thread"
#                          sentinel; everything else the plugin does runs in
#                          its own spawned thread, outside the audit context)
#
# Also emits a distributable zip beside dist/: stratum-orca-<version>.zip
# (version parsed from stratum_orca.py's PEP 723 header), containing the
# stratum/ folder at the archive root — unzip straight into orca_plugins/.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
dest="${1:-$here/dist/stratum}"

# Plugin version — single source is stratum_orca.py's PEP 723 block; the zip
# name and .install_state.json both derive from it so they cannot drift.
ver="$(python - "$here/stratum_orca.py" <<'PYVER'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'^# version = "([^"]+)"', src, re.M)
if not m:
    sys.exit("version not found in stratum_orca.py header")
print(m.group(1))
PYVER
)"

rm -rf "$dest"
mkdir -p "$dest/app/bin" "$dest/app/sample"

cp "$here/stratum_orca.py" "$dest/stratum.py"
cp "$repo/server.py" "$repo/index.html" "$repo/report.js" "$repo/stl-preview.js" "$dest/app/"
# v0.5: the plugin's DEDICATED workflow page (选取→参数优化→切片评估→迭代优
# 化). Served by the vendored server.py via its UI_STATIC allowlist entry
# (/plugin.html); the panel iframe points here. The standalone WebUI files
# above still ship for browser-tab debugging.
cp "$here/plugin.html" "$dest/app/plugin.html"
# v0.10: the agent modules ride next to server.py (its plain imports resolve
# via sys.path — stratum.py appends app/ in the server thread).
cp "$repo/agent_tools.py" "$repo/agent_harness.py" "$dest/app/"
# v0.7.2: bundled dependency wheels. NOT at the plugin root — discovery
# treats any root .whl next to the .py entry as a second entry and rejects
# the plugin ("contains both .py and .whl entry files", PluginFsUtils). The
# wheels ride in vendor/ (invisible to the root entry scan); stratum.py
# self-extracts them onto sys.path once, in its un-audited server thread.
mkdir -p "$dest/vendor"
for whl in "$here"/vendor/*.whl; do
  cp "$whl" "$dest/vendor/"
done
cp "$repo/sample/beam_100x10x4.stl" "$dest/app/sample/"
cp "$repo/bin/stratum.exe" "$dest/app/bin/"

# Build-time bridge injection: append the orca-session listener to the DIST
# copy of index.html only — the repo source stays untouched. The listener is
# inert in standalone runs (nobody posts stratum-orca-* messages outside the
# plugin panel) and reuses the page's own upload-success path (applySession +
# persistSession + analyze). v0.4 also injects an「应用到盘上对象」CTA next to
# the summary cards (relay: iframe -> top document -> plugin apply flow).
python - "$dest/app/index.html" <<'PYEOF'
import io, sys

path = sys.argv[1]
with io.open(path, "r", encoding="utf-8") as fh:
    html = fh.read()

marker = "stratum-orca-session"
if marker in html:
    sys.exit("bridge already injected")

bridge = u"""
<script>
/* Orca plugin bridge — injected at plugin build time by make-plugin.sh.
   Receives messages relayed from the panel's top document:
   - stratum-orca-session: a plate-picked model session, adopted through the
     page's own upload-success path (applySession + persistSession + analyze)
   - stratum-orca-analyze: the plugin attached a real sliced G-code to the
     current session server-side; re-run analyze so the response brings the
     stress-tuned G-code channel (the page's own chip syncs from it).
   - stratum-orca-apply-done: echo of the plugin's 写回 result, shown next to
     the injected CTA button (the toolbar status line stays authoritative).
   Standalone runs never receive these messages, so this is inert there. */
(function () {
  window.addEventListener("message", function (ev) {
    if (!ev.data) return;
    if (ev.data.type === "stratum-orca-session") {
      var j = ev.data.session;
      if (!j || !j.token || !j.name) return;
      resetTuningState();
      applySession(j);
      persistSession();
      var msg = document.getElementById("upload-msg");
      if (msg) {
        msg.className = "ok";
        msg.textContent = "已从 Orca 盘选取 " + j.name +
          (ev.data.note ? "（" + ev.data.note + "）" : "");
      }
      analyze(false);
      return;
    }
    if (ev.data.type === "stratum-orca-analyze") {
      if (!state.token) return;
      analyze(false);
      return;
    }
    if (ev.data.type === "stratum-orca-apply-done") {
      var st = document.getElementById("stratum-orca-apply-status");
      if (st) st.textContent = (ev.data.ok ? "\\u2713 " : "\\u2717 ") +
        (ev.data.ok ? (ev.data.note || "已写回") : (ev.data.error || "写回失败"));
    }
  });
  /* v0.4 apply-to-plate CTA: mounted as a SIBLING right after
     #summary-cards (verdict/advice cards). The container itself is static —
     renderReport only rebuilds its children — and it is visible in both
     simple and advanced mode (#rec-items / #orca-list are folded away in
     simple mode, so they cannot host the button). Click relays through the
     top document into the plugin's existing apply flow, identity guard
     included; the toolbar 写回 Orca button remains as fallback. If the
     mount point ever drifts, this degrades silently — no button, toolbar
     still works. */
  var mount = document.getElementById("summary-cards");
  if (mount && mount.parentNode) {
    var row = document.createElement("div");
    row.id = "stratum-orca-apply-row";
    row.setAttribute("data-i18n-skip", "1");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "rec-apply";
    btn.textContent = "\\u21e9 \\u5e94\\u7528\\u5230\\u76d8\\u4e0a\\u5bf9\\u8c61";
    btn.title = "\\u628a\\u300c\\u4ece\\u76d8\\u9009\\u53d6\\u300d\\u4f1a\\u8bdd\\u62a5\\u544a\\u91cc\\u7684 Orca \\u5efa\\u8bae\\uff0c" +
      "\\u4f5c\\u4e3a\\u5bf9\\u8c61\\u7ea7\\u53c2\\u6570\\u8986\\u76d6\\u5199\\u56de\\u8be5\\u5bf9\\u8c61" +
      "\\uff08\\u9700\\u5f53\\u524d\\u9009\\u4e2d\\u7684\\u4ecd\\u662f\\u9009\\u53d6\\u65f6\\u7684\\u90a3\\u4e2a\\u5bf9\\u8c61\\uff09";
    var st = document.createElement("span");
    st.id = "stratum-orca-apply-status";
    st.className = "hint";
    st.style.marginLeft = "8px";
    btn.addEventListener("click", function () {
      st.textContent = "\\u5199\\u56de\\u4e2d\\u2026";
      window.parent.postMessage({ type: "stratum-orca-apply" }, "*");
    });
    row.appendChild(btn);
    row.appendChild(st);
    mount.parentNode.insertBefore(row, mount.nextSibling);
  }
})();
</script>
"""

closer = u"</body>"
idx = html.rfind(closer)
if idx < 0:
    sys.exit("no </body> found in index.html")
html = html[:idx] + bridge + html[idx:]
with io.open(path, "w", encoding="utf-8", newline="") as fh:
    fh.write(html)
print("bridge injected into", path)
PYEOF

# v0.8: pre-grant the bundled engine's bin dir as a PROCESS TREE grant
# ("<dir>/*" — the host audit matches a tree grant against the command
# line's first token, the executable path; verbatim grants can never cover
# analyze's per-run temp paths, so without this every fresh install dies
# on "subprocess.Popen: audit permission required" at the first analyze).
# $APPDATA is the standard install root on this box; other machines get
# the empty fallback and approve via the host's own prompt flow.
# The events/network_socket pre-grants below mirror the set the host
# itself records once a user approves the plugin (socket.__new__ +
# bind to 127.0.0.1:0 — the server always binds loopback port 0);
# without them a fresh full-dir deploy wipes the grants and the server
# thread dies on the first socket operation. network_http pre-grants the
# DeepSeek host (the default API backend) so the direct-API conversation
# works out of the box — host-wide canonical grant, the KEY itself lives
# only in the machine-local chat_settings.json and never ships in this zip.
BIN_GRANT=""
if [ -n "$APPDATA" ]; then
  # json.dumps emits the path with JSON-escaped backslashes (C:\\Users\\…);
  # [1:-1] strips the surrounding quotes so the heredoc value stays valid JSON.
  BIN_GRANT="$(python -c 'import json,os;print(json.dumps(os.path.join(os.environ["APPDATA"],"Snapmaker_Orca","orca_plugins","stratum","app","bin"))[1:-1])')"
fi

# v0.9: the AI conversation spawns the codex CLI (node.exe <npm>/codex.js, or
# $CODEX_BIN) — its executable also needs a process tree grant or every
# assistant turn dies on the same "subprocess.Popen: audit permission
# required". Node's dir is granted as a tree (the audit matches the first
# token only); empty when node is not resolvable — that machine approves
# through the host's own prompt flow.
NODE_GRANT=""
if command -v node >/dev/null 2>&1; then
  NODE_GRANT="$(python -c 'import json,os,shutil;w=shutil.which("node");print(json.dumps(os.path.dirname(w))[1:-1] if w else "")' 2>/dev/null)"
  [ -z "$NODE_GRANT" ] && NODE_GRANT=""
fi
CODEX_GRANT=""
if [ -n "${CODEX_BIN:-}" ]; then
  CODEX_GRANT="$(CODEX_BIN="${CODEX_BIN}" python -c 'import json,os;print(json.dumps(os.path.dirname(os.path.abspath(os.environ["CODEX_BIN"])))[1:-1])')"
fi
# assembled grant entries — ", \"<dir>/*\"" per extra grant, nothing when empty
PROC_EXTRA=""
[ -n "$NODE_GRANT" ] && PROC_EXTRA="$PROC_EXTRA, \"$NODE_GRANT/*\""
[ -n "$CODEX_GRANT" ] && PROC_EXTRA="$PROC_EXTRA, \"$CODEX_GRANT/*\""

cat > "$dest/.install_state.json" <<EOF
{
  "installed_from": "local",
  "installed_version": "$ver",
  "plugin_name": "Stratum",
  "enabled": true,
  "permissions": {
    "events": ["FsRead:open", "Socket:socket.__new__", "FsReadWrite:open"],
    "fs_read": [],
    "fs_readwrite": [],
    "network_http": ["https://api.deepseek.com"],
    "network_socket": ["('127.0.0.1', 0)"],
    "process": ["$BIN_GRANT/*"$PROC_EXTRA],
    "threading": ["thread"]
  }
}
EOF

# v0.39: chat settings ride in the LOCAL deploy tree (user direction) so a
# full rm -rf + cp deploy no longer wipes the configured backend. Source
# priority: the live deployed copy > DeepSeek default from $DEEPSEEK_API_KEY
# > none. The API key stays in the local tree only — the ZIP step below
# strips it (distribution artifact must not carry secrets).
CHAT_SETTINGS_SRC="$APPDATA/Snapmaker_Orca/orca_plugins/stratum/chat_settings.json"
if [ -n "$APPDATA" ] && [ -f "$CHAT_SETTINGS_SRC" ]; then
  cp "$CHAT_SETTINGS_SRC" "$dest/chat_settings.json"
  echo "chat settings: carried from live deployment"
elif [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  python - "$dest" <<'PYEOF'
import json, os, sys
dest = sys.argv[1]
s = {"backend": "openai", "codex_bin": "", "cli_args": "",
     "model": "deepseek-flash",
     "api_base": "https://api.deepseek.com/v1",
     "api_key": os.environ["DEEPSEEK_API_KEY"], "extra_json": ""}
with open(os.path.join(dest, "chat_settings.json"), "w", encoding="utf-8") as fh:
    json.dump(s, fh, ensure_ascii=False, indent=2)
print("chat settings: DeepSeek default from DEEPSEEK_API_KEY")
PYEOF
fi

python -m py_compile "$dest/stratum.py" "$dest/app/agent_tools.py" "$dest/app/agent_harness.py"
rm -rf "$dest/__pycache__" "$dest/app/__pycache__"

# Distributable zip: stratum/ at the archive root (unzip into orca_plugins/
# or use the Plugins dialog's local-install). port.txt/logs can only exist
# in a DEPLOYED copy, but the walk skips them anyway — a custom dest that
# was previously live can never leak runtime state into the artifact.
zip_dir="$here/dist"
mkdir -p "$zip_dir"
python - "$dest" "$zip_dir/stratum-orca-$ver.zip" <<'PYZIP'
import json, os, sys, zipfile

src, zpath = sys.argv[1], sys.argv[2]
skip_dirs = {"__pycache__", "logs", "__extracted__"}
skip_files = {"port.txt"}
count = 0
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
        for fname in sorted(files):
            if fname in skip_files:
                continue
            full = os.path.join(root, fname)
            arc = os.path.join("stratum", os.path.relpath(full, src))
            if fname == "chat_settings.json":
                # The zip is the DISTRIBUTION artifact: strip the API key,
                # keep the shape (backend/model/base) so a fresh install is
                # pre-shaped and only asks for the key. The local dist/ tree
                # (deploy source) keeps the full file untouched.
                try:
                    s = json.load(open(full, encoding="utf-8"))
                    s["api_key"] = ""
                    zf.writestr(arc, json.dumps(s, ensure_ascii=False, indent=2))
                    count += 1
                    continue
                except (OSError, ValueError):
                    pass  # unreadable -> fall through to raw copy (keyless default)
            zf.write(full, arc)
            count += 1
print("zip: %s (%d files)" % (zpath, count))
PYZIP

echo "assembled: $dest (v$ver)"
find "$dest" -type f | sed "s|$dest/||" | sort
