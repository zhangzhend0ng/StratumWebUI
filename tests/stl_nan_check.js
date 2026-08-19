// T56 companion (iter 67): non-finite vertex guard in stlParse.
// Loads the browser classic script in a vm sandbox (file declares functions
// only — see header of stl-preview.js) and drives stlParse with degenerate
// inputs. Exits non-zero on any failure (verify-script-exit-code pattern).
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

const SRC = path.join(__dirname, "..", "stl-preview.js");
const ctx = { TextDecoder: TextDecoder, isFinite: isFinite, Math: Math,
              Array: Array, console: console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(SRC, "utf8"), ctx);
const stlParse = ctx.stlParse;
if (typeof stlParse !== "function") {
  console.error("FATAL: stlParse not exported by stl-preview.js");
  process.exit(1);
}

let fails = 0;
function expect(name, cond, detail) {
  console.log((cond ? "PASS" : "FAIL") + "  " + name + (cond ? "" : "  " + detail));
  if (!cond) fails++;
}
function allFinite(m) {
  return m.pos.every(function (v) { return isFinite(v); })
      && m.nrm.every(function (v) { return isFinite(v); })
      && (!m.bbox || (m.bbox.min.every(isFinite) && m.bbox.max.every(isFinite)));
}

// 1. ASCII with a malformed numeric token: "e5" parseFloat→NaN (the regex
//    [-+0-9.eE]+ accepts it; note "1e" is NOT NaN — parseFloat takes the
//    longest valid prefix and returns 1, caught while writing this test).
//    The NaN tri must be skipped, neighbors kept.
const ascii = "solid x\n" +
  "facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n" +
  "facet normal 0 0 1\nouter loop\nvertex e5 2 3\nvertex 4 5 6\nvertex 7 8 9\nendloop\nendfacet\n" +
  "facet normal 0 0 1\nouter loop\nvertex 10 0 0\nvertex 11 0 0\nvertex 10 1 0\nendloop\nendfacet\n" +
  "endsolid x\n";
const b1 = Buffer.from(ascii, "utf8");
let m1 = stlParse(b1.buffer.slice(b1.byteOffset, b1.byteOffset + b1.length));
expect("ascii NaN-token tri skipped, neighbors kept",
       m1.tris === 2 && allFinite(m1), "tris=" + m1.tris);

// 2. binary with a NaN float32 vertex bit pattern (0x7FC00000)
const tri = function (vs) {
  const b = Buffer.alloc(50);
  for (let k = 0; k < 9; k++) b.writeFloatLE(vs[k], 12 + k * 4);
  return b;
};
const hdr = Buffer.alloc(84); hdr.write("bin", 0); hdr.writeUInt32LE(3, 80);
const binBuf = Buffer.concat([hdr,
  tri([0, 0, 0, 1, 0, 0, 0, 1, 0]),
  tri([NaN, 2, 3, 4, 5, 6, 7, 8, 9]),
  tri([10, 0, 0, 11, 0, 0, 10, 1, 0])]);
let m2 = stlParse(binBuf.buffer.slice(binBuf.byteOffset, binBuf.byteOffset + binBuf.length));
expect("binary NaN-vertex tri skipped, neighbors kept",
       m2.tris === 2 && allFinite(m2), "tris=" + m2.tris);

// 3. Infinity shape (0x7F800000): also skipped — the "all finite bbox" claim
const inf = Buffer.alloc(4); inf.writeUInt32LE(0x7F800000, 0);
const infTri = Buffer.concat([Buffer.alloc(12), Buffer.concat([inf, inf, inf, inf, inf, inf, inf, inf, inf]), Buffer.alloc(2)]);  // 12 normal + 9*4 verts + 2 attr = 50
const binInf = Buffer.concat([hdr,
  tri([0, 0, 0, 1, 0, 0, 0, 1, 0]),
  infTri,
  tri([10, 0, 0, 11, 0, 0, 10, 1, 0])]);
let m3 = stlParse(binInf.buffer.slice(binInf.byteOffset, binInf.byteOffset + binInf.length));
expect("binary Inf-vertex tri skipped", m3.tris === 2 && allFinite(m3), "tris=" + m3.tris);

// 4. regression: the real fixture still parses, finite, not truncated
const real = fs.readFileSync(path.join(__dirname, "..", "test_data", "beam_100x10x4.stl"));
let m4 = stlParse(real.buffer.slice(real.byteOffset, real.byteOffset + real.byteLength));
expect("real fixture parses finite, truncated=false",
       m4.tris > 0 && allFinite(m4) && m4.truncated === false,
       "tris=" + m4.tris);

