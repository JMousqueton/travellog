"""Import et export des voyages en CSV, GeoJSON et GPX.

Les trois formats portent les mêmes champs (FIELDS), si bien qu'un export peut être réimporté tel quel :
c'est aussi une sauvegarde (hors photos). Un aller-retour se reconnaît à la présence d'une date de retour ;
les trajets d'un même voyage partagent la même clé `journey_key`.

L'import CSV reconnaît aussi les historiques de vols exportés par Flighty et myFlightradar24.
"""
import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from flask_babel import gettext as _

from ..airports import find_airport, place_name
from ..geo import haversine_km
from ..transport import TRANSPORT_MODES

FIELDS = [
    "depart_date", "return_date", "transport_mode",
    "origin_name", "origin_lat", "origin_lon", "origin_country",
    "dest_name", "dest_lat", "dest_lon", "dest_country",
    "notes", "tags", "journey_key", "journey_name", "journey_notes",
]
TEXT_FIELDS = {"origin_name", "dest_name", "notes", "tags", "journey_key", "journey_name", "journey_notes"}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
GPX_NS = "http://www.topografix.com/GPX/1/1"
EXT_NS = "urn:carnet-de-voyages:gpx:1"
LIMITS = {"origin_name": 255, "dest_name": 255, "notes": 5000, "tags": 500, "journey_key": 64,
          "journey_name": 120, "journey_notes": 5000}


class FileFormatError(ValueError):
    """Fichier illisible dans son ensemble (format inconnu, JSON ou XML invalide…)."""


# --- Export ------------------------------------------------------------------------------

def trip_record(trip):
    journey = trip.journey
    return {
        "depart_date": trip.depart_date.isoformat(),
        "return_date": trip.return_date.isoformat() if trip.return_date else "",
        "transport_mode": trip.transport_mode,
        "origin_name": trip.origin_name, "origin_lat": trip.origin_lat, "origin_lon": trip.origin_lon,
        "origin_country": trip.origin_country or "",
        "dest_name": trip.dest_name, "dest_lat": trip.dest_lat, "dest_lon": trip.dest_lon,
        "dest_country": trip.dest_country or "",
        "notes": trip.notes or "",
        "tags": ", ".join(tag.name for tag in trip.tags),
        "journey_key": f"J{journey.id}" if journey else "",
        "journey_name": (journey.name or "") if journey else "",
        "journey_notes": (journey.notes or "") if journey else "",
    }


def _csv_safe(value):
    """Neutralise les formules (=, +, -, @) qu'un tableur exécuterait à l'ouverture."""
    text = str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def to_csv(records):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for record in records:
        writer.writerow({k: _csv_safe(v) if k in TEXT_FIELDS else v for k, v in record.items()})
    return "﻿" + out.getvalue()  # BOM : Excel reconnaît l'UTF-8


def to_geojson(records):
    features = []
    for r in records:
        props = {k: v for k, v in r.items() if k not in ("origin_lat", "origin_lon", "dest_lat", "dest_lon")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[r["origin_lon"], r["origin_lat"]], [r["dest_lon"], r["dest_lat"]]]},
            "properties": props,
        })
    return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=1)


def to_gpx(records, title):
    ET.register_namespace("", GPX_NS)
    ET.register_namespace("cv", EXT_NS)
    gpx = ET.Element(f"{{{GPX_NS}}}gpx", {"version": "1.1", "creator": title})
    meta = ET.SubElement(gpx, f"{{{GPX_NS}}}metadata")
    ET.SubElement(meta, f"{{{GPX_NS}}}name").text = title
    ET.SubElement(meta, f"{{{GPX_NS}}}time").text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in records:
        rte = ET.SubElement(gpx, f"{{{GPX_NS}}}rte")
        ET.SubElement(rte, f"{{{GPX_NS}}}name").text = f"{r['origin_name']} → {r['dest_name']}"
        if r["notes"]:
            ET.SubElement(rte, f"{{{GPX_NS}}}desc").text = r["notes"]
        ET.SubElement(rte, f"{{{GPX_NS}}}type").text = r["transport_mode"]
        ext = ET.SubElement(ET.SubElement(rte, f"{{{GPX_NS}}}extensions"), f"{{{EXT_NS}}}trip")
        for key in FIELDS:
            if key not in ("origin_lat", "origin_lon", "dest_lat", "dest_lon") and r[key] != "":
                ET.SubElement(ext, f"{{{EXT_NS}}}{key}").text = str(r[key])
        for prefix, when in (("origin", r["depart_date"]), ("dest", None)):
            pt = ET.SubElement(rte, f"{{{GPX_NS}}}rtept",
                               {"lat": repr(r[f"{prefix}_lat"]), "lon": repr(r[f"{prefix}_lon"])})
            if when:
                ET.SubElement(pt, f"{{{GPX_NS}}}time").text = f"{when}T00:00:00Z"
            ET.SubElement(pt, f"{{{GPX_NS}}}name").text = r[f"{prefix}_name"]
    ET.indent(gpx)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(gpx, encoding="unicode") + "\n"


