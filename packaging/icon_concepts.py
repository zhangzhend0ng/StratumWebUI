#!/usr/bin/env python3
"""Icon concept exploration for Stratum WebUI (scratch tool, not part of build).

Concepts (all deterministic PIL drawing):

  B  Contour Bloom   — superellipse-to-circle contour rings drifting toward a
                       glowing core (topographic map = strata, seen from above)
  C  Light Slice     — a cube split in two, the cut faces glowing with layer
                       lines (cross-section / structural analysis)
  D  Levitating Layer — front-view tapering slab stack, the top layer floats
                        free (rotated, glow beneath): the layer being tuned

Run:  .venv-build/Scripts/python.exe packaging/icon_concepts.py
Out:  packaging/concept-<x>.png (512px previews with small-size strip)
"""

import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024  # working size


# --- shared helpers ------------------------------------------------------------

def lerp(a, b, t):
    return a + (b - a) * t


def mix(c0, c1, t):
    return tuple(round(lerp(a, b, t)) for a, b in zip(c0[:3], c1[:3]))


def vgrad(size, top, bottom):
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        row = mix(top, bottom, y / (size - 1))
        for x in range(size):
            px[x, y] = row
    return img


def radial_glow(size, center, radius, color, strength=1.0):
    """Soft additive radial light as an RGBA layer."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    cx, cy = center
    steps = 48
    for i in range(steps, 0, -1):
        r = radius * i / steps
        a = round(255 * strength * (1 - i / steps) ** 2.2)
        d.ellipse([cx - r, cy - r * 0.9, cx + r, cy + r * 0.9], fill=a)
    m = m.filter(ImageFilter.GaussianBlur(size // 40))
    layer = Image.new("RGB", (size, size), color[:3])
    layer.putalpha(m)
    return layer


def add_over(base, layer):
    out = base.convert("RGB").copy()
    out.paste(layer.convert("RGB"), (0, 0), layer.split()[-1])
    return out


def add_glow(img, shapes_rgba, blur, gain=1.0):
    """Additively bleed the bright parts of shapes back into img."""
    glow = Image.new("RGB", (S, S), (0, 0, 0))
    glow.paste(shapes_rgba.convert("RGB"), (0, 0), shapes_rgba.split()[-1])
    glow = glow.filter(ImageFilter.GaussianBlur(blur))
    if gain > 1.0:
        glow = glow.point(lambda v: min(255, int(v * gain)))
    return ImageChops.add(img, glow)


def vignette(img, size, strength=110):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([-size * 0.25, -size * 0.25, size * 1.25, size * 1.25],
              fill=255)
    m = m.filter(ImageFilter.GaussianBlur(size // 12))
    dark = Image.new("RGB", (size, size), (0, 0, 0))
    dark.putalpha(m.point(lambda v: 255 - v))
    return add_over(img, dark)


def rounded_tile(rgb, size, corner=0.225):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * corner), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(rgb, (0, 0), mask)
    return out


def sheet(master, name):
    """512px preview + small-size legibility strip, on a neutral dark bg."""
    big = master.resize((512, 512), Image.LANCZOS)
    smalls = [master.resize((n, n), Image.LANCZOS) for n in (64, 48, 32, 16)]
    out = Image.new("RGBA", (760, 512), (24, 26, 32, 255))
    out.paste(big, (0, 0), big)
    x = 540
    for sm in smalls:
        out.paste(sm, (x, 256 - sm.height // 2), sm)
        x += sm.width + 28
    out.save(os.path.join(HERE, name))


def iso_slab(d, cx, cy_top, w, h, top, left, right,
             outline=(240, 250, 255), lw=6, lines=0,
             line_col=(235, 250, 255, 120)):
    """One isometric box (2:1): rhombus top at cy_top, sides of height h."""
    hh = w // 2
    T = (cx, cy_top)
    R = (cx + w, cy_top + hh)
    L = (cx - w, cy_top + hh)
    C = (cx, cy_top + 2 * hh)
    B = (cx, cy_top + 2 * hh + h)
    LL = (cx - w, cy_top + hh + h)
    RR = (cx + w, cy_top + hh + h)
    d.polygon([T, R, C, L], fill=top, outline=outline)
    d.polygon([L, C, B, LL], fill=left, outline=outline)
    d.polygon([C, R, RR, B], fill=right, outline=outline)
    d.line([T, R, C, L, T, L, LL, B, RR, R, B, C], fill=outline,
           width=lw, joint="curve")
    for i in range(1, lines + 1):
        t = i / (lines + 1)
        a = (L[0] + (LL[0] - L[0]) * t, L[1] + (LL[1] - L[1]) * t)
        b = (C[0] + (B[0] - C[0]) * t, C[1] + (B[1] - C[1]) * t)
        d.line([a, b], fill=line_col, width=max(3, lw // 2))
        a = (C[0] + (B[0] - C[0]) * t, C[1] + (B[1] - C[1]) * t)
        b = (R[0] + (RR[0] - R[0]) * t, R[1] + (RR[1] - R[1]) * t)
        d.line([a, b], fill=line_col, width=max(3, lw // 2))


# --- Concept B: Contour Bloom ---------------------------------------------------

def superellipse_points(cx, cy, a, b, n, count=220):
    pts = []
    for k in range(count):
        t = 2 * math.pi * k / count
        ct, st = math.cos(t), math.sin(t)
        x = a * math.copysign(abs(ct) ** (2 / n), ct)
        y = b * math.copysign(abs(st) ** (2 / n), st)
        pts.append((cx + x, cy + y))
    return pts


def concept_b():
    bg = vgrad(S, (7, 26, 34), (2, 5, 9))
    bg = add_over(bg, radial_glow(S, (int(S * 0.54), int(S * 0.46)),
                                  S * 0.36, (24, 130, 140), strength=0.55))
    rings = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(rings, "RGBA")

    outer_c = (34, 128, 142)
    mid_c = (72, 214, 224)
    core_c = (238, 255, 250)
    cx0, cy0 = S * 0.47, S * 0.51
    drift = (S * 0.028, -S * 0.018)

    N = 5
    for i in range(N):
        t = i / (N - 1)
        a = lerp(S * 0.37, S * 0.10, t)
        n_exp = lerp(4.2, 2.0, t)          # squircle -> circle
        col = mix(outer_c, mid_c, t) if t < 1 else core_c
        alpha = round(lerp(210, 255, t))
        lw = round(lerp(13, 18, t))
        cx = cx0 + drift[0] * t
        cy = cy0 + drift[1] * t
        pts = superellipse_points(cx, cy, a, a * 0.84, n_exp)
        d.line(pts + [pts[0]], fill=col + (alpha,), width=lw, joint="curve")

    core = (cx0 + drift[0], cy0 + drift[1])
    d.ellipse([core[0] - S * 0.055, core[1] - S * 0.046,
               core[0] + S * 0.055, core[1] + S * 0.046],
              fill=core_c + (255,))

    img = add_over(bg, rings)
    img = add_glow(img, rings, S // 70)

    return rounded_tile(vignette(img, S, 80), S)


# --- Concept C: Light Slice -------------------------------------------------------

def concept_c():
    w_half = int(S * 0.125)
    gap = int(S * 0.040)
    H = int(S * 0.30)
    cy_top = int(S * 0.31)

    bg = vgrad(S, (10, 14, 34), (3, 5, 12))
    bg = add_over(bg, radial_glow(S, (S // 2, int(S * 0.45)), S * 0.40,
                                  (30, 110, 170), strength=0.5))

    cut = (175, 246, 255, 255)      # glowing cross-section
    slabs = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(slabs, "RGBA")

    iso_slab(d, S // 2 - gap - w_half, cy_top, w_half, H,
             (110, 220, 236, 255), (40, 128, 198, 255), cut,
             outline=(235, 250, 255, 230), lw=max(5, S // 180), lines=4)
    iso_slab(d, S // 2 + gap + w_half, cy_top, w_half, H,
             (96, 200, 220, 255), cut, (20, 88, 150, 255),
             outline=(235, 250, 255, 230), lw=max(5, S // 180), lines=4)

    img = add_over(bg, slabs)

    bleed = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(bleed, "RGBA").polygon(
        [(S * 0.43, S * 0.33), (S * 0.57, S * 0.33),
         (S * 0.61, S * 0.63), (S * 0.39, S * 0.63)],
        fill=(120, 235, 250, 110))
    bleed = bleed.filter(ImageFilter.GaussianBlur(S // 28))
    img = add_over(img, bleed)
    img = add_glow(img, slabs, S // 80)

    return rounded_tile(vignette(img, S, 90), S)


# --- Concept D: Levitating Layer -------------------------------------------------

def grad_slab(w, h, c_top, c_bottom, radius, edge_light=(255, 255, 255, 90)):
    """Rounded-rect slab with a vertical gradient and a crisp top highlight."""
    slab = vgrad_hack = Image.new("RGB", (w, h))
    px = slab.load()
    for y in range(h):
        row = mix(c_top, c_bottom, y / max(1, h - 1))
        for x in range(w):
            px[x, y] = row
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1],
                                           radius=radius, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(slab, (0, 0), mask)

    d = ImageDraw.Draw(out, "RGBA")
    hi_y = max(2, h // 14)
    d.rounded_rectangle(
        [radius, hi_y, w - 1 - radius, hi_y + max(2, h // 22)],
        radius=max(2, h // 30), fill=edge_light)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius,
                        outline=(242, 252, 255, 235), width=max(2, h // 55))
    return out


def concept_d():
    bg = vgrad(S, (13, 19, 42), (5, 8, 20))
    bg = add_over(bg, radial_glow(S, (S // 2, int(S * 0.44)), S * 0.48,
                                  (38, 108, 160), strength=0.5))

    img = bg
    art = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # --- lower stack: three tapering slabs, tiny glowing seams ---------------
    widths = (0.48, 0.46, 0.44)          # bottom -> top
    colors = [((62, 98, 176), (40, 62, 126)),
              ((74, 146, 216), (46, 100, 168)),
              ((100, 202, 232), (56, 142, 194))]
    slab_h = int(S * 0.115)
    seam = int(S * 0.018)
    bottom_y = int(S * 0.775)

    y = bottom_y
    seams_y = []
    for w_frac, (c_top, c_bot) in zip(widths, colors):
        w = int(S * w_frac)
        slab = grad_slab(w, slab_h, c_top, c_bot, radius=int(slab_h * 0.34))
        art.alpha_composite(slab, (S // 2 - w // 2, y - slab_h))
        seams_y.append(y - slab_h - seam // 2)
        y -= slab_h + seam

    # glow seams between the lower slabs
    seam_lyr = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ds = ImageDraw.Draw(seam_lyr, "RGBA")
    for sy, w_frac in zip(seams_y[:2], widths[:2]):
        w = int(S * w_frac * 0.82)
        ds.line([(S // 2 - w // 2, sy), (S // 2 + w // 2, sy)],
                fill=(120, 230, 245, 230), width=max(4, S // 180))
    seam_lyr = seam_lyr.filter(ImageFilter.GaussianBlur(S // 100))
    img = ImageChops.add(img, seam_lyr.convert("RGB"))

    # --- levitating top layer, slightly rotated -------------------------------
    w_top = int(S * 0.40)
    top_c = ((170, 250, 238), (74, 208, 218))
    lev_gap = int(S * 0.095)
    top_slab = grad_slab(w_top, slab_h, top_c[0], top_c[1],
                         radius=int(slab_h * 0.34),
                         edge_light=(255, 255, 255, 130))
    fly = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    fly.alpha_composite(top_slab, (S // 2 - w_top // 2, y - slab_h - lev_gap))
    fly = fly.rotate(6, resample=Image.BICUBIC, center=(S // 2, y - lev_gap))

    # light pooling on the stack below the floating layer
    pool = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(pool, "RGBA").ellipse(
        [S // 2 - int(S * 0.20), y - slab_h - seam - int(S * 0.030),
         S // 2 + int(S * 0.20), y - slab_h - seam + int(S * 0.030)],
        fill=(140, 240, 250, 150))
    pool = pool.filter(ImageFilter.GaussianBlur(S // 60))
    img = add_over(img, pool)

    img = add_over(img, art)
    img = add_over(img, fly)

    # sparks drifting up through the levitation gap
    sparks = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dsp = ImageDraw.Draw(sparks, "RGBA")
    for sx, sy, r in ((S * 0.36, y - int(S * 0.055), 7),
                      (S * 0.63, y - int(S * 0.075), 5),
                      (S * 0.52, y - int(S * 0.038), 4)):
        dsp.ellipse([sx - r, sy - r, sx + r, sy + r],
                    fill=(210, 250, 255, 220))
    sparks = sparks.filter(ImageFilter.GaussianBlur(3))
    img = add_over(img, sparks)

    # glow pool under the whole stack (build-plate light)
    under = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(under, "RGBA").ellipse(
        [S // 2 - int(S * 0.30), int(S * 0.79),
         S // 2 + int(S * 0.30), int(S * 0.79) + int(S * 0.055)],
        fill=(50, 190, 225, 80))
    under = under.filter(ImageFilter.GaussianBlur(S // 30))
    img = add_over(img, under)

    img = add_glow(img, art, S // 90, gain=0.8)
    img = add_glow(img, fly, S // 70, gain=0.8)

    return rounded_tile(vignette(img, S, 95), S)


if __name__ == "__main__":
    for fn, name in ((concept_b, "concept-b.png"),
                     (concept_c, "concept-c.png"),
                     (concept_d, "concept-d.png")):
        sheet(fn(), name)
        print("wrote", name)
