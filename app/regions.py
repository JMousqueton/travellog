"""Régions des grands pays (États, provinces, Länder, cantons…) : recherche hors ligne d'un point, noms localisés.

Données : app/data/regions.json, généré par scripts/make_region_data.py (Natural Earth 1:10m).
"""
import json
import math
import os
from functools import lru_cache

from flask_babel import lazy_gettext as _l

from .countries import _in_box, _in_ring, _segment_distance_km

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "regions.json")
# Un aéroport ou un port peut tomber juste hors du tracé simplifié : région la plus proche dans ce rayon.
COAST_TOLERANCE_KM = 15

# Nom des subdivisions de chaque pays, au pluriel (« 4 / 51 États »).
UNITS = {
    "US": _l("États"), "MX": _l("États"), "BR": _l("États"), "CA": _l("Provinces et territoires"),
    "AU": _l("États et territoires"), "IN": _l("États et territoires"), "DE": _l("Länder"), "CH": _l("Cantons"),
    "JP": _l("Préfectures"), "CN": _l("Provinces"), "FR": _l("Régions"), "IT": _l("Régions"),
    "ES": _l("Communautés autonomes"), "GB": _l("Nations"),
}

# Nations du Royaume-Uni : regroupées depuis les subdivisions, sans nom traduit dans les données.
NATIONS = {"England": _l("Angleterre"), "Scotland": _l("Écosse"), "Wales": _l("Pays de Galles"),
           "Northern Ireland": _l("Irlande du Nord")}


class _Region:
    __slots__ = ("id", "country", "names", "polygons", "bbox")

    def __init__(self, row):
        self.id = row["id"]
        self.country = row["country"]
        self.names = row["names"]
        self.polygons = []
        for rings in row["polygons"]:
            lons = [p[0] for p in rings[0]]
            lats = [p[1] for p in rings[0]]
            self.polygons.append(((min(lons), min(lats), max(lons), max(lats)), rings))
        boxes = [b for b, _ in self.polygons]
        self.bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes))


@lru_cache(maxsize=1)
def _regions():
    """Régions par pays, et index par identifiant."""
    with open(DATA_FILE, encoding="utf-8") as fh:
        rows = json.load(fh)["regions"]
    by_country, by_id = {}, {}
    for region in map(_Region, rows):
        by_country.setdefault(region.country, []).append(region)
        by_id[region.id] = region
    return by_country, by_id


def has_regions(country):
    return country in _regions()[0]


def region_count(country):
    return len(_regions()[0].get(country, ()))


def unit_label(country):
    return str(UNITS.get(country, _l("Régions")))


def region_name(region_id, locale):
    region = _regions()[1].get(region_id)
    if region is None:
        return region_id
    if region.country == "GB" and region.names.get("en") in NATIONS:
        return str(NATIONS[region.names["en"]])
    return region.names.get(str(locale).split("_")[0]) or region.names.get("en") or region_id


@lru_cache(maxsize=50_000)
def _lookup(lat, lon, country):
    regions = _regions()[0].get(country, ())
    for region in regions:
        if not _in_box(lon, lat, region.bbox):
            continue
        for box, rings in region.polygons:
            if _in_box(lon, lat, box) and _in_ring(lon, lat, rings[0]) \
                    and not any(_in_ring(lon, lat, hole) for hole in rings[1:]):
                return region.id
    margin = COAST_TOLERANCE_KM / 111 / max(math.cos(math.radians(lat)), 0.1)
    best, best_km = None, COAST_TOLERANCE_KM
    for region in regions:
        if not _in_box(lon, lat, region.bbox, margin):
            continue
        for box, rings in region.polygons:
            if not _in_box(lon, lat, box, margin):
                continue
            ring = rings[0]
            for a, b in zip(ring, ring[1:]):
                km = _segment_distance_km(lat, lon, a, b)
                if km < best_km:
                    best, best_km = region.id, km
    return best


def region_at(lat, lon, country):
    """Identifiant de la région du pays `country` contenant le point, ou None (pays sans régions, en mer…)."""
    if lat is None or lon is None or not has_regions(country):
        return None
    return _lookup(round(lat, 4), round(lon, 4), country)