# --- Lecture -----------------------------------------------------------------------------

def _decode(data):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")  # export Excel « CSV (séparateur : point-virgule) »


# « Amsterdam / Schiphol (AMS/EHAM) » : codes IATA et OACI entre parenthèses (l'un des deux peut manquer).
FR24_AIRPORT = re.compile(r"\(([A-Z0-9]{3})?/([A-Z0-9]{4})?\)\s*$")
TRAILING_CODES = re.compile(r"\s*\([^)]*\)\s*$")  # « Delta Air Lines (DL/DAL) » → « Delta Air Lines »
ISO_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
SLASH_DAY = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{2}|\d{4})\b")
# Horaires Flighty au format ISO (heure locale de l'aéroport), plus sûrs que la colonne Date (« 10/12/15 »).
FLIGHTY_TIMES = ("gate departure (scheduled)", "take off (scheduled)", "gate departure (actual)", "take off (actual)")
SAME_PLACE_KM = 50        # CDG à l'aller, ORY au retour : même ville
MAX_ROUND_TRIP_DAYS = 365


def slash_order(values):
    """« dmy » ou « mdy » pour les dates JJ/MM/AA ou MM/JJ/AA d'un fichier, d'après celles qui lèvent le doute."""
    for value in values:
        match = SLASH_DAY.match(value)
        if match and int(match.group(1)) > 12:
            return "dmy"
        if match and int(match.group(2)) > 12:
            return "mdy"
    return "mdy"  # Flighty et myFlightradar24 suivent l'usage américain


def flight_date(value, order):
    """Date d'un historique de vols au format AAAA-MM-JJ, ou None si elle est illisible."""
    if match := ISO_DAY.match(value):
        year, month, day = (int(g) for g in match.groups())
    elif match := SLASH_DAY.match(value):
        first, second, year = (int(g) for g in match.groups())
        day, month = (first, second) if order == "dmy" else (second, first)
        year += 2000 if year < 100 else 0
    else:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def flight_log_kind(fieldnames):
    """« flighty », « flightradar24 » ou None d'après les en-têtes du CSV."""
    names = {(f or "").strip().lower() for f in fieldnames}
    if not {"date", "from", "to"} <= names:
        return None
    if "flight number" in names:
        return "flightradar24"
    if {"airline", "flight"} <= names:
        return "flighty"
    return None


def flight_row(row, kind, order="mdy"):
    """Vol Flighty ou myFlightradar24 (clés en minuscules) → ligne au format de l'export ; None si annulé."""
    get = lambda key: row.get(key, "")  # noqa: E731
    dates = [get("date")]
    if kind == "flighty":
        if get("canceled").lower() == "true":
            return None
        dates = [get(key) for key in FLIGHTY_TIMES] + dates
        number, airline = get("airline") + get("flight"), ""
        aircraft, note = get("aircraft type name"), get("notes")
        codes = (get("from"), get("diverted to") or get("to"))
    else:
        number, airline = get("flight number"), TRAILING_CODES.sub("", get("airline"))
        aircraft, note = TRAILING_CODES.sub("", get("aircraft")), get("note")
        codes = tuple(m.group(1) or m.group(2) if (m := FR24_AIRPORT.search(v)) else v
                      for v in (get("from"), get("to")))
    depart = next((d for d in (flight_date(v, order) for v in dates if v) if d), get("date"))
    out = {"depart_date": depart, "transport_mode": "plane", "_errors": []}
    for prefix, code in zip(("origin", "dest"), codes):
        airport = find_airport(code)
        if airport is None:
            out[f"{prefix}_name"] = code
            out["_errors"].append(_("aéroport inconnu : « %(code)s »", code=code))
            continue
        out.update({f"{prefix}_name": place_name(airport), f"{prefix}_lat": str(airport["lat"]),
                    f"{prefix}_lon": str(airport["lon"]), f"{prefix}_country": airport["country"] or ""})
    details = " · ".join(p for p in (_("Vol %(number)s", number=number) if number else "", airline, aircraft) if p)
    out["notes"] = "\n".join(p for p in (details, note) if p)
    return out


