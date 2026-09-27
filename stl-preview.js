"use strict";
// Extracted from index.html (zero-build split, see ROADMAP):
// loaded as a classic <script src> before the main inline script.
// All helpers ($, el, num, numEnv, state, ...) are globals resolved
// at CALL time — this file only declares functions, runs nothing.

// ---------- minimal WebGL STL preview (v1.0a; zero-dependency, no three.js —
// architecture red line 1). Preview is a pure bonus: any failure (no WebGL,
// parse error, huge mesh truncation) degrades to a text note and never
// affects analysis.
var STL_MAX_TRIS = 1500000;  // ~96MB of Float32 buffers; beyond this preview
                             // truncates and says so (64MB binary ≈ 1.34M tris)
function stlParse(buf) {
  var bytes = new Uint8Array(buf);
  function looksAscii() {
    // dual test: ASCII files START with "solid" and decode as UTF-8 text;
    // binary files may also start with "solid" in their 80-byte header, so
    // text-decodability is the real discriminator
    var head = "";
    for (var i = 0; i < 5 && i < bytes.length; i++) head += String.fromCharCode(bytes[i]);
    if (head !== "solid") return false;
    try { new TextDecoder("utf-8", { fatal: true }).decode(bytes); return true; }
    catch (e) { return false; }
  }
  var pos = [], nrm = [], trunc = false, dropped = 0;
  function pushTri(ax, ay, az, bx, by, bz, cx, cy, cz) {
    if (pos.length / 9 >= STL_MAX_TRIS) return false;
    // non-finite vertex (malformed ASCII token "e5"/"--5"→parseFloat NaN, or
    // NaN/Inf float32 bit patterns in binary): skip this tri but KEEP parsing
    // (return true, counted in `dropped`). This guarantees bbox/radius never
    // see non-finite values; without it a NaN reaches pos, every bbox
    // comparison goes false, the axis stays ±Infinity and the preview
    // silently renders a blank canvas instead of degrading (iter 67 REFUTE
    // finding). ASCII facet mis-grouping was fixed by boundary grouping in
    // iter 73 — the stale "known limitation" note is obsolete and removed.
    if (!(isFinite(ax) && isFinite(ay) && isFinite(az) &&
          isFinite(bx) && isFinite(by) && isFinite(bz) &&
          isFinite(cx) && isFinite(cy) && isFinite(cz))) { dropped++; return true; }
    // face normal via cross product; guard degenerate (zero-length) normals
    var ux = bx - ax, uy = by - ay, uz = bz - az;
    var vx = cx - ax, vy = cy - ay, vz = cz - az;
    var nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    var l = Math.hypot(nx, ny, nz);
    if (l > 0) { nx /= l; ny /= l; nz /= l; }
    else { nx = 0; ny = 0; nz = 1; }  // degenerate (collinear) tri: any unit
    // normal is valid — the cross product is (0,0,0) and normalize(0)=NaN
    // in the shader paints an undefined fragment color
    pos.push(ax, ay, az, bx, by, bz, cx, cy, cz);
    nrm.push(nx, ny, nz, nx, ny, nz, nx, ny, nz);
    return true;
  }
  if (looksAscii()) {
    var text = new TextDecoder().decode(bytes);
    // (iter 73) facet-boundary grouping: the old flat-stream 9-stride
    // silently mis-grouped all triangles after a missing/extra vertex line.
    // Each "facet normal" block must contain exactly 3 vertices (STL spec:
    // outer loop + 3×vertex); anything else drops the WHOLE facet.
    // Fallback to flat grouping only when the file has NO facet lines at
    // all (blocks.length === 1) but still has ≥9 vertex numbers — NOT when
    // facets exist but are all malformed, which would resurrect the bug in
    // the fallback path (iter 73 REFUTE blocker).
    var blocks = text.split(/facet\s+normal/);
    if (blocks.length > 1) {
      for (var bi = 1; bi < blocks.length && !trunc; bi++) {
        var vs = [], m2;
        var re = /^\s*vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/gm;
        while ((m2 = re.exec(blocks[bi])))
          vs.push(parseFloat(m2[1]), parseFloat(m2[2]), parseFloat(m2[3]));
        if (vs.length === 9) {
          if (!pushTri(vs[0], vs[1], vs[2], vs[3], vs[4], vs[5],
                       vs[6], vs[7], vs[8])) trunc = true;
        }
        // vs.length !== 9 → malformed facet: drop it, keep neighbors aligned
        else dropped++;
      }
    } else {
      var vsf = [];
      text.split(/\r?\n/).forEach(function (line) {
        var m = /^\s*vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/.exec(line);
        if (m) vsf.push(parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]));
      });
      if (vsf.length >= 9) {  // nonstandard facet-less ASCII: legacy grouping
        for (var i = 0; i + 8 < vsf.length; i += 9) {
          if (!pushTri(vsf[i], vsf[i+1], vsf[i+2], vsf[i+3], vsf[i+4], vsf[i+5],
                       vsf[i+6], vsf[i+7], vsf[i+8])) { trunc = true; break; }
        }
        // (iter 76 CLEAN) tail leftover (<9 numbers, never a full tri):
        // count into dropped instead of silently vanishing (only when the
        // loop ran to completion — a trunc break leaves full tris unread)
        if (!trunc && i < vsf.length) dropped += Math.floor((vsf.length - i) / 3);
      }
    }
  } else {
    var dv = new DataView(buf);
    if (bytes.length < 84) return { tris: 0, truncated: false };
    var count = dv.getUint32(80, true);
    if (84 + count * 50 > bytes.length) return { tris: 0, truncated: false };
    for (var t = 0; t < count; t++) {
      var o = 84 + t * 50 + 12;  // skip the stored normal — we recompute
      var v = [];
      for (var k = 0; k < 3; k++) {
        v.push(dv.getFloat32(o + k * 12, true),
               dv.getFloat32(o + k * 12 + 4, true),
               dv.getFloat32(o + k * 12 + 8, true));
      }
      if (!pushTri(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8])) { trunc = true; break; }
    }
  }
  var n = pos.length / 9;
  // bbox
  var bb = null;
  if (n) {
    bb = { min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] };
    for (var p = 0; p < pos.length; p += 3) {
      for (var d2 = 0; d2 < 3; d2++) {
        if (pos[p + d2] < bb.min[d2]) bb.min[d2] = pos[p + d2];
        if (pos[p + d2] > bb.max[d2]) bb.max[d2] = pos[p + d2];
      }
    }
  }
  // truncated = explicit flag set only when STL_MAX_TRIS actually stopped a
  // push (not derived from n — a file with exactly STL_MAX_TRIS good tris
  // after skipping bad ones would otherwise misreport, iter 67 REFUTE minor)
  return { tris: n, truncated: trunc, dropped: dropped, pos: pos, nrm: nrm, bbox: bb };
}

