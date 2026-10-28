"""Cartes Wallet (.pkpass, .pkpasses) : cartes d'embarquement d'Apple Wallet, jointes à un e-mail d'import ou
envoyées depuis la page Importer / exporter.

Un .pkpass est une archive zip dont pass.json décrit la carte. Les trajets d'une carte d'embarquement sont lus,
dans l'ordre :
- dans le code-barres d'une carte aérienne (format IATA BCBP : aéroports, compagnie, numéro et jour du vol) ;
- dans ses données « semantics » (codes d'aéroports ou gares, numéro, date de départ) ;
- dans ses champs affichés (codes d'aéroports, numéro de vol, date de la carte).
La signature de la carte n'est pas vérifiée : l'e-mail qui la porte est authentifié (DKIM), et un fichier
envoyé est relu dans l'aperçu de l'import.
"""
import io
import json
import re
import zipfile
from datetime import date, timedelta

from ..airports import find_airline_by_iata, find_airport
from .json_ld import ld_place
from .rows import airport_place, make_row

MAX_PASS_JSON = 512 * 1024      # pass.json décompressé (une carte en fait quelques Ko)
MAX_INNER_PASS = 10 * 1024 * 1024
MAX_PASSES = 20                 # cartes d'un .pkpasses
PASS_TYPES = ("application/vnd.apple.pkpass", "application/vnd.apple.pkpasses")
TRANSIT_MODES = {"PKTransitTypeAir": "plane", "PKTransitTypeTrain": "train", "PKTransitTypeBus": "bus",
                 "PKTransitTypeBoat": "boat"}
FIELD_GROUPS = ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields", "backFields")
ISO_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})")
FLIGHT_CODE = re.compile(r"^([A-Z]{2}|[A-Z][0-9]|[0-9][A-Z]) ?0*(\d{1,4}[A-Z]?)$")


class WalletError(ValueError):
    pass


def is_pass(filename, content_type=""):
    return content_type in PASS_TYPES or (filename or "").lower().endswith((".pkpass", ".pkpasses"))