def _near(a, prefix_a, b, prefix_b):
    return haversine_km(float(a[f"{prefix_a}_lat"]), float(a[f"{prefix_a}_lon"]),
                        float(b[f"{prefix_b}_lat"]), float(b[f"{prefix_b}_lon"])) <= SAME_PLACE_KM


def pair_round_trips(rows):
    """Réunit un vol X → Y et son vol retour Y → X en un trajet aller-retour.

    Les vols sont suivis dans l'ordre chronologique avec une pile des allers encore ouverts : un vol qui
    repart de la destination du dernier aller s'y empile (étape d'un circuit) ou le ferme s'il revient à
    son point de départ ; un vol qui part d'ailleurs (vol annulé ou absent de l'export) vide la pile.
    """
    usable = sorted((i for i, (_line, f) in enumerate(rows) if not f["_errors"] and ISO_DAY.match(f["depart_date"])),
                    key=lambda i: (rows[i][1]["depart_date"], i))
    stack, merged, returns = [], {}, set()
    for i in usable:
        flight = rows[i][1]
        if stack and not _near(flight, "origin", rows[stack[-1]][1], "dest"):
            stack.clear()
        if stack:
            out = rows[stack[-1]][1]
            gap = (date.fromisoformat(flight["depart_date"]) - date.fromisoformat(out["depart_date"])).days
            if _near(flight, "dest", out, "origin") and gap <= MAX_ROUND_TRIP_DAYS:
                notes = "\n".join(n for n in (
                    _("Aller : %(notes)s", notes=out["notes"]) if out["notes"] else "",
                    _("Retour : %(notes)s", notes=flight["notes"]) if flight["notes"] else "") if n)
                merged[stack.pop()] = dict(out, return_date=flight["depart_date"], notes=notes)
                returns.add(i)
                continue
        stack.append(i)
    return [(line, merged.get(i, flight)) for i, (line, flight) in enumerate(rows) if i not in returns]


def parse_csv(data):
    text = _decode(data)
    first_line = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=first_line.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    kind = flight_log_kind(reader.fieldnames or [])
    if kind is None and (not reader.fieldnames or not {"depart_date", "origin_name", "dest_name"} <= {
            (f or "").strip() for f in reader.fieldnames}):
        raise FileFormatError(_("En-têtes CSV manquants : depart_date, origin_name, dest_name… (exportez un fichier pour voir le format attendu)."))
    if kind:
        flights = [(reader.line_num, {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k})
                   for row in reader]
        order = slash_order(row.get("date", "") for _line, row in flights)
        return pair_round_trips([(line, flight) for line, row in flights
                                 if any(row.values()) and (flight := flight_row(row, kind, order)) is not None])
    rows = []
    for row in reader:
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
        if any(clean.values()):
            # Annule la protection anti-formule ajoutée à l'export.
            for key in TEXT_FIELDS & clean.keys():
                if clean[key][:1] == "'" and clean[key][1:2] in FORMULA_PREFIXES:
                    clean[key] = clean[key][1:]
            rows.append((reader.line_num, clean))
    return rows


def parse_geojson(data):
    try:
        doc = json.loads(_decode(data))
    except ValueError:
        raise FileFormatError(_("Fichier GeoJSON invalide.")) from None
    features = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(features, list):
        raise FileFormatError(_("Fichier GeoJSON invalide."))
    rows = []
    for index, feature in enumerate(features, start=1):
        props = dict(feature.get("properties") or {}) if isinstance(feature, dict) else {}
        coords = ((feature.get("geometry") or {}).get("coordinates") if isinstance(feature, dict) else None) or []
        if len(coords) >= 2 and all(isinstance(c, list) and len(c) >= 2 for c in (coords[0], coords[-1])):
            props.update(origin_lon=coords[0][0], origin_lat=coords[0][1],
                         dest_lon=coords[-1][0], dest_lat=coords[-1][1])
        # Listes de photos d'une sauvegarde complète (.zip) : conservées telles quelles.
        photos = {key: props.pop(key) for key in ("photos", "journey_photos") if isinstance(props.get(key), list)}
        row = {k: "" if v is None else str(v) for k, v in props.items()}
        row.update(photos)
        rows.append((index, row))
    return rows


