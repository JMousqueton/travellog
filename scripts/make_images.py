"""Génère les images statiques : icônes PNG (d'après favicon.svg) et image de partage 1200 × 630.

    .venv/bin/python scripts/make_images.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "app", "static", "img")
FONT = os.path.join(ROOT, "app", "data", "fonts", "Inter.ttf")
BRAND, BRAND_2, WHITE = (79, 70, 229), (124, 58, 237), (255, 255, 255)


def bezier(p0, p1, p2, steps=64):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / steps for i in range(steps + 1))]


def icon(size, rounded=True):
    """Reproduit favicon.svg (carré arrondi, arc de trajet, deux points), suréchantillonné puis réduit."""
    scale = 8
    s = size * scale / 64
    im = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, size * scale - 1, size * scale - 1], radius=16 * s if rounded else 0, fill=BRAND)
    d.line([(x * s, y * s) for x, y in bezier((14, 44), (32, 8), (50, 40))], fill=WHITE, width=round(5 * s), joint="curve")
    for cx, cy in ((14, 44), (50, 40)):
        d.ellipse([(cx - 6) * s, (cy - 6) * s, (cx + 6) * s, (cy + 6) * s], fill=WHITE)
    return im.resize((size, size), Image.Resampling.LANCZOS)


def font(size, weight):
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_name(weight)
    return f


def og_image():
    w, h = 1200, 630
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im, "RGBA")
    for x in range(w):  # dégradé horizontal
        t = x / (w - 1)
        d.line([(x, 0), (x, h)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BRAND, BRAND_2)))
    # Arcs de trajets stylisés, comme sur la carte (aller plein, retour en pointillés).
    for (p0, p1, p2), dashed in ((((850, 470), (990, 150), (1130, 330)), False),
                                 (((850, 470), (1000, 360), (1130, 330)), True),
                                 (((880, 560), (960, 450), (1060, 530)), False)):
        points = bezier(p0, p1, p2, 120)
        for i in range(len(points) - 1):
            if not dashed or (i // 4) % 2 == 0:
                d.line([points[i], points[i + 1]], fill=(255, 255, 255, 170 if dashed else 235), width=6)
        for cx, cy in (p0, p2):
            d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=WHITE)
    d.rounded_rectangle([74, 84, 206, 216], radius=36, outline=(255, 255, 255, 120), width=3)  # détache l'icône du fond
    im.paste(icon(120), (80, 90), icon(120))
    d.text((80, 250), "Voyage Voyage", font=font(76, "Black"), fill=WHITE)
    d.text((80, 345), "le carnet de voyages", font=font(48, "SemiBold"), fill=(224, 231, 255))
    d.text((80, 470), "voyage-voyage.app", font=font(30, "Medium"), fill=(224, 231, 255))
    return im


if __name__ == "__main__":
    icon(180, rounded=False).convert("RGB").save(os.path.join(OUT, "apple-touch-icon.png"), optimize=True)  # iOS arrondit lui-même
    icon(192).save(os.path.join(OUT, "icon-192.png"), optimize=True)
    icon(512).save(os.path.join(OUT, "icon-512.png"), optimize=True)
    og_image().save(os.path.join(OUT, "og-image.png"), optimize=True)
    print("ok")
