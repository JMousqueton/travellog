"""Import et export des voyages en CSV, GeoJSON et GPX.

Les trois formats portent les mêmes champs (FIELDS), si bien qu'un export peut être réimporté tel quel :
c'est aussi une sauvegarde (hors photos). Un aller-retour se reconnaît à la présence d'une date de retour ;
les trajets d'un même voyage partagent la même clé `journey_key`.
"""
import csv
import io
import json
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from flask_babel import gettext as _

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


def parse_csv(data):
    text = _decode(data)
    first_line = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=first_line.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames or not {"depart_date", "origin_name", "dest_name"} <= {
            (f or "").strip() for f in reader.fieldnames}:
        raise FileFormatError(_("En-têtes CSV manquants : depart_date, origin_name, dest_name… (exportez un fichier pour voir le format attendu)."))
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
    errors, out = [], {}
    try:
        out["depart_date"] = date.fromisoformat(raw.get("depart_date", "").strip())
    except ValueError:
        errors.append(_("date de départ invalide (format attendu : AAAA-MM-JJ)"))
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
