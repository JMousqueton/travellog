"""Génère app/templates/partials/world_map.svg : carte du monde simplifiée (page 404), d'après les contours
Natural Earth de app/data/countries.geojson. Projection équirectangulaire, sans l'Antarctique ni les petites îles.

    .venv/bin/python scripts/make_world_svg.py
"""
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
SOURCE = os.path.join(ROOT, "app", "data", "countries.geojson")
OUT = os.path.join(ROOT, "app", "templates", "partials", "world_map.svg")
STEP = 1.5          # distance minimale (en degrés) entre deux points gardés
MIN_AREA = 3        # surface minimale (degrés carrés) d'un contour gardé
SOUTH_LIMIT = -58   # sous cette latitude : Antarctique, non dessiné


def area(ring):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2


def simplify(ring):
    kept = [ring[0]]
    for x, y in ring[1:]:
        if abs(x - kept[-1][0]) + abs(y - kept[-1][1]) >= STEP:
            kept.append((x, y))
    return kept


def path(ring):
    # x : longitude + 180 ; y : 90 - latitude (le nord en haut), arrondis au degré (moins d'un pixel affiché)
    points = list(dict.fromkeys(f"{round(x + 180)} {round(90 - y)}" for x, y in ring))
    return "M" + "L".join(points) + "Z"


def main():
    with open(SOURCE, encoding="utf-8") as fh:
        features = json.load(fh)["features"]
    parts = []
    for feature in features:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for polygon in polygons:
            ring = [tuple(point[:2]) for point in polygon[0]]
            if max(y for _x, y in ring) < SOUTH_LIMIT or area(ring) < MIN_AREA:
                continue
            ring = simplify(ring)
            if len(ring) >= 4:
                parts.append(path(ring))
    svg = ('<svg class="world-map" viewBox="0 0 360 150" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" '
           f'focusable="false"><path fill="currentColor" d="{"".join(parts)}"/></svg>\n')
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"{len(parts)} contours, {len(svg) // 1024} Ko écrits dans {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
