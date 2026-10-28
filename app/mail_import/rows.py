"""Lignes de trajet au format de l'export (valeurs texte), comme les imports de fichiers."""
from ..airports import place_name
from ..transfer.formats import LIMITS


def airport_place(airport):
    return {"name": place_name(airport), "lat": airport["lat"], "lon": airport["lon"], "country": airport["country"] or ""}


def make_row(day, mode, origin, dest, carrier="", number=""):
    """Ligne au format de l'export (valeurs texte), comme les imports de fichiers."""
    out = {"depart_date": day, "transport_mode": mode, "_errors": [], "notes": "", "vehicle": "",
           "carrier": (carrier or "")[:LIMITS["carrier"]], "service_number": (number or "")[:LIMITS["service_number"]]}
    for prefix, place in (("origin", origin), ("dest", dest)):
        out.update({f"{prefix}_name": place["name"][:LIMITS[f"{prefix}_name"]], f"{prefix}_lat": str(place["lat"]),
                    f"{prefix}_lon": str(place["lon"]), f"{prefix}_country": place["country"]})
    return out