def pass_documents(data, nested=False):
    """Contenu (pass.json) de chaque carte d'un .pkpass, ou d'un .pkpasses qui en regroupe plusieurs."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError):
        raise WalletError("carte Wallet illisible (archive zip invalide)") from None
    with archive:
        names = archive.namelist()
        if "pass.json" in names:
            return [_read_pass_json(archive)]
        inner = [n for n in names if n.lower().endswith(".pkpass")][:MAX_PASSES]
        if nested or not inner:
            raise WalletError("carte Wallet sans pass.json")
        documents = []
        for name in inner:
            if archive.getinfo(name).file_size <= MAX_INNER_PASS:
                documents.extend(pass_documents(archive.read(name), nested=True))
        return documents


def _read_pass_json(archive):
    if archive.getinfo("pass.json").file_size > MAX_PASS_JSON:
        raise WalletError("pass.json trop volumineux")
    try:
        document = json.loads(archive.read("pass.json").decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise WalletError("pass.json illisible") from None
    if not isinstance(document, dict):
        raise WalletError("pass.json illisible")
    return document


def pass_rows(data, ref, lang):
    """Trajets (lignes au format de l'export) des cartes d'embarquement d'un .pkpass ou .pkpasses."""
    return [row for document in pass_documents(data) for row in _document_rows(document, ref, lang)]


def _document_rows(document, ref, lang):
    boarding = document.get("boardingPass")
    if not isinstance(boarding, dict):
        return []  # billet d'événement, carte de fidélité…
    mode = TRANSIT_MODES.get(boarding.get("transitType"))
    if mode is None:
        return []
    semantics = document.get("semantics") if isinstance(document.get("semantics"), dict) else {}
    day = _iso_day(semantics.get("originalDepartureDate")) or _iso_day(semantics.get("currentDepartureDate")) \
        or _iso_day(document.get("relevantDate"))
    carrier = str(document.get("organizationName") or "").strip()
    if mode == "plane":
        for message in _barcode_messages(document):
            rows = [row for leg in parse_bcbp(message) if (row := _bcbp_row(leg, day or ref, carrier))]
            if rows:
                return rows
    row = _semantics_row(semantics, mode, day, carrier, lang) or _fields_row(boarding, mode, day, carrier)
    return [row] if row else []


def _iso_day(value):
    match = ISO_DAY.match(str(value or "").strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _barcode_messages(document):
    codes = document.get("barcodes") if isinstance(document.get("barcodes"), list) else []
    if isinstance(document.get("barcode"), dict):
        codes = codes + [document["barcode"]]
    return [str(code["message"]) for code in codes if isinstance(code, dict) and code.get("message")]


# --- Code-barres IATA BCBP (Resolution 792) ------------------------------------------------------

def parse_bcbp(message):
    """Vols d'un code-barres de carte d'embarquement : [{origin, dest, carrier, number, julian}].

    « M1DUPONT/JEAN        EABC123 CDGBCNAF 1148 072Y012A0042 100 » : format M, nombre de vols, nom (20),
    indicateur de billet électronique, puis pour chaque vol 35 caractères fixes (réservation, départ, arrivée,
    compagnie, numéro, jour de l'année, classe, siège, séquence, statut) suivis de la taille, en hexadécimal,
    de sa partie variable.
    """
    if len(message) < 60 or message[0] != "M" or not message[1].isdigit():
        return []
    legs, pos = [], 23
    for _index in range(int(message[1])):
        chunk = message[pos:pos + 35]
        if len(chunk) < 35:
            break
        origin, dest, carrier = chunk[7:10], chunk[10:13], chunk[13:16].strip()
        number, julian = chunk[16:21].strip(), chunk[21:24]
        if not (origin.isalpha() and dest.isalpha() and julian.isdigit() and 1 <= int(julian) <= 366):
            break
        match = re.fullmatch(r"0*(\d{1,4})([A-Z]?)", number)
        legs.append({"origin": origin, "dest": dest, "carrier": carrier,
                     "number": carrier + match.group(1) + match.group(2) if match and carrier else "",
                     "julian": int(julian)})
        try:
            pos += 37 + int(message[pos + 35:pos + 37], 16)
        except ValueError:
            break
    return legs


def julian_to_date(julian, ref):
    """Jour de l'année (sans année) le plus proche de la date de référence."""
    candidates = []
    for year in (ref.year - 1, ref.year, ref.year + 1):
        value = date(year, 1, 1) + timedelta(days=julian - 1)
        if value.year == year:
            candidates.append(value)
    return min(candidates, key=lambda value: abs(value - ref))


def _bcbp_row(leg, ref, organization):
    origin, dest = find_airport(leg["origin"]), find_airport(leg["dest"])
    if not origin or not dest or origin["iata"] == dest["iata"]:
        return None
    airline = find_airline_by_iata(leg["carrier"]) if len(leg["carrier"]) == 2 else None
    return make_row(julian_to_date(leg["julian"], ref).isoformat(), "plane", airport_place(origin),
                    airport_place(dest), carrier=(airline and airline["name"]) or organization, number=leg["number"])


# --- Données « semantics » et champs de la carte ------------------------------------------------

def _semantics_row(semantics, mode, day, carrier, lang):
    if not semantics or day is None:
        return None
    if mode == "plane":
        origin, dest = find_airport(semantics.get("departureAirportCode")), find_airport(semantics.get("arrivalAirportCode"))
        if not origin or not dest:
            return None
        code = str(semantics.get("airlineCode") or "").strip().upper()
        number = str(semantics.get("flightCode") or "").replace(" ", "").upper()
        if not number and code and semantics.get("flightNumber"):
            number = f"{code}{semantics['flightNumber']}"
        airline = find_airline_by_iata(code) if code else None
        return make_row(day.isoformat(), mode, airport_place(origin), airport_place(dest),
                        carrier=(airline and airline["name"]) or carrier, number=number)
    places = []
    for prefix in ("departure", "arrival"):
        location = semantics.get(f"{prefix}Location")
        node = {"name": semantics.get(f"{prefix}StationName") or semantics.get(f"{prefix}LocationDescription") or ""}
        if isinstance(location, dict):
            node["geo"] = location
        places.append(ld_place(node, lang) if node["name"] else None)
    if None in places:
        return None
    return make_row(day.isoformat(), mode, *places, carrier=str(semantics.get("transitProvider") or carrier),
                    number=str(semantics.get("vehicleNumber") or ""))


def _fields(boarding, groups=FIELD_GROUPS):
    for group in groups:
        for field in boarding.get(group) or []:
            if isinstance(field, dict):
                yield field


def _fields_row(boarding, mode, day, carrier):
    """Carte aérienne sans code-barres lisible ni « semantics » : codes d'aéroports des champs principaux
    (valeur « CDG » ou libellé « CDG » au-dessus d'une ville), numéro de vol et date des autres champs."""
    if mode != "plane":
        return None
    airports = []
    for field in _fields(boarding, ("primaryFields",)):
        for text in (field.get("value"), field.get("label")):
            airport = find_airport(str(text or "").strip()) if len(str(text or "").strip()) == 3 else None
            if airport:
                airports.append(airport)
                break
    number = ""
    for field in _fields(boarding):
        value = str(field.get("value") or "").strip().upper()
        if day is None and field.get("dateStyle"):
            day = _iso_day(value)
        match = FLIGHT_CODE.match(value)
        if not number and match and find_airline_by_iata(match.group(1)):
            number = match.group(1) + match.group(2)
    if len(airports) < 2 or day is None or airports[0]["iata"] == airports[1]["iata"]:
        return None
    airline = find_airline_by_iata(number[:2]) if number else None
    return make_row(day.isoformat(), "plane", airport_place(airports[0]), airport_place(airports[1]),
                    carrier=(airline and airline["name"]) or carrier, number=number)