var stlView = { gl: null, prog: null, n: 0, rotX: 0.7, rotY: 0.4, dist: 2,
                center: [0, 0, 0], radius: 1,
                // orientation overlay (v1.0a): engine's --optimize-orient
                // candidate build directions, drawn as arrows from the model
                // center. orient[i] = {rank, dir:[x,y,z]} with dir normalized
                // here. Null/empty = no overlay (3MF has no preview;
                // non-assessable reports never set it).
                orient: null, orientSel: 0,
                // spatial risk heatmap (v0.8; engine --heatmap-json): sparse
                // bins³ grid rendered as flat-colored cubes. While active it
                // REPLACES the mesh draw — the bins fill the part interior,
                // so an overlaid cloud would be hidden by the surface.
                heat: null, heatMode: "vm",
                heatPosBuf: null, heatColBuf: null, heatCount: 0 };

// jet-ish colormap t∈[0,1] → [r,g,b] (classic 3-segment interpolation)
function stlHeatColor(t) {
  t = Math.min(1, Math.max(0, t));
  return [Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - 3))),
          Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - 2))),
          Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - 1)))];
}

// parse + upload the engine heatmap JSON into cube buffers. Defensive shape
// checks throughout: a malformed channel degrades to "no heatmap", never
// breaks the preview. `data` null → clear.
function stlSetHeatmap(data) {
  stlView.heat = null;
  stlView.heatCount = 0;
  if (data && typeof data === "object" && Array.isArray(data.bins)
      && typeof data.bins_dim === "number" && data.bins_dim >= 2
      && Array.isArray(data.extent_mm) && data.extent_mm.length === 3) {
    var B = data.bins_dim;
    var hs = [data.extent_mm[0] / B / 2 * 0.92,
              data.extent_mm[1] / B / 2 * 0.92,
              data.extent_mm[2] / B / 2 * 0.92];
    var pos = [], vm = [], risk = [], vmaxVm = 0, vmaxRisk = 0;
    data.bins.forEach(function (bin) {
      if (!bin || !Array.isArray(bin.center_mm) || bin.center_mm.length < 3) return;
      var v = (typeof bin.von_mises_max_mpa === "number" && bin.von_mises_max_mpa > 0)
        ? bin.von_mises_max_mpa : 0;   // engine -1 sentinel = no solid cells
      var r = (typeof bin.risk_score_max === "number" && bin.risk_score_max > 0)
        ? bin.risk_score_max : 0;
      var c = bin.center_mm;
      var x0 = c[0] - hs[0], x1 = c[0] + hs[0];
      var y0 = c[1] - hs[1], y1 = c[1] + hs[1];
      var z0 = c[2] - hs[2], z1 = c[2] + hs[2];
      // 6 faces × 2 triangles = 36 vertices per axis-aligned cube
      var faces = [
        [x0,y0,z0, x1,y0,z0, x1,y1,z0, x0,y0,z0, x1,y1,z0, x0,y1,z0],
        [x0,y0,z1, x1,y0,z1, x1,y1,z1, x0,y0,z1, x1,y1,z1, x0,y1,z1],
        [x0,y0,z0, x1,y0,z0, x1,y0,z1, x0,y0,z0, x1,y0,z1, x0,y0,z1],
        [x0,y1,z0, x1,y1,z0, x1,y1,z1, x0,y1,z0, x1,y1,z1, x0,y1,z1],
        [x0,y0,z0, x0,y1,z0, x0,y1,z1, x0,y0,z0, x0,y1,z1, x0,y0,z1],
        [x1,y0,z0, x1,y1,z0, x1,y1,z1, x1,y0,z0, x1,y1,z1, x1,y0,z1]
      ];
      for (var f = 0; f < faces.length; f++) {
        var q = faces[f];
        for (var k = 0; k < 18; k += 3) {
          pos.push(q[k], q[k + 1], q[k + 2]);
          vm.push(v); risk.push(r);
        }
      }
      if (v > vmaxVm) vmaxVm = v;
      if (r > vmaxRisk) vmaxRisk = r;
    });
    if (pos.length) {
      stlView.heat = { pos: new Float32Array(pos), vm: vm, risk: risk,
                       vmaxVm: vmaxVm, vmaxRisk: vmaxRisk,
                       count: pos.length / 3 };
    }
  }
  stlBuildHeatColors();
  stlDraw();
}

