import re
import unicodedata
from collections import Counter, defaultdict

from flask_babel import format_percent, ngettext

from .. import countries as geo_countries
from ..i18n import current_locale, format_co2, format_countdown, format_distance, format_number, format_share
from ..transport import SERVICE_FIELDS, TRANSPORT_MODES
from .. import utils


def count_label(count):
    return ngettext("%(count)s voyage", "%(count)s voyages", count, count=format_number(count))


def trip_count(trips):
    """Nombre de voyages : un voyage en plusieurs trajets compte pour un."""
    journeys = {t.journey_id for t in trips if t.journey_id is not None}
    return len(journeys) + sum(1 for t in trips if t.journey_id is None)


def visited_countries(trips):
    """Codes des pays visités, dans l'ordre chronologique de la première visite."""
    ordered = sorted(trips, key=lambda t: (t.depart_date, t.id))
    return list(dict.fromkeys(code for t in ordered for code in t.countries))


def land_share(codes):
    """Part des terres émergées couverte par ces pays (0 à 1)."""
    return sum(geo_countries.area_km2(c) for c in codes) / geo_countries.world_area_km2()


def compute_stats(trips):
    total_km = sum(t.total_distance_km for t in trips)
    total_co2 = sum(t.co2_kg for t in trips)
    codes = visited_countries(trips)
    covered = land_share(codes)
    count = trip_count(trips)
    by_mode = []
    for key, mode in TRANSPORT_MODES.items():
        subset = [t for t in trips if t.transport_mode == key]
        if not subset:
            continue
        km = sum(t.total_distance_km for t in subset)
        co2 = sum(t.co2_kg for t in subset)
        share = len(subset) / len(trips)
        by_mode.append({
            "mode": key,
            "label": str(mode["label"]),
            "icon": mode["icon"],
            "count": len(subset),
            "count_fmt": format_number(len(subset)),
            "share": share,
            "share_fmt": format_percent(share),
            "distance_km": round(km, 1),
            "distance_fmt": format_distance(km),
            "co2_kg": round(co2, 1),
            "co2_fmt": format_co2(co2),
        })
    by_mode.sort(key=lambda m: m["count"], reverse=True)
    return {
        "count": count,
        "count_fmt": format_number(count),
        "count_label": count_label(count),
        "legs": len(trips),
        "round_trips": sum(1 for t in trips if t.is_round_trip),
        "total_distance_km": round(total_km, 1),
        "total_distance_fmt": format_distance(total_km),
        "co2_kg": round(total_co2, 1),
        "co2_fmt": format_co2(total_co2),
        "countries": len(codes),
        "countries_fmt": format_number(len(codes)),
        "land_share": covered,
        "land_share_fmt": format_share(covered),
        "by_mode": by_mode,
        "next_trip": next_trip(trips),
    }


def upcoming_trips(trips):
    """Trajets pas encore partis, du plus proche au plus lointain."""
    return sorted((t for t in trips if t.depart_date > utils.today()), key=lambda t: (t.depart_date, t.id))


def happened(trips):
    """Trajets déjà commencés : seuls ceux-ci comptent dans les statistiques « visitées »."""
    return [t for t in trips if t.depart_date <= utils.today()]


def next_trip(trips):
    upcoming = upcoming_trips(trips)
    if not upcoming:
        return None
    trip = upcoming[0]
    return {"id": trip.id, "route": f"{trip.origin_name} → {trip.dest_name}", "mode": trip.transport_mode,
            "countdown": format_countdown(trip.depart_date, trip.end_date)}


def yearly_stats(trips):
    """Une ligne par année de départ (la plus récente d'abord), avec les pays découverts cette année-là."""
    by_year = defaultdict(list)
    for trip in trips:
        by_year[trip.depart_date.year].append(trip)
    seen, rows = set(), []
    for year in sorted(by_year):
        items = by_year[year]
        codes = visited_countries(items)
        new = [c for c in codes if c not in seen]
        seen.update(codes)
        km = sum(t.total_distance_km for t in items)
        co2 = sum(t.co2_kg for t in items)
        rows.append({
            "year": year,
            "count": trip_count(items),
            "legs": len(items),
            "distance_km": km,
            "co2_kg": co2,
            "countries": codes,
            "new_countries": new,
            "modes": {m: sum(1 for t in items if t.transport_mode == m) for m in TRANSPORT_MODES},
            "mode_km": {m: sum(t.total_distance_km for t in items if t.transport_mode == m) for m in TRANSPORT_MODES},
        })
    return rows[::-1]


