"""Génère app/data/airports.csv : aéroports ayant un code IATA.

    .venv/bin/python scripts/make_airports.py [airports.csv d'OurAirports] [airports.dat d'OpenFlights]

Sources, téléchargées si elles ne sont pas fournies :
- OurAirports (domaine public), la référence ;
- OpenFlights (ODbL), seulement pour les codes absents d'OurAirports : celui-ci retire le code IATA des
  aéroports fermés (Berlin-Tegel TXL, Schönefeld SXF…), qui figurent pourtant dans les historiques de vols.
"""
import csv
import io
import os
import sys
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from app.countries import country_at  # noqa: E402

OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OPENFLIGHTS = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
OUT = os.path.join(ROOT, "app", "data", "airports.csv")
# Quand deux aéroports partagent un code IATA, le plus important l'emporte.
TYPE_RANK = {"large_airport": 0, "medium_airport": 1, "small_airport": 2, "seaplane_base": 3, "heliport": 4}


def read(path_or_url):
    if not path_or_url.startswith("https://"):
        with open(path_or_url, encoding="utf-8") as fh:
            return fh.read()
    with urllib.request.urlopen(path_or_url, timeout=60) as response:
        return response.read().decode("utf-8")


def from_ourairports(text):
    best = {}
    for row in csv.DictReader(io.StringIO(text)):
        iata = row["iata_code"].strip().upper()
        if len(iata) != 3 or not iata.isalnum() or row["type"] not in TYPE_RANK:
            continue
        rank = (row["scheduled_service"] != "yes", TYPE_RANK[row["type"]])
        if iata not in best or rank < best[iata][0]:
            icao = (row.get("icao_code") or row["gps_code"] or row["ident"]).strip().upper()
            best[iata] = (rank, [iata, icao if len(icao) == 4 else "", row["name"].strip(),
                                 row["iso_country"].strip().upper(), float(row["latitude_deg"]),
                                 float(row["longitude_deg"])])
    return {iata: entry for iata, (_rank, entry) in best.items()}


def from_openflights(text, known):
    extra = {}
    for row in csv.reader(io.StringIO(text)):
        iata, icao = row[4].strip().upper(), row[5].strip().upper()
        if len(iata) != 3 or not iata.isalnum() or iata in known or iata in extra:
            continue
        lat, lon = float(row[6]), float(row[7])
        extra[iata] = [iata, icao if len(icao) == 4 else "", row[1].strip(), country_at(lat, lon) or "", lat, lon]
    return extra


def main():
    airports = from_ourairports(read(sys.argv[1] if len(sys.argv) > 1 else OURAIRPORTS))
    extra = from_openflights(read(sys.argv[2] if len(sys.argv) > 2 else OPENFLIGHTS), airports)
    airports.update(extra)
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["iata", "icao", "name", "country", "lat", "lon"])
        for iata, (code, icao, name, country, lat, lon) in sorted(airports.items()):
            writer.writerow([code, icao, name, country, f"{lat:.5f}", f"{lon:.5f}"])
    print(f"{len(airports)} aéroports ({len(extra)} d'OpenFlights) écrits dans {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
