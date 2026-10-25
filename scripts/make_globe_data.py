"""Génère app/static/data/world.json : contours simplifiés des pays pour le globe de la carte, d'après
app/data/countries.geojson (Natural Earth). Chaque entité garde son code ISO pour colorer les pays visités.

d3-geo travaille sur la sphère : l'anneau extérieur d'un polygone doit tourner dans le sens horaire et les trous
dans le sens inverse, sinon le polygone couvre tout le reste du globe. Les anneaux sont réorientés ici.

    .venv/bin/python scripts/make_globe_data.py
"""
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
SOURCE = os.path.join(ROOT, "app", "data", "countries.geojson")
OUT = os.path.join(ROOT, "app", "static", "data", "world.json")
STEP = 0.5        # distance minimale (en degrés) entre deux points gardés
MIN_AREA = 0.04   # surface minimale (degrés carrés) d'un contour gardé
DIGITS = 2


def signed_area(ring):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / 2


def simplify(ring):
    kept = [ring[0]]
    for x, y in ring[1:-1]:
        if abs(x - kept[-1][0]) + abs(y - kept[-1][1]) >= STEP:
            kept.append((x, y))
    kept.append(ring[0])
    return [[round(x, DIGITS), round(y, DIGITS)] for x, y in kept]


def orient(ring, clockwise):
    # Repère longitude/latitude, nord en haut : une surface signée négative correspond au sens horaire.
    return ring if (signed_area(ring) < 0) == clockwise else ring[::-1]


def main():
    with open(SOURCE, encoding="utf-8") as fh:
        features = json.load(fh)["features"]
    out = []
    for feature in features:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        # Le plus grand contour est toujours gardé : les micro-États restent visibles (Monaco, Singapour…).
        largest = max(range(len(polygons)), key=lambda i: abs(signed_area([tuple(p[:2]) for p in polygons[i][0]])))
        kept = []
        for number, polygon in enumerate(polygons):
            rings = []
            for index, ring in enumerate(polygon):
                ring = [tuple(point[:2]) for point in ring]
                if abs(signed_area(ring)) < MIN_AREA and not (index == 0 and number == largest):
                    if index == 0:
                        break
                    continue
                simple = simplify(ring)
                if len(simple) < 4 and index == 0 and number == largest:
                    simple = [[round(x, DIGITS), round(y, DIGITS)] for x, y in ring]  # trop petit pour simplifier
                ring = simple
                if len(ring) >= 4:
                    rings.append(orient(ring, clockwise=index == 0))
                elif index == 0:
                    break
            if rings and len(rings[0]) >= 4:
                kept.append(rings)
        if kept:
            out.append({"type": "Feature", "properties": {"code": feature["properties"]["code"]},
                        "geometry": {"type": "MultiPolygon", "coordinates": kept}})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": out}, fh, separators=(",", ":"))
    print(f"{len(out)} pays, {os.path.getsize(OUT) // 1024} Ko écrits dans {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