// per-vertex colors for the active heat mode, uploaded to the GPU
function stlBuildHeatColors() {
  var h = stlView.heat, gl = stlView.gl;
  if (!h || !gl) return;
  var useRisk = stlView.heatMode === "risk";
  var vals = useRisk ? h.risk : h.vm;
  var vmax = useRisk ? h.vmaxRisk : h.vmaxVm;
  var cols = new Float32Array(h.count * 3);
  for (var i = 0; i < h.count; i++) {
    var c = stlHeatColor(vmax > 0 ? vals[i] / vmax : 0);
    cols[i * 3] = c[0]; cols[i * 3 + 1] = c[1]; cols[i * 3 + 2] = c[2];
  }
  gl.useProgram(stlView.prog);
  if (!stlView.heatPosBuf) stlView.heatPosBuf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, stlView.heatPosBuf);
  gl.bufferData(gl.ARRAY_BUFFER, h.pos, gl.STATIC_DRAW);
  if (!stlView.heatColBuf) stlView.heatColBuf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, stlView.heatColBuf);
  gl.bufferData(gl.ARRAY_BUFFER, cols, gl.STATIC_DRAW);
  stlView.heatCount = h.count;
}

// legend range for the active mode (0 → max; max is the normalization anchor)
function stlHeatRange() {
  var h = stlView.heat;
  if (!h) return null;
  return stlView.heatMode === "risk"
    ? { max: h.vmaxRisk, label: "Phase A 风险分" }
    : { max: h.vmaxVm, label: "von Mises (MPa)" };
}

