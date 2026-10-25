"""Aéroports par code IATA ou OACI et compagnies par code OACI (voir scripts/make_flight_data.py)."""
import csv
import os
from functools import lru_cache

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "airports.csv")
AIRLINES_FILE = os.path.join(os.path.dirname(__file__), "data", "airlines.csv")


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


@lru_cache(maxsize=1)
def _airlines():
    with open(AIRLINES_FILE, encoding="utf-8", newline="") as fh:
        return {row["icao"]: row for row in csv.DictReader(fh)}


def find_airline(icao):
    """{icao, iata, name} d'une compagnie active, ou None."""
    return _airlines().get((icao or "").strip().upper())
