"""Aéroports par code IATA ou OACI (OurAirports, domaine public ; voir scripts/make_airports.py)."""
import csv
import os
from functools import lru_cache

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "airports.csv")


@lru_cache(maxsize=1)
def _index():
    index = {}
    with open(DATA_FILE, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            airport = {"iata": row["iata"], "name": row["name"], "country": row["country"] or None,
                       "lat": float(row["lat"]), "lon": float(row["lon"])}
            index[row["iata"]] = airport
            if row["icao"]:
                index.setdefault(row["icao"], airport)
    return index


def find_airport(code):
    """Aéroport d'un code IATA (3 caractères) ou OACI (4), ou None."""
    return _index().get((code or "").strip().upper())


def place_name(airport):
    return f"{airport['name']} ({airport['iata']})"