function stlSetHeatMode(mode) {
  stlView.heatMode = mode === "risk" ? "risk" : "vm";
  stlBuildHeatColors();
  stlDraw();
}

// set/replace the overlay; dirs normalized defensively (engine emits ~unit
// vectors on 0.21.0 but the JSON contract does not promise it)
function stlSetOrient(cands) {
  stlView.orient = null;
  stlView.orientSel = 0;
  if (Array.isArray(cands)) {
    var out = [];
    cands.forEach(function (c) {
      var d = c && c.direction;
      if (!Array.isArray(d) || d.length < 3) return;
      var m = Math.hypot(d[0], d[1], d[2]);
      if (!(m > 0) || !isFinite(m)) return;  // zero/garbage dir: skip arrow
      out.push({ rank: c.rank || (out.length + 1),
                 dir: [d[0] / m, d[1] / m, d[2] / m] });
    });
    if (out.length) stlView.orient = out;
  }
  stlDraw();
}

// rotate the view so candidate direction d (model space, unit) points
// screen-up. Solved from Rx(rotX)·Ry(rotY)·S·d = (0,1,0) where S is the
// z-up→y-up swap (x,-z,y); with u=(d0,-d2,d1), g=hypot(u0,u2):
//   rotY = atan2(-u0, u2), rotX = atan2(-g, u1)
// (Rx rows are [[1,0,0],[0,cx,-sx],[0,sy,cx]] — first derivation flipped
// the Rx row signs and produced (0,.54,.84) instead of (0,1,0); caught by
// the iter-64 numeric cross-check, DOGFOOD of the same iter-42 risk zone).
// g=0 (d along model ±Y) → rotX=±π/2, atan2 handles it.
function stlOrientToDir(d) {
  if (!Array.isArray(d) || d.length < 3) return;
  var m = Math.hypot(d[0], d[1], d[2]);
  if (!(m > 0) || !isFinite(m)) return;
  var u0 = d[0] / m, u1 = -d[2] / m, u2 = d[1] / m;
  var g = Math.hypot(u0, u2);
  stlView.rotY = Math.atan2(-u0, u2);
  stlView.rotX = Math.atan2(-g, u1);
  stlDraw();
}

// highlight one rank (0 = none); called by the 「分析结果」 orientation table rows
function stlSelectOrient(rank) {
  stlView.orientSel = rank;
  stlDraw();
}

// candidate arrow colors: selected red, rank 1 gold, others muted blue-gray
function stlOrientColor(rank) {
  if (rank === stlView.orientSel) return [1.0, 0.25, 0.25];
  if (rank === 1) return [1.0, 0.8, 0.2];
  return [0.55, 0.62, 0.72];
}

// line-segment POSITIONS for one candidate's arrow (shaft + 3-segment tip),
// model space — built per draw (tiny), one draw call per candidate so each
// can have its flat color via uColor
function stlOrientArrowVerts(c) {
  var v = stlView, out = [];
  var L = v.radius * 0.85;   // arrow reach: just past the mesh surface
  var tip = v.radius * 0.14;
  var d = c.dir;
  function seg(ax, ay, az, bx, by, bz) { out.push(ax, ay, az, bx, by, bz); }
  var hx = v.center[0] + d[0] * L, hy = v.center[1] + d[1] * L,
      hz = v.center[2] + d[2] * L;
  seg(v.center[0], v.center[1], v.center[2], hx, hy, hz);
  // two vectors perpendicular to d (basis for the tip spokes)
  var px = Math.abs(d[0]) < 0.9 ? 1 : 0, py = Math.abs(d[0]) < 0.9 ? 0 : 1;
  var u = [d[1] * 0 - d[2] * py, d[2] * px - d[0] * 0, d[0] * py - d[1] * px];
  var um = Math.hypot(u[0], u[1], u[2]) || 1;
  u = [u[0] / um, u[1] / um, u[2] / um];
  var w = [d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2],
           d[0] * u[1] - d[1] * u[0]];
  for (var k = 0; k < 3; k++) {
    var a = 2 * Math.PI * k / 3;
    var cA = Math.cos(a), sA = Math.sin(a);
    var sx = u[0] * cA + w[0] * sA, sy = u[1] * cA + w[1] * sA,
        sz = u[2] * cA + w[2] * sA;
    seg(hx, hy, hz,
        hx - d[0] * tip + sx * tip, hy - d[1] * tip + sy * tip,
        hz - d[2] * tip + sz * tip);
  }
  return out;
}

