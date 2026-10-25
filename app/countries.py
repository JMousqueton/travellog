"""Pays : recherche hors ligne d'un point (Natural Earth 1:50m), noms localisés, drapeaux et surfaces."""
import json
import math
import os
from functools import lru_cache

from babel import Locale

from .geo import haversine_km

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "countries.geojson")
# Un point côtier peut tomber juste hors du tracé simplifié : on retient le pays le plus proche dans ce rayon.
COAST_TOLERANCE_KM = 25


# Continents (codes Natural Earth) -> région CLDR, pour un nom localisé par Babel.
CONTINENTS = {"EU": "150", "AS": "142", "AF": "002", "NA": "003", "SA": "005", "OC": "009", "AN": "AQ"}


class _Country:
    __slots__ = ("code", "continent", "area_km2", "polygons", "bbox", "feature")

    def __init__(self, feature):
        self.feature = feature
        self.code = feature["properties"]["code"]
        self.continent = feature["properties"].get("continent")
        self.area_km2 = feature["properties"]["area_km2"]
        self.polygons = []  # (bbox, anneaux)
        for rings in feature["geometry"]["coordinates"]:
            lons = [p[0] for p in rings[0]]
            lats = [p[1] for p in rings[0]]
            self.polygons.append(((min(lons), min(lats), max(lons), max(lats)), rings))
        boxes = [b for b, _ in self.polygons]
        self.bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes))


@lru_cache(maxsize=1)
def _countries():
    with open(DATA_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    return {c.code: c for c in map(_Country, data["features"])}


def _in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_box(lon, lat, box, margin=0.0):
    return box[0] - margin <= lon <= box[2] + margin and box[1] - margin <= lat <= box[3] + margin


def _segment_distance_km(lat, lon, a, b):
    """Distance approchée d'un point à un segment (projection équirectangulaire locale)."""
    kx = math.cos(math.radians(lat))
    ax, ay = (a[0] - lon) * kx, a[1] - lat
    bx, by = (b[0] - lon) * kx, b[1] - lat
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    px, py = ax + t * dx, ay + t * dy
    return haversine_km(lat, lon, lat + py, lon + px / kx if kx else lon)


def country_at(lat, lon):
    """Code ISO 3166-1 alpha-2 du pays contenant le point, ou None (en mer, loin des côtes)."""
    if lat is None or lon is None:
        return None
    countries = _countries().values()
    for country in countries:
        if not _in_box(lon, lat, country.bbox):
            continue
        for box, rings in country.polygons:
            if _in_box(lon, lat, box) and _in_ring(lon, lat, rings[0]) \
                    and not any(_in_ring(lon, lat, hole) for hole in rings[1:]):
                return country.code
    margin = COAST_TOLERANCE_KM / 111 / max(math.cos(math.radians(lat)), 0.1)
    best, best_km = None, COAST_TOLERANCE_KM
    for country in countries:
        if not _in_box(lon, lat, country.bbox, margin):
            continue
        for box, rings in country.polygons:
            if not _in_box(lon, lat, box, margin):
                continue
            ring = rings[0]
            for a, b in zip(ring, ring[1:]):
                km = _segment_distance_km(lat, lon, a, b)
                if km < best_km:
                    best, best_km = country.code, km
    return best


def is_known(code):
    return code in _countries()


def continent(code):
    country = _countries().get(code)
    return country.continent if country else None


def continent_name(code, locale):
    return country_name(CONTINENTS.get(code, code), locale)


def area_km2(code):
    country = _countries().get(code)
    return country.area_km2 if country else 0


def world_area_km2():
    return sum(c.area_km2 for c in _countries().values())


def features(codes):
    """Entités GeoJSON des pays demandés (pour la couche « pays visités »)."""
    countries = _countries()
    return [countries[code].feature for code in codes if code in countries]


def country_name(code, locale):
    """Nom localisé (CLDR) ; le code lui-même si inconnu."""
    try:
        return Locale.parse(locale).territories.get(code) or code
    except (ValueError, TypeError):
        return code


def flag(code):
    """Drapeau en émoji (indicateurs régionaux Unicode)."""
    if not code or len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())
