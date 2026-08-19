#!/usr/bin/env python3
"""Regenerate packaging/stratum-webui.ico programmatically.

Design "Levitating Layer": a front-view tapering stack of three gradient
slabs (FDM layers, indigo -> electric blue -> cyan-blue) joined by thin
glowing seams; the top layer — mint-cyan, slightly rotated — floats free
above the stack, its light pooling on the stack beneath while sparks drift
up through the gap. Metaphor: the layer currently being tuned, lifted out
of the print for inspection.

Fully deterministic: geometry and palette live in this file, so the .ico can
always be reproduced exactly. (Alternate directions: icon_concepts.py.)

Run (Pillow is a make-time-only dep; install it into .venv-build):
    .venv-build/Scripts/python.exe packaging/make_icon.py

Outputs:
    packaging/stratum-webui.ico   multi-size (16-256), consumed by the
                                  PyInstaller spec and installer.iss
    packaging/icon-preview.png    512px preview for eyeballing / README
"""

import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))

# --- palette -------------------------------------------------------------------
BG_TOP = (13, 19, 42)         # deep space navy, top of gradient
BG_BOTTOM = (5, 8, 20)        # near-black, bottom
GLOW_BG = (38, 108, 160)      # radial ambience behind the stack
SEAM = (120, 230, 245)        # glowing cyan layer seams
SLAB_COLORS = [               # bottom -> top: (top edge, bottom edge)
    ((62, 98, 176), (40, 62, 126)),     # indigo
    ((74, 146, 216), (46, 100, 168)),   # electric blue
    ((100, 202, 232), (56, 142, 194)),  # cyan-blue
]
TOP_COLORS = ((170, 250, 238), (74, 208, 218))  # mint-cyan floating layer
SPARK = (210, 250, 255)       # particles rising through the levitation gap
POOL = (140, 240, 250)        # light pooling on the stack below the layer
UNDER = (50, 190, 225)        # build-plate glow under the whole stack

S = 2048  # master size (downscaled for antialiasing)

# --- geometry (fractions of S) --------------------------------------------------
SLAB_W = (0.48, 0.46, 0.44)   # stack widths, bottom -> top (taper)
SLAB_H = 0.115                # slab height
SEAM_GAP = 0.018              # gap between stack slabs
BOTTOM_Y = 0.775              # bottom edge of the lowest slab
TOP_W = 0.40                  # floating layer width
LEV_GAP = 0.095               # levitation gap
TOP_ROT = 6                   # degrees, counterclockwise


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c0, c1, t):
    return tuple(round(lerp(a, b, t)) for a, b in zip(c0[:3], c1[:3]))


def vgrad(size, top, bottom):
    """Vertical gradient, built as a 1px column then stretched (fast)."""
    col = Image.new("RGB", (1, size))
    col.putdata([mix(top, bottom, y / (size - 1)) for y in range(size)])
    return col.resize((size, size))


def radial_glow(size, center, radius, color, strength=1.0):
    """Soft additive radial light as an RGB layer."""
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


def vignette(img, size, strength=95):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).ellipse(
        [-size * 0.25, -size * 0.25, size * 1.25, size * 1.25], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(size // 12))
    dark = Image.new("RGB", (size, size), (0, 0, 0))
    dark.putalpha(m.point(lambda v: 255 - v))
    return add_over(img, dark)


def grad_slab(w, h, c_top, c_bottom, radius,
              edge_light=(255, 255, 255, 90)):
    """Rounded-rect slab with a vertical gradient, crisp outline and a
    horizontal highlight just under the top edge."""
    col = Image.new("RGB", (1, h))
    col.putdata([mix(c_top, c_bottom, y / max(1, h - 1)) for y in range(h)])
    slab = col.resize((w, h))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, w - 1, h - 1], radius=radius, fill=255)
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


def rounded_tile(rgb, size, corner=0.225):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * corner), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(rgb, (0, 0), mask)
    return out