def country_summary(trips):
    """Pays visités, du plus visité au moins visité (puis par ordre alphabétique) : nom localisé,
    drapeau, nombre de trajets, première et dernière visite."""
    locale = current_locale()
    info = {}
    for trip in sorted(trips, key=lambda t: (t.depart_date, t.id)):
        for code in trip.countries:
            entry = info.setdefault(code, {"code": code, "name": geo_countries.country_name(code, locale),
                                           "flag": geo_countries.flag(code), "trips": 0,
                                           "first": trip.depart_date, "last": trip.depart_date})
            entry["trips"] += 1
            entry["last"] = trip.depart_date
    return sorted(info.values(), key=lambda e: (-e["trips"], _sort_key(e["name"])))


def _sort_key(name):
    """Tri alphabétique sans tenir compte des accents (États-Unis avec les E)."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()


def tag_stats(trips):
    """Par étiquette : nombre, distance et CO₂ (au total et pour l'année en cours). None = sans étiquette."""
    year = utils.today().year
    groups = defaultdict(list)
    for trip in trips:
        for tag in trip.tags or [None]:
            groups[tag].append(trip)
    if list(groups) == [None]:
        return []  # aucune étiquette utilisée
    rows = []
    for tag, items in groups.items():
        this_year = [t for t in items if t.depart_date.year == year]
        rows.append({
            "tag": tag,
            "name": tag.name if tag else None,
            "count": trip_count(items),
            "distance_km": sum(t.total_distance_km for t in items),
            "co2_kg": sum(t.co2_kg for t in items),
            "year_count": trip_count(this_year),
            "year_co2_kg": sum(t.co2_kg for t in this_year),
        })
    # Étiquettes par émissions décroissantes, « sans étiquette » en dernier.
    return sorted(rows, key=lambda r: (r["tag"] is None, -r["co2_kg"], _sort_key(r["name"] or "")))


SERVICE_TOP = 8


def _per_leg(trip, value):
    """Valeur d'un champ pour chaque sens effectué : « AF1148 / AF1549 » sur un aller-retour → une par sens."""
    if not value:
        return []
    legs = 2 if trip.is_round_trip else 1
    parts = [part.strip() for part in value.split(" / ") if part.strip()]
    return parts if len(parts) == legs else [value] * legs


def service_stats(trips):
    """Avion et train : nombre de vols ou de trajets, compagnies, appareils et aéroports ou gares les plus fréquents."""
    rows = []
    for mode in SERVICE_FIELDS:
        items = [t for t in trips if t.transport_mode == mode]
        if not items:
            continue
        carriers, vehicles, places = Counter(), Counter(), Counter()
        for trip in items:
            carriers.update(_per_leg(trip, trip.carrier))
            vehicles.update(_per_leg(trip, trip.vehicle))
            legs = 2 if trip.is_round_trip else 1
            places.update({trip.origin_name: legs})
            places.update({trip.dest_name: legs})
        rows.append({
            "mode": mode,
            "legs": sum(2 if t.is_round_trip else 1 for t in items),
            "distance_km": sum(t.total_distance_km for t in items),
            "carriers": carriers.most_common(SERVICE_TOP),
            "vehicles": vehicles.most_common(SERVICE_TOP),
            "places": places.most_common(SERVICE_TOP),
        })
    return rows


# Constructeurs reconnus en tête du nom d'appareil (« Airbus A321 », « Boeing 777-300 ER »…).
MANUFACTURERS = ("Airbus", "Boeing", "Embraer", "ATR", "Bombardier", "De Havilland", "Fokker",
                 "McDonnell Douglas", "Hawker Beechcraft", "Beechcraft", "Saab", "Dornier", "Sukhoi", "Comac",
                 "Tupolev", "Ilyushin", "Antonov", "Cessna", "Pilatus")
IATA_SUFFIX = re.compile(r"\(([A-Z0-9]{3})\)$")  # « Charles de Gaulle International Airport (CDG) »


def legs(trip):
    """Sens effectués d'un trajet : l'aller, plus le retour d'un aller-retour (compagnie, appareil et numéro
    répartis d'après « AF1148 / AF1549 »)."""
    count = 2 if trip.is_round_trip else 1

    def split(value):
        return _per_leg(trip, value) or [None] * count

    ends = [(trip.depart_date, trip.origin_name, trip.dest_name)]
    if trip.is_round_trip:
        ends.append((trip.return_date, trip.dest_name, trip.origin_name))
    return [{"date": day, "origin": origin, "dest": dest, "carrier": carrier, "vehicle": vehicle, "number": number,
             "km": trip.distance_km}
            for (day, origin, dest), carrier, vehicle, number
            in zip(ends, split(trip.carrier), split(trip.vehicle), split(trip.service_number))]


def manufacturer(vehicle):
    for name in MANUFACTURERS:
        if vehicle.casefold().startswith(name.casefold()):
            return name
    return vehicle.split()[0]


def short_place(name):
    """Code IATA d'un aéroport importé, sinon le nom jusqu'à la première virgule."""
    match = IATA_SUFFIX.search(name)
    return match.group(1) if match else name.split(",")[0]


def _ranking(rows, key, year):
    """Regroupe les sens par `key` : nombre, distance, part, première et dernière date, nombre cette année."""
    groups = defaultdict(list)
    for leg in rows:
        if leg[key]:
            groups[leg[key]].append(leg)
    total = sum(len(items) for items in groups.values())
    ranking = [{"name": name, "count": len(items), "km": sum(leg["km"] for leg in items),
                "share": len(items) / total, "first": min(leg["date"] for leg in items),
                "last": max(leg["date"] for leg in items),
                "year_count": sum(1 for leg in items if leg["date"].year == year)}
               for name, items in groups.items()]
    return sorted(ranking, key=lambda r: (-r["count"], -r["km"], _sort_key(r["name"])))


def transport_details(trips, mode):
    """Page de détail d'un mode (avion ou train) : compagnies, appareils, constructeurs, lignes, lieux."""
    year = utils.today().year
    rows = [leg for trip in trips if trip.transport_mode == mode for leg in legs(trip)]
    for leg in rows:
        leg["manufacturer"] = manufacturer(leg["vehicle"]) if leg["vehicle"] and mode == "plane" else None
        leg["route"] = " – ".join(sorted((short_place(leg["origin"]), short_place(leg["dest"]))))
    places = Counter(name for leg in rows for name in (leg["origin"], leg["dest"]))
    return {
        "mode": mode,
        "legs": len(rows),
        "year_legs": sum(1 for leg in rows if leg["date"].year == year),
        "km": sum(leg["km"] for leg in rows),
        "missing_carrier": sum(1 for leg in rows if not leg["carrier"]),
        "missing_vehicle": sum(1 for leg in rows if not leg["vehicle"]),
        "carriers": _ranking(rows, "carrier", year),
        "vehicles": _ranking(rows, "vehicle", year),
        "manufacturers": _ranking(rows, "manufacturer", year),
        "routes": _ranking(rows, "route", year)[:15],
        "places": places.most_common(15),
    }


EARTH_CIRCUMFERENCE_KM = 40_075


REVIEW_GRACE_MONTHS = 2  # lien de partage : en janvier et février, le bilan de l'année écoulée reste visible


def open_review_years(trips):
    """Années dont le bilan est consultable par un lien de partage : l'année en cours, et la précédente en
    janvier et février."""
    today = utils.today()
    allowed = {today.year} | ({today.year - 1} if today.month <= REVIEW_GRACE_MONTHS else set())
    return [year for year in review_years(trips) if year in allowed]


def review_years(trips):
    """Années ayant au moins un trajet déjà commencé, de la plus récente à la plus ancienne."""
    return sorted({t.depart_date.year for t in happened(trips)}, reverse=True)


def year_review(trips, year):
    """Bilan d'une année : chiffres clés, pays découverts, trajet le plus long, mois actifs…"""
    done = happened(trips)
    items = sorted((t for t in done if t.depart_date.year == year), key=lambda t: (t.depart_date, t.id))
    if not items:
        return None
    seen_before = set(visited_countries([t for t in done if t.depart_date.year < year]))
    countries = visited_countries(items)
    locale = current_locale()
    km = sum(t.total_distance_km for t in items)
    by_mode = defaultdict(float)
    for trip in items:
        by_mode[trip.transport_mode] += trip.total_distance_km
    destinations = defaultdict(int)
    for trip in items:
        destinations[trip.dest_name] += 1
    longest = max(items, key=lambda t: t.total_distance_km)
    months = [0] * 12
    for trip in items:
        months[trip.depart_date.month - 1] += 1
    return {
        "year": year,
        "count": trip_count(items),
        "legs": len(items),
        "distance_km": km,
        "earth_laps": km / EARTH_CIRCUMFERENCE_KM,
        "co2_kg": sum(t.co2_kg for t in items),
        "countries": [{"code": c, "name": geo_countries.country_name(c, locale), "flag": geo_countries.flag(c)}
                      for c in countries],
        "new_countries": [{"code": c, "name": geo_countries.country_name(c, locale), "flag": geo_countries.flag(c)}
                          for c in countries if c not in seen_before],
        "longest": longest,
        "top_mode": max(by_mode, key=by_mode.get),
        "mode_km": dict(sorted(by_mode.items(), key=lambda kv: -kv[1])),
        "top_destinations": sorted(destinations.items(), key=lambda kv: (-kv[1], _sort_key(kv[0])))[:3],
        "months": months,
        "first": items[0],
        "last": items[-1],
        "photos": sum(len(t.photos) for t in items)
        + sum(len(j.photos) for j in {t.journey for t in items if t.journey}),
    }