// column-major (WebGL layout): element(row r, col c) lives at index c*4+r.
// The first version indexed [r*4+c] — row-major math on column-major data,
// which scrambled every product (caught by DOGFOOD iter 42).
function stlMat4Mul(a, b) {
  var o = new Float32Array(16);
  for (var c = 0; c < 4; c++) for (var r = 0; r < 4; r++) {
    o[c * 4 + r] = a[0 * 4 + r] * b[c * 4 + 0] + a[1 * 4 + r] * b[c * 4 + 1]
                 + a[2 * 4 + r] * b[c * 4 + 2] + a[3 * 4 + r] * b[c * 4 + 3];
  }
  return o;
}
function stlPersp(fov, asp, near, far) {
  var f = 1 / Math.tan(fov / 2);
  return new Float32Array([f / asp, 0, 0, 0, 0, f, 0, 0, 0, 0,
    (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0]);
}
function stlDraw() {
  var v = stlView;
  if (!v.gl || !v.n) return;
  var cy = Math.cos(v.rotY), sy = Math.sin(v.rotY);
  var cx = Math.cos(v.rotX), sx = Math.sin(v.rotX);
  var ry = new Float32Array([cy, 0, -sy, 0, 0, 1, 0, 0, sy, 0, cy, 0, 0, 0, 0, 1]);
  var rx = new Float32Array([1, 0, 0, 0, 0, cx, sy, 0, 0, -sx, cx, 0, 0, 0, 0, 1]);
  // z-up → y-up swap (X=x, Y=-z, Z=y): the translation must cancel the
  // SWAPPED center, i.e. (-c0, +c2, -c1) — a plain -center here leaves a
  // residual offset (caught by DOGFOOD iter 42 readPixels diagnostics)
  var tr = new Float32Array([1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0,
    -v.center[0], v.center[2], -v.center[1], 1]);
  var eye = [0, 0, v.dist];
  var view = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0,
    -eye[0], -eye[1], -eye[2], 1]);
  // model = rotate AFTER centering (rx*ry*tr): translating by the
  // UNrotated center first and rotating after would swing the model off
  // the view axis (caught by DOGFOOD iter 42 — nothing rasterized)
  // far plane must clear the camera distance (dist = radius*3 can exceed
  // any fixed far — a 100 far clipped the whole mesh at 150, DOGFOOD iter 42)
  var far = v.dist + v.radius * 4;
  var mvp = stlMat4Mul(stlPersp(0.9, v.gl.drawingBufferWidth / v.gl.drawingBufferHeight,
                                0.01, far), stlMat4Mul(view, stlMat4Mul(rx, stlMat4Mul(ry, tr))));
  v.gl.clear(v.gl.COLOR_BUFFER_BIT | v.gl.DEPTH_BUFFER_BIT);
  v.gl.uniformMatrix4fv(v.gl.getUniformLocation(v.prog, "uMvp"), false, mvp);
  var locNrm = v.gl.getAttribLocation(v.prog, "aNrm");
  var locPos = v.gl.getAttribLocation(v.prog, "aPos");
  var locCol = v.gl.getAttribLocation(v.prog, "aColor");
  if (v.heat && v.heatCount && v.heatPosBuf && v.heatColBuf) {
    // heatmap view: one flat-colored TRIANGLES draw for all cubes (the
    // per-bin color comes from aColor via uHeat; no lighting mix)
    v.gl.disableVertexAttribArray(locNrm);
    v.gl.vertexAttrib3f(locNrm, 0, 0, 1);
    v.gl.bindBuffer(v.gl.ARRAY_BUFFER, v.heatPosBuf);
    v.gl.enableVertexAttribArray(locPos);
    v.gl.vertexAttribPointer(locPos, 3, v.gl.FLOAT, false, 0, 0);
    v.gl.bindBuffer(v.gl.ARRAY_BUFFER, v.heatColBuf);
    v.gl.enableVertexAttribArray(locCol);
    v.gl.vertexAttribPointer(locCol, 3, v.gl.FLOAT, false, 0, 0);
    v.gl.uniform1f(v.gl.getUniformLocation(v.prog, "uHeat"), 1);
    v.gl.drawArrays(v.gl.TRIANGLES, 0, v.heatCount);
    v.gl.uniform1f(v.gl.getUniformLocation(v.prog, "uHeat"), 0);
    v.gl.disableVertexAttribArray(locCol);
  } else {
    v.gl.uniform1f(v.gl.getUniformLocation(v.prog, "uFlat"), 0);
    v.gl.drawArrays(v.gl.TRIANGLES, 0, v.n);
  }
  // orientation overlay: one flat-colored LINES draw per candidate (≤5 on
  // 0.21.0). aNrm is switched to a constant so the (short) line buffer can
  // not read past its end through the still-enabled triangle normal array.
  if (v.orient && v.orient.length) {
    v.gl.disableVertexAttribArray(locNrm);
    v.gl.vertexAttrib3f(locNrm, 0, 0, 1);
    v.gl.uniform1f(v.gl.getUniformLocation(v.prog, "uFlat"), 1);
    var cLoc = v.gl.getUniformLocation(v.prog, "uColor");
    v.orient.forEach(function (c) {
      var col = stlOrientColor(c.rank);
      var buf = v.gl.createBuffer();
      v.gl.bindBuffer(v.gl.ARRAY_BUFFER, buf);
      v.gl.bufferData(v.gl.ARRAY_BUFFER,
                      new Float32Array(stlOrientArrowVerts(c)), v.gl.DYNAMIC_DRAW);
      v.gl.enableVertexAttribArray(locPos);
      v.gl.vertexAttribPointer(locPos, 3, v.gl.FLOAT, false, 0, 0);
      v.gl.uniform3f(cLoc, col[0], col[1], col[2]);
      v.gl.drawArrays(v.gl.LINES, 0, 8);  // shaft + 3 tips = 8 vertices
      v.gl.deleteBuffer(buf);
    });
    v.gl.uniform1f(v.gl.getUniformLocation(v.prog, "uFlat"), 0);
    v.gl.enableVertexAttribArray(locNrm);
    // re-point BOTH attribs at the mesh buffers: the line draws re-bound
    // aPos per candidate and aNrm was constant — the next TRIANGLES draw
    // (e.g. a drag redraw without a reload) would otherwise read garbage.
    v.gl.bindBuffer(v.gl.ARRAY_BUFFER, v.posBuf || null);
    v.gl.vertexAttribPointer(locPos, 3, v.gl.FLOAT, false, 0, 0);
    v.gl.bindBuffer(v.gl.ARRAY_BUFFER, v.nrmBuf || null);
    v.gl.vertexAttribPointer(locNrm, 3, v.gl.FLOAT, false, 0, 0);
  }
}