// 5. all-bad file: tris=0 (consumers throw "no triangles" → degrade note)
const hdr1 = Buffer.alloc(84); hdr1.write("bin", 0); hdr1.writeUInt32LE(1, 80);
const binBad = Buffer.concat([hdr1, tri([NaN, NaN, NaN, NaN, NaN, NaN, NaN, NaN, NaN])]);
let m5 = stlParse(binBad.buffer.slice(binBad.byteOffset, binBad.byteOffset + binBad.length));
expect("all-bad binary → tris=0, bbox null",
       m5.tris === 0 && m5.bbox == null && m5.truncated === false);

// 6. (iter 73) facet-boundary grouping: a facet MISSING one vertex is
// dropped whole — neighbors keep exact geometry (old flat stream would
// mis-group everything after it).
const facet = (vs) => "facet normal 0 0 1\nouter loop\n" +
  vs.map(v => "vertex " + v.join(" ")).join("\n") + "\nendloop\nendfacet\n";
const ascii6 = "solid x\n" +
  facet([[0,0,0],[1,0,0],[0,1,0]]) +
  facet([[10,0,0],[11,0,0]]) +              // missing 3rd vertex
  facet([[20,0,0],[21,0,0],[20,1,0]]) + "\nendsolid x\n";
const b6 = Buffer.from(ascii6, "utf8");
let m6 = stlParse(b6.buffer.slice(b6.byteOffset, b6.byteOffset + b6.length));
expect("iter73: malformed facet dropped, neighbors exact",
       m6.tris === 2 && m6.bbox.max[0] === 21 && m6.bbox.min[0] === 0,
       "tris=" + m6.tris + " bbox=" + JSON.stringify(m6.bbox));

// 7. all facets malformed (facet lines present) → NO flat fallback (REFUTE
// blocker regression): would resurrect mis-grouping
const ascii7 = "solid x\n" +
  facet([[0,0,0],[1,0,0]]) + facet([[2,0,0],[3,0,0]]) +
  facet([[4,0,0],[5,0,0]]) + facet([[6,0,0],[7,0,0]]) + "\nendsolid x\n";
const b7 = Buffer.from(ascii7, "utf8");
let m7 = stlParse(b7.buffer.slice(b7.byteOffset, b7.byteOffset + b7.length));
expect("iter73: all-malformed facets → tris=0, no fallback",
       m7.tris === 0 && m7.bbox == null, "tris=" + m7.tris);

// 8. nonstandard facet-less ASCII (≥9 vertex numbers) → legacy flat grouping
const ascii8 = "solid x\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nvertex 5 5 5\nvertex 6 5 5\nvertex 5 6 5\nendsolid x\n";
const b8 = Buffer.from(ascii8, "utf8");
let m8 = stlParse(b8.buffer.slice(b8.byteOffset, b8.byteOffset + b8.length));
expect("iter73: facet-less ASCII legacy grouping",
       m8.tris === 2, "tris=" + m8.tris);

// 9. truncation path (STL_MAX_TRIS overridden low in the vm context):
// 6 good facets, cap 5 → tris=5, truncated=true
ctx.STL_MAX_TRIS = 5;
let ascii9 = "solid x\n";
for (let q = 0; q < 6; q++) ascii9 += facet([[q,0,0],[q+0.5,0,0],[q,1,0]]);
ascii9 += "endsolid x\n";
const b9 = Buffer.from(ascii9, "utf8");
let m9 = stlParse(b9.buffer.slice(b9.byteOffset, b9.byteOffset + b9.length));
ctx.STL_MAX_TRIS = 1500000;
expect("iter73: STL_MAX_TRIS truncation → tris=5, truncated=true",
       m9.tris === 5 && m9.truncated === true,
       "tris=" + m9.tris + " trunc=" + m9.truncated);

// 10. (iter 74) dropped counter + consumer-side message distinction
expect("iter74: all-bad file reports dropped=1",
       m5.dropped === 1, "dropped=" + m5.dropped);
expect("iter74: case 6 malformed facet counted in dropped",
       m6.dropped === 1, "dropped=" + m6.dropped);
expect("iter74: clean real fixture dropped=0",
       m4.dropped === 0, "dropped=" + m4.dropped);

process.exit(fails ? 1 : 0);