def build_master():
    img = vgrad(S, BG_TOP, BG_BOTTOM)
    img = add_over(img, radial_glow(S, (S // 2, int(S * 0.44)), S * 0.48,
                                    GLOW_BG, strength=0.5))

    # --- lower stack: three tapering slabs, tiny glowing seams ---------------
    art = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    slab_h = int(S * SLAB_H)
    seam = int(S * SEAM_GAP)
    y = int(S * BOTTOM_Y)
    seams_y = []
    for w_frac, (c_top, c_bot) in zip(SLAB_W, SLAB_COLORS):
        w = int(S * w_frac)
        art.alpha_composite(grad_slab(w, slab_h, c_top, c_bot,
                                      radius=int(slab_h * 0.34)),
                            (S // 2 - w // 2, y - slab_h))
        seams_y.append(y - slab_h - seam // 2)
        y -= slab_h + seam

    seam_lyr = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ds = ImageDraw.Draw(seam_lyr, "RGBA")
    for sy, w_frac in zip(seams_y[:2], SLAB_W[:2]):
        w = int(S * w_frac * 0.82)
        ds.line([(S // 2 - w // 2, sy), (S // 2 + w // 2, sy)],
                fill=SEAM + (230,), width=max(4, S // 180))
    img = ImageChops.add(img, seam_lyr.filter(
        ImageFilter.GaussianBlur(S // 100)).convert("RGB"))

    # --- levitating top layer, slightly rotated -------------------------------
    w_top = int(S * TOP_W)
    lev_gap = int(S * LEV_GAP)
    fly = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    fly.alpha_composite(grad_slab(w_top, slab_h, TOP_COLORS[0], TOP_COLORS[1],
                                  radius=int(slab_h * 0.34),
                                  edge_light=(255, 255, 255, 130)),
                        (S // 2 - w_top // 2, y - slab_h - lev_gap))
    fly = fly.rotate(TOP_ROT, resample=Image.BICUBIC,
                     center=(S // 2, y - lev_gap))

    # its light pooling on the stack below
    pool = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(pool, "RGBA").ellipse(
        [S // 2 - int(S * 0.20), y - slab_h - seam - int(S * 0.030),
         S // 2 + int(S * 0.20), y - slab_h - seam + int(S * 0.030)],
        fill=POOL + (150,))
    img = add_over(img, pool.filter(ImageFilter.GaussianBlur(S // 60)))

    img = add_over(img, art)
    img = add_over(img, fly)

    # sparks drifting up through the levitation gap
    sparks = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dsp = ImageDraw.Draw(sparks, "RGBA")
    for sx, sy, r in ((S * 0.36, y - int(S * 0.055), 7),
                      (S * 0.63, y - int(S * 0.075), 5),
                      (S * 0.52, y - int(S * 0.038), 4)):
        dsp.ellipse([sx - r, sy - r, sx + r, sy + r], fill=SPARK + (220,))
    img = add_over(img, sparks.filter(ImageFilter.GaussianBlur(3)))

    # build-plate glow under the whole stack
    under = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(under, "RGBA").ellipse(
        [S // 2 - int(S * 0.30), int(S * 0.79),
         S // 2 + int(S * 0.30), int(S * 0.79) + int(S * 0.055)],
        fill=UNDER + (80,))
    img = add_over(img, under.filter(ImageFilter.GaussianBlur(S // 30)))

    # gentle additive bleed from the bright shapes
    for shapes, blur, gain in ((art, S // 90, 0.8), (fly, S // 70, 0.8)):
        glow = Image.new("RGB", (S, S), (0, 0, 0))
        glow.paste(shapes.convert("RGB"), (0, 0), shapes.split()[-1])
        glow = glow.filter(ImageFilter.GaussianBlur(blur))
        img = ImageChops.add(img, glow.point(lambda v: int(v * gain)))

    return rounded_tile(vignette(img, S), S)


def main():
    master = build_master().resize((1024, 1024), Image.LANCZOS)
    master.resize((512, 512), Image.LANCZOS).save(
        os.path.join(HERE, "icon-preview.png"))
    master.save(
        os.path.join(HERE, "stratum-webui.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
               (64, 64), (128, 128), (256, 256)])
    print("wrote stratum-webui.ico + icon-preview.png in", HERE)


if __name__ == "__main__":
    main()