function loadStlPreview(j) {
  var canvas = $("stl-view"), note = $("stl-view-note");
  function degrade(msg) {
    canvas.style.display = "none";
    note.style.display = "";
    note.textContent = msg;
  }
  var ext = (j.name.split(".").pop() || "").toLowerCase();
  if (ext !== "stl") {
    // also clears a previous session's last frame (canvas hidden = no stale)
    degrade(ext === "3mf" ? "3MF 预览暂不支持（结构优化请看 「分析结果」与「档位对比」面板）"
                          : "预览仅支持 STL");
    return;
  }
  fetch("/api/model?token=" + encodeURIComponent(j.token))
    .then(function (r) {
      if (!r.ok) throw new Error("model fetch " + r.status);
      return r.arrayBuffer();
    })
    .then(function (buf) {
      var m = stlParse(buf);
      // (iter 74) distinguish an empty file from one whose tris were all
      // dropped as malformed — "no triangles" on a corrupt file misled users
      if (!m.tris) throw new Error(m.dropped > 0
        ? "no valid triangles (" + m.dropped + " malformed dropped)"
        : "no triangles");
      var gl = stlView.gl;
      if (!gl) {
        gl = canvas.getContext("webgl", { antialias: true });
        if (!gl) throw new Error("WebGL 不可用");
        stlView.gl = gl;
        var vsSrc = "attribute vec3 aPos; attribute vec3 aNrm; attribute vec3 aColor;" +
          "uniform mat4 uMvp; varying float vL; varying vec3 vColor;" +
          "void main(){ gl_Position = uMvp * vec4(aPos, 1.0);" +
          " vec3 n = normalize(mat3(uMvp[0].xyz, uMvp[1].xyz, uMvp[2].xyz) * aNrm);" +
          " vL = 0.35 + 0.65 * max(dot(n, normalize(vec3(0.4, 0.6, 0.8))), 0.0);" +
          " vColor = aColor; }";
        var fsSrc = "precision mediump float; varying float vL; varying vec3 vColor;" +
          "uniform float uFlat; uniform vec3 uColor; uniform float uHeat;" +
          "void main(){ vec3 c = vec3(0.22, 0.74, 0.97) * vL;" +
          " c = mix(c, uColor, uFlat); c = mix(c, vColor, uHeat);" +
          " gl_FragColor = vec4(c, 1.0); }";
        function sh(type, src) {
          var s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
          if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
            throw new Error(gl.getShaderInfoLog(s));
          }
          return s;
        }
        var prog = gl.createProgram();
        gl.attachShader(prog, sh(gl.VERTEX_SHADER, vsSrc));
        gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fsSrc));
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
          throw new Error(gl.getProgramInfoLog(prog));
        }
        stlView.prog = prog;
        gl.enable(gl.DEPTH_TEST);
        gl.clearColor(0.086, 0.11, 0.16, 1);
        // Deliberately NOT --surface-2: v0.11 switched the UI to a light
        // theme but kept this as the fixed dark model-viewport (like CAD/
        // slicer apps); rgb(22,28,41) is pinned by the browser e2e lit-check
        // (browser_render_check.js, 3-channel Manhattan sum <= 40 of this
        // value) — do not move it without updating that constant.
        // interactions: drag rotate + wheel zoom (explicit non-passive so
        // preventDefault is legal on the element)
        var drag = null;
        canvas.addEventListener("mousedown", function (e) {
          drag = [e.clientX, e.clientY]; e.preventDefault();
        });
        window.addEventListener("mousemove", function (e) {
          if (!drag) return;
          stlView.rotY += (e.clientX - drag[0]) * 0.01;
          stlView.rotX += (e.clientY - drag[1]) * 0.01;
          drag = [e.clientX, e.clientY];
          stlDraw();
        });
        window.addEventListener("mouseup", function () { drag = null; });
        canvas.addEventListener("wheel", function (e) {
          e.preventDefault();
          stlView.dist = Math.min(50, Math.max(1.2, stlView.dist * (1 + e.deltaY * 0.001)));
          stlDraw();
        }, { passive: false });
      }
      var prog = stlView.prog;
      gl.useProgram(prog);
      function attr(name, data) {
        var buf = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
        var loc = gl.getAttribLocation(prog, name);
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
        return buf;  // kept on stlView so stlDraw's overlay can restore it
      }
      try {
        stlView.posBuf = attr("aPos", m.pos);
        stlView.nrmBuf = attr("aNrm", m.nrm);
      } catch (e) {  // OUT_OF_MEMORY / CONTEXT_LOST on huge meshes
        stlView.n = 0;
        throw new Error("mesh too large for preview");
      }
      stlView.n = m.tris * 3;
      var bb = m.bbox;
      stlView.center = [(bb.min[0] + bb.max[0]) / 2, (bb.min[1] + bb.max[1]) / 2,
                        (bb.min[2] + bb.max[2]) / 2];
      stlView.radius = Math.max(bb.max[0] - bb.min[0], bb.max[1] - bb.min[1],
                                bb.max[2] - bb.min[2]) / 2 || 1;
      stlView.dist = stlView.radius * 3;
      // HiDPI: backing store × dpr, CSS size unchanged
      var dpr = window.devicePixelRatio || 1;
      var w = canvas.clientWidth || 420, h = Math.round(w * 280 / 420);
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      gl.viewport(0, 0, canvas.width, canvas.height);
      note.style.display = "none";
      canvas.style.display = "";
      stlDraw();
      if (m.truncated) {
        note.style.display = "";
        note.textContent = "预览已抽稀（超过 " + STL_MAX_TRIS + " 三角）";
      }
    })
    .catch(function (e) { degrade("预览不可用: " + String(e.message || e)); });
}