def parse_gpx(data):
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise FileFormatError(_("Fichier GPX invalide."))
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise FileFormatError(_("Fichier GPX invalide.")) from None
    ns = {"g": root.tag[1:].split("}")[0] if root.tag.startswith("{") else "", "cv": EXT_NS}
    g = "g:" if ns["g"] else ""
    routes = root.findall(f"{g}rte", ns)
    if not routes:
        raise FileFormatError(_("Aucun itinéraire (<rte>) dans ce fichier GPX."))
    rows = []
    for index, rte in enumerate(routes, start=1):
        points = rte.findall(f"{g}rtept", ns)
        row = {}
        ext = rte.find(f"{g}extensions/cv:trip", ns)
        if ext is not None:
            for child in ext:
                row[child.tag.split("}")[-1]] = (child.text or "").strip()
        row.setdefault("transport_mode", (rte.findtext(f"{g}type", "", ns) or "").strip())
        row.setdefault("notes", (rte.findtext(f"{g}desc", "", ns) or "").strip())
        if len(points) >= 2:
            first, last = points[0], points[-1]
            row.update(origin_lat=first.get("lat", ""), origin_lon=first.get("lon", ""),
                       dest_lat=last.get("lat", ""), dest_lon=last.get("lon", ""))
            row.setdefault("origin_name", (first.findtext(f"{g}name", "", ns) or "").strip())
            row.setdefault("dest_name", (last.findtext(f"{g}name", "", ns) or "").strip())
            row.setdefault("depart_date", (first.findtext(f"{g}time", "", ns) or "")[:10])
        rows.append((index, row))
    return rows


PARSERS = {"csv": parse_csv, "geojson": parse_geojson, "gpx": parse_gpx}


def detect_format(filename, data):
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return "csv"
    if name.endswith((".geojson", ".json")):
        return "geojson"
    if name.endswith(".gpx"):
        return "gpx"
    head = data[:200].lstrip(b"\xef\xbb\xbf \r\n\t")
    if head.startswith(b"{"):
        return "geojson"
    if head.startswith(b"<"):
        return "gpx"
    return "csv"


# --- Validation --------------------------------------------------------------------------

def _float(value, low, high):
    number = float(str(value).replace(",", ".").strip())
    if not low <= number <= high:
        raise ValueError
    return number


def validate_record(raw):
    """Renvoie (valeurs propres, liste d'erreurs) pour une ligne lue."""
    errors, out = list(raw.get("_errors") or []), {}  # erreurs déjà relevées à la lecture (aéroport inconnu…)
    try:
        out["depart_date"] = date.fromisoformat(raw.get("depart_date", "").strip())
    except ValueError:
        errors.append(_("date de départ invalide : « %(value)s » (format attendu : AAAA-MM-JJ)",
                        value=raw.get("depart_date", "").strip()))
    ret = raw.get("return_date", "").strip()
    out["return_date"] = None
    if ret:
        try:
            out["return_date"] = date.fromisoformat(ret)
            if "depart_date" in out and out["return_date"] < out["depart_date"]:
                errors.append(_("la date de retour précède la date de départ"))
        except ValueError:
            errors.append(_("date de retour invalide (format attendu : AAAA-MM-JJ)"))
    mode = raw.get("transport_mode", "").strip().lower()
    if mode not in TRANSPORT_MODES:
        errors.append(_("mode de transport inconnu : « %(mode)s » (valeurs possibles : %(modes)s)",
                        mode=mode, modes=", ".join(TRANSPORT_MODES)))
    out["transport_mode"] = mode
    for prefix in ("origin", "dest"):
        name = raw.get(f"{prefix}_name", "").strip()
        if not name:
            errors.append(_("lieu de départ manquant") if prefix == "origin" else _("lieu d'arrivée manquant"))
        out[f"{prefix}_name"] = name
        try:
            out[f"{prefix}_lat"] = _float(raw.get(f"{prefix}_lat", ""), -90, 90)
            out[f"{prefix}_lon"] = _float(raw.get(f"{prefix}_lon", ""), -180, 180)
        except ValueError:
            if not raw.get("_errors"):
                errors.append(_("coordonnées invalides pour « %(place)s »", place=name or prefix))
        code = raw.get(f"{prefix}_country", "").strip().upper()
        out[f"{prefix}_country"] = code if len(code) == 2 and code.isalpha() else None
    for key in ("notes", "tags", "journey_key", "journey_name", "journey_notes"):
        out[key] = raw.get(key, "").strip() or None
    for key in ("photos", "journey_photos"):
        out[key] = [p for p in raw.get(key) or [] if isinstance(p, dict) and isinstance(p.get("file"), str)]
    for key, limit in LIMITS.items():
        if out.get(key) and len(out[key]) > limit:
            errors.append(_("champ %(field)s trop long (%(max)s caractères au maximum)", field=key, max=limit))
    return out, errors
