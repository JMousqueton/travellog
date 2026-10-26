"""Image PNG du bilan annuel (1080 × 1350, format portrait des réseaux sociaux), dessinée avec Pillow."""
import io
import os
from functools import lru_cache

from babel.dates import get_month_names
from flask_babel import gettext as _
from flask_babel import ngettext
from PIL import Image, ImageDraw, ImageFont

from .i18n import current_locale, format_co2, format_distance, format_number

FONT_FILE = os.path.join(os.path.dirname(__file__), "data", "fonts", "Inter.ttf")
WIDTH, HEIGHT = 1080, 1350
MARGIN = 80
TOP, BOTTOM = (67, 56, 202), (124, 58, 237)  # dégradé indigo -> violet
WHITE = (255, 255, 255)
SOFT = (224, 231, 255)


@lru_cache(maxsize=32)
def _font(size, weight="Regular"):
    font = ImageFont.truetype(FONT_FILE, size)
    font.set_variation_by_name(weight)
    return font


def _fit(draw, text, max_width, size, weight="Regular", min_size=24):
    """Police la plus grande (≤ size) où le texte tient ; sinon texte tronqué avec « … »."""
    while size > min_size and draw.textlength(text, font=_font(size, weight)) > max_width:
        size -= 2
    font = _font(size, weight)
    if draw.textlength(text, font=font) <= max_width:
        return text, font
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…", font


def _background():
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        draw.line([(0, y), (WIDTH, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    return image


def render(review, title, url=""):
    image = _background()
    # Mode RGBA : les remplissages semi-transparents se mélangent au fond, dans l'ordre du dessin.
    draw = ImageDraw.Draw(image, "RGBA")
    inner = WIDTH - 2 * MARGIN

    draw.text((MARGIN, 70), title, font=_font(34, "Medium"), fill=SOFT)
    draw.text((MARGIN - 6, 110), str(review["year"]), font=_font(190, "Black"), fill=WHITE)
    draw.text((MARGIN, 330), _("Mon année en voyages"), font=_font(46, "SemiBold"), fill=WHITE)

    # Chiffres clés : grille 2 × 2.
    cards = [
        (format_number(review["count"]), ngettext("voyage", "voyages", review["count"])),
        (format_distance(review["distance_km"]), _("parcourus")),
        (format_number(len(review["countries"])), ngettext("pays", "pays", len(review["countries"]))),
        (format_co2(review["co2_kg"]), _("de CO₂ estimé")),
    ]
    gap, card_w, card_h, y0 = 24, (inner - 24) // 2, 150, 410
    for index, (value, label) in enumerate(cards):
        x = MARGIN + (index % 2) * (card_w + gap)
        y = y0 + (index // 2) * (card_h + gap)
        draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=28, fill=(255, 255, 255, 34))
        text, font = _fit(draw, value, card_w - 60, 68, "Bold")
        draw.text((x + 30, y + 20), text, font=font, fill=WHITE)
        draw.text((x + 30, y + 100), label, font=_font(30), fill=SOFT)

    y = y0 + 2 * card_h + gap + 40
    laps = review["earth_laps"]
    parts = []
    if review.get("days_away"):
        parts.append(ngettext("%(num)s jour loin de chez moi", "%(num)s jours loin de chez moi", review["days_away"]))
    if laps >= 0.1:
        parts.append(_("Soit %(laps)s fois le tour de la Terre", laps=format_number(round(laps, 1))))
    if parts:
        text, font = _fit(draw, " · ".join(parts), inner, 34, "Medium")
        draw.text((MARGIN, y), text, font=font, fill=WHITE)
        y += 60

    longest = review["longest"]
    draw.text((MARGIN, y), _("Le plus long trajet").upper(), font=_font(24, "SemiBold"), fill=SOFT)
    route, font = _fit(draw, f"{longest.origin_name} → {longest.dest_name}", inner, 40, "Bold")
    draw.text((MARGIN, y + 36), route, font=font, fill=WHITE)
    draw.text((MARGIN, y + 88), format_distance(longest.total_distance_km), font=_font(30), fill=SOFT)
    y += 140

    if review["new_countries"]:
        draw.text((MARGIN, y), _("Nouveaux pays").upper(), font=_font(24, "SemiBold"), fill=SOFT)
        names, font = _fit(draw, ", ".join(c["name"] for c in review["new_countries"]), inner, 36, "SemiBold")
        draw.text((MARGIN, y + 36), names, font=font, fill=WHITE)
        y += 120

    # Mois de départ : 12 barres, calées en bas de l'image (les blocs au-dessus ont une hauteur bornée).
    months, peak = review["months"], max(review["months"]) or 1
    labels = get_month_names("narrow", locale=current_locale())
    chart_h = 110
    chart_top = HEIGHT - 95 - 36 - chart_h
    bar_gap = 14
    bar_w = (inner - 11 * bar_gap) / 12
    for m, count in enumerate(months):
        x = MARGIN + m * (bar_w + bar_gap)
        h = max(8, chart_h * count / peak) if count else 8
        fill = (255, 255, 255, 230) if count else (255, 255, 255, 60)
        draw.rounded_rectangle([x, chart_top + chart_h - h, x + bar_w, chart_top + chart_h], radius=8, fill=fill)
        letter = labels[m + 1]
        lw = draw.textlength(letter, font=_font(24, "Medium"))
        draw.text((x + (bar_w - lw) / 2, chart_top + chart_h + 12), letter, font=_font(24, "Medium"), fill=SOFT)

    # Adresse du site (APP_BASE_URL), centrée en bas, sans le protocole.
    site = url.split("://", 1)[-1].rstrip("/")
    if site:
        text, font = _fit(draw, site, inner, 28, "Medium")
        draw.text((WIDTH / 2, HEIGHT - 50), text, font=font, fill=SOFT, anchor="ms")

    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()
