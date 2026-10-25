"""Génère app/data/regions.json : régions (États, provinces, Länder, cantons…) des grands pays, pour compter
celles qu'on a visitées. D'après les subdivisions Natural Earth 1:10m (domaine public).

    .venv/bin/python scripts/make_region_data.py [ne_10m_admin_1_states_provinces.geojson]

Le fichier source (environ 40 Mo) est téléchargé s'il n'est pas fourni. Pour la France, l'Espagne et l'Italie,
les départements ou provinces sont regroupés en régions ; pour le Royaume-Uni, en nations.
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
SOURCE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
              "ne_10m_admin_1_states_provinces.geojson")
OUT = os.path.join(ROOT, "app", "data", "regions.json")
LANGUAGES = ("fr", "en", "es", "de", "it")
STEP = 0.05       # distance minimale (en degrés) entre deux points gardés : environ 5 km
MIN_AREA = 0.002  # îlots plus petits ignorés (degrés carrés)
DIGITS = 3

# Pays retenus -> propriété qui regroupe les subdivisions (None : une région par subdivision).
COUNTRIES = {
    "US": None, "CA": None, "MX": None, "BR": None, "AU": None, "DE": None, "CH": None, "JP": None,
    "CN": None, "IN": None, "FR": "region", "ES": "region", "IT": "region", "GB": "geonunit",
}
# Subdivisions trop petites pour compter (îles isolées, territoires sans habitants).
SKIP = {"Paracel Islands", "Jervis Bay Territory", "Macquarie Island", "Lord Howe Island",
        "Ashmore and Cartier Islands"}
# Noms de région Natural Earth en anglais ou abrégés -> nom local.
RENAME = {
    "Apulia": "Puglia", "Sicily": "Sicilia", "Canary Is.": "Canarias", "Valenciana": "Comunitat Valenciana",
    "Foral de Navarra": "Navarra", "Islas Baleares": "Illes Balears",
}


def signed_area(ring):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / 2


def simplify(ring):
    kept = [ring[0]]
    for x, y in ring[1:-1]:
        if abs(x - kept[-1][0]) + abs(y - kept[-1][1]) >= STEP:
            kept.append((x, y))
    kept.append(ring[0])
    if len(kept) < 4:
        kept = ring  # trop petit pour simplifier
    return [[round(x, DIGITS), round(y, DIGITS)] for x, y in kept]


def polygons(geometry):
    coords = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    # Le plus grand contour est toujours gardé : les petites régions restent comptées (Ceuta, Melilla…).
    largest = max(range(len(coords)), key=lambda i: abs(signed_area([tuple(p[:2]) for p in coords[i][0]])))
    out = []
    for number, polygon in enumerate(coords):
        outer = [tuple(p[:2]) for p in polygon[0]]
        if abs(signed_area(outer)) < MIN_AREA and number != largest:
            continue
        holes = [simplify([tuple(p[:2]) for p in ring]) for ring in polygon[1:]
                 if abs(signed_area([tuple(p[:2]) for p in ring])) >= MIN_AREA]
        out.append([simplify(outer), *holes])
    return out


def load(path):
    if path is None:
        print(f"Téléchargement de {SOURCE_URL}…")
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
            return json.load(response)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    source = load(sys.argv[1] if len(sys.argv) > 1 else None)
    regions = {}
    for feature in source["features"]:
        p = feature["properties"]
        country = p.get("iso_a2")
        if country not in COUNTRIES or not p["name"] or p["name"] in SKIP or feature["geometry"] is None \
                or (p.get("iso_3166_2") or "").endswith("~"):
            continue
        group = COUNTRIES[country]
        if group:
            name = (p.get(group) or p["name"]).strip()
            name = RENAME.get(name, name)
            key = f"{country}:{name}"
            names = {lang: name for lang in LANGUAGES}
        else:
            key = p.get("iso_3166_2") or f"{country}:{p['name']}"
            names = {lang: p.get(f"name_{lang}") or p["name"] for lang in LANGUAGES}
        entry = regions.setdefault(key, {"id": key, "country": country, "names": names, "polygons": []})
        entry["polygons"].extend(polygons(feature["geometry"]))
    rows = sorted((r for r in regions.values() if r["polygons"]), key=lambda r: (r["country"], r["id"]))
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"regions": rows}, fh, ensure_ascii=False, separators=(",", ":"))
    per_country = {}
    for row in rows:
        per_country[row["country"]] = per_country.get(row["country"], 0) + 1
    print(f"{len(rows)} régions ({per_country}), {os.path.getsize(OUT) // 1024} Ko écrits dans {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
