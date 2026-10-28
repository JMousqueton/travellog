"""Import de voyages par e-mail : `flask mail-import` relève la boîte IMAP (IMAP_SERVER…), toutes les 5 minutes
par cron.

Un e-mail n'est accepté que si son expéditeur (From) est un compte, ou une adresse d'import confirmée
d'un compte (ImportAddress), et que l'e-mail porte une signature DKIM
valide de ce domaine (sans elle, n'importe qui pourrait ajouter des trajets à un compte). Les trajets sont
lus d'abord dans les données schema.org (JSON-LD) que la plupart des compagnies et agences ajoutent à leurs
confirmations, sinon dans le texte : numéro de vol, codes d'aéroports et date.

- trajets trouvés : ajoutés au compte (sauf doublons), e-mail supprimé de la boîte ;
- rien de reconnu : ticket ouvert au nom du compte « Import Error » avec l'e-mail brut, e-mail laissé ;
- expéditeur inconnu ou non authentifié : e-mail ignoré et laissé.

Chaque e-mail est noté dans la table mail_imports : il n'est traité (et son ticket ouvert) qu'une fois.
"""
import email
import hashlib
import html
import imaplib
import json
import re
import ssl
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from flask import current_app
from sqlalchemy import func

from .airports import find_airline_by_iata, find_airport, place_name
from .extensions import db
from .models import ImportAddress, MailImport, Ticket, User
from .geo import haversine_km
from .transfer.formats import LIMITS, SAME_PLACE_KM, pair_round_trips, validate_record

MAX_RAW_CHARS = 100_000  # e-mail brut recopié dans le ticket (au-delà : tronqué)
REGION_CHARS = 600       # texte lu autour d'un numéro de vol pour y trouver aéroports et date


@dataclass
class Outcome:
    status: str                      # imported, failed, ignored ou done (déjà traité)
    delete: bool = False             # supprimer l'e-mail de la boîte
    reason: str = ""
    records: list = field(default_factory=list)


# --- Relève de la boîte ------------------------------------------------------------------------

def run(dry_run=False):
    """Traite chaque e-mail de la boîte ; renvoie le nombre d'e-mails par statut.
    En simulation (dry_run), rien n'est écrit ni supprimé et la boîte est ouverte en lecture seule."""
    cfg = current_app.config
    counts = {}
    conn = imaplib.IMAP4_SSL(cfg["IMAP_SERVER"], cfg["IMAP_PORT"], timeout=cfg["IMAP_TIMEOUT"],
                             ssl_context=ssl.create_default_context())
    with conn:
        conn.login(cfg["IMAP_USERNAME"], cfg["IMAP_PASSWORD"])
        conn.select(cfg["IMAP_FOLDER"], readonly=dry_run)
        _typ, data = conn.uid("SEARCH", None, "ALL")
        deleted = []
        for uid in data[0].split():
            outcome = _process_uid(conn, uid, dry_run)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            if dry_run:
                current_app.logger.info("E-mail %s : %s %s %s", uid.decode(), outcome.status, outcome.reason,
                                        [_summary(r) for r in outcome.records])
            elif outcome.delete:
                conn.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
                deleted.append(uid)
        if deleted:
            if "UIDPLUS" in conn.capabilities:
                conn.uid("EXPUNGE", b",".join(deleted))
            else:
                conn.expunge()
    return counts


def _summary(record):
    return f"{record['depart_date']} {record['origin_name']} → {record['dest_name']} ({record['transport_mode']})"


def _fetch(conn, uid, what):
    _typ, parts = conn.uid("FETCH", uid, f"(BODY.PEEK[{what}])")
    return next((p[1] for p in parts or [] if isinstance(p, tuple)), b"")


def _process_uid(conn, uid, dry_run):
    # L'en-tête suffit pour reconnaître un e-mail déjà traité, sans retélécharger ses pièces jointes.
    header = email.message_from_bytes(_fetch(conn, uid, "HEADER.FIELDS (MESSAGE-ID)"), policy=policy.default)
    key = _key(header.get("Message-ID"), None)
    if key is not None:
        done = db.session.execute(db.select(MailImport).filter_by(message_key=key)).scalar_one_or_none()
        if done is not None:  # e-mail importé dont la suppression avait échoué : on le supprime maintenant
            return Outcome("done", delete=done.status == "imported")
    return process(_fetch(conn, uid, ""), dry_run=dry_run)


def _key(message_id, raw):
    if message_id and message_id.strip():
        return hashlib.sha256(b"mid:" + message_id.strip().encode("utf-8", "replace")).hexdigest()
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


# --- Traitement d'un e-mail --------------------------------------------------------------------

def process(raw, dry_run=False):
    msg = email.message_from_bytes(raw, policy=policy.default)
    key = _key(msg.get("Message-ID"), raw)
    done = db.session.execute(db.select(MailImport).filter_by(message_key=key)).scalar_one_or_none()
    if done is not None:
        return Outcome("done", delete=done.status == "imported")

    sender = parseaddr(str(msg.get("From", "")))[1].strip().lower()
    subject = str(msg.get("Subject", "")).strip()
    user = account_for(sender)
    if not sender or user is None or user.email == current_app.config["MAIL_IMPORT_ERROR_EMAIL"]:
        return _finish(Outcome("ignored", reason="expéditeur inconnu"), key, sender, subject, None, dry_run)
    if current_app.config["MAIL_IMPORT_REQUIRE_DKIM"] and not dkim_aligned(raw, sender.rpartition("@")[2]):
        return _finish(Outcome("ignored", reason="signature DKIM absente, invalide ou d'un autre domaine"),
                       key, sender, subject, user, dry_run)

    try:
        records, problems = extract_trips(msg, user.locale)
    except Exception as exc:  # e-mail inattendu : traité comme un échec (un ticket, une fois)
        current_app.logger.exception("Lecture de l'e-mail %s impossible", key)
        records, problems = [], [f"erreur interne : {exc!r}"]
    if not records:
        reason = "; ".join(problems) or "aucun trajet reconnu dans l'e-mail"
        outcome = Outcome("failed", reason=reason[:255])
    else:
        outcome = Outcome("imported", delete=True, records=records)
    if dry_run:
        return outcome

    entry = None
    if outcome.status == "imported":
        entry = _save_trips(user, records)
    else:
        entry = _open_ticket(raw, sender, subject, user, outcome.reason)
    return _finish(outcome, key, sender, subject, user, dry_run, **entry)


def account_for(sender):
    """Compte de l'expéditeur : celui dont c'est l'adresse, ou à qui elle est confirmée comme adresse d'import."""
    user = db.session.execute(db.select(User).filter(func.lower(User.email) == sender)).scalar_one_or_none()
    if user is None:
        address = db.session.execute(db.select(ImportAddress).filter_by(email=sender)).scalar_one_or_none()
        user = address.user if address else None
    return user


def _finish(outcome, key, sender, subject, user, dry_run, added=(), duplicates=(), ticket=None):
    if dry_run:
        return outcome
    db.session.add(MailImport(message_key=key, status=outcome.status, sender=sender[:255] or None,
                              subject=subject[:200] or None, reason=outcome.reason[:255] or None,
                              trip_count=len(added), user_id=user.id if user else None,
                              ticket_id=ticket.id if ticket else None))
    db.session.commit()
    if outcome.status in ("imported", "failed"):
        # Lancé par cron, hors requête : les liens sont construits sur l'adresse publique.
        with current_app.test_request_context(base_url=current_app.config["APP_BASE_URL"] or None):
            if ticket is not None:
                from .support.notify import notify_staff

                notify_staff(ticket, ticket.messages[0])
            _reply(sender, subject, user, added, duplicates, failed=ticket is not None)
    return outcome


def _reply(sender, subject, user, added, duplicates, failed):
    """Compte rendu à l'expéditeur, dans la langue du compte : trajets ajoutés, déjà enregistrés, ou e-mail
    transmis à l'équipe pour un import manuel. Jamais aux expéditeurs ignorés (pas de rétrodiffusion)."""
    from flask import render_template
    from flask_babel import force_locale
    from flask_babel import gettext as _

    from .auth.routes import _external_url
    from .mail import send_email

    with force_locale(user.locale):
        if failed:
            title = _("Import impossible : %(subject)s", subject=subject)
        elif added:
            title = _("Voyages importés : %(subject)s", subject=subject)
        else:
            title = _("Voyages déjà enregistrés : %(subject)s", subject=subject)
        body = render_template("mail_import/result.txt", subject=subject, failed=failed,
                               added=[_trip_line(r) for r in added], duplicates=[_trip_line(r) for r in duplicates],
                               url=_external_url("trips.list_view"), site=current_app.config["SITE_NAME"])
    send_email(sender, title[:200], body, headers={"Auto-Submitted": "auto-replied"})


def _trip_line(record):
    """« 10 nov. 2026 → 10 nov. 2026 · CDG ⇄ MUC · AF1722 / AF1823 » dans la langue active."""
    from flask_babel import format_date

    from .trips.stats import short_place

    days = format_date(record["depart_date"], "medium")
    if record["return_date"] and record["return_date"] != record["depart_date"]:
        days += " → " + format_date(record["return_date"], "medium")
    arrow = " ⇄ " if record["return_date"] else " → "
    parts = [days, short_place(record["origin_name"]) + arrow + short_place(record["dest_name"])]
    return " · ".join(parts + [v for v in (record["service_number"], record["carrier"]) if v])


def _legs(trip):
    """Sens effectués [(mode, date, (lat, lon) de départ, d'arrivée)] d'un trajet ou d'une ligne validée."""
    get = trip.get if isinstance(trip, dict) else lambda key: getattr(trip, key)
    origin, dest = (get("origin_lat"), get("origin_lon")), (get("dest_lat"), get("dest_lon"))
    legs = [(get("transport_mode"), get("depart_date"), origin, dest)]
    if get("return_date"):
        legs.append((get("transport_mode"), get("return_date"), dest, origin))
    return legs


def _same_leg(a, b):
    return (a[0] == b[0] and a[1] == b[1] and haversine_km(*a[2], *b[2]) <= SAME_PLACE_KM
            and haversine_km(*a[3], *b[3]) <= SAME_PLACE_KM)


def _save_trips(user, records):
    """Ajoute les trajets, sauf ceux dont un sens est déjà enregistré (même mode, même jour, mêmes lieux à
    SAME_PLACE_KM près, aller ou retour d'un aller-retour compris) : l'import est quand même réussi."""
    from .transfer.routes import new_trip

    existing = [leg for trip in user.trips for leg in _legs(trip)]
    added, duplicates = [], []
    for record in records:
        legs = _legs(record)
        if any(_same_leg(leg, known) for leg in legs for known in existing):
            duplicates.append(record)
            continue
        existing.extend(legs)
        db.session.add(new_trip(user, record))
        added.append(record)
    db.session.flush()
    return {"added": added, "duplicates": duplicates}


def import_error_account():
    """Compte « Import Error » qui ouvre les tickets d'échec. Il ne peut pas se connecter (mot de passe
    inutilisable) et son adresse en .invalid ne reçoit rien."""
    address = current_app.config["MAIL_IMPORT_ERROR_EMAIL"]
    account = db.session.execute(db.select(User).filter_by(email=address)).scalar_one_or_none()
    if account is None:
        account = User(email=address, password_hash="!", ticket_emails=False)
        db.session.add(account)
        db.session.flush()
    return account


def _open_ticket(raw, sender, subject, user, reason):
    account = import_error_account()
    text = raw.decode("utf-8", "replace")
    if len(text) > MAX_RAW_CHARS:
        text = text[:MAX_RAW_CHARS] + f"\n[… e-mail tronqué : {len(raw)} octets au total]"
    body = (f"Import par e-mail impossible : {reason}\n\n"
            f"Expéditeur : {sender}\nCompte : {user.email} (n° {user.id})\nObjet : {subject}\n\n"
            f"--- E-mail brut ---\n{text}")
    ticket = Ticket(user_id=account.id, subject=f"Import Error : {subject or '(sans objet)'}"[:200], notify=False)
    db.session.add(ticket)
    ticket.add_message(account, body, from_staff=False)
    db.session.flush()
    return {"ticket": ticket}


# --- Authentification de l'expéditeur ----------------------------------------------------------

def dkim_aligned(raw, domain, dnsfunc=None):
    """Vrai si une signature DKIM valide de l'e-mail vient du domaine de l'expéditeur (ou d'un domaine parent
    ou enfant : alignement « relaxed » de DMARC). Les clés publiques sont lues dans le DNS (ou par dnsfunc)."""
    import dkim

    verifier = dkim.DKIM(raw, logger=current_app.logger, minkey=1024)
    signatures = len(re.findall(rb"^DKIM-Signature:", raw, flags=re.I | re.M))
    for index in range(signatures):
        try:
            if not verifier.verify(idx=index, **({"dnsfunc": dnsfunc} if dnsfunc else {})):
                continue
        except Exception:  # signature mal formée, DNS injoignable…
            continue
        signer = (verifier.domain or b"").decode("ascii", "replace").lower()
        if signer and (signer == domain or domain.endswith("." + signer) or signer.endswith("." + domain)):
            return True
    return False


# --- Lecture des trajets -----------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Texte d'une page HTML, un bloc (cellule, paragraphe…) par ligne."""

    BLOCKS = {"br", "p", "div", "tr", "td", "th", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def text(self):
        lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def html_to_text(markup):
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return parser.text()


def _bodies(msg):
    """(textes, pages HTML) de l'e-mail, y compris ceux d'un e-mail transféré en pièce jointe."""
    texts, pages = [], []
    for part in msg.walk():
        if part.is_multipart() or part.get_content_maintype() != "text":
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):  # jeu de caractères inconnu
            content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if part.get_content_subtype() == "html":
            pages.append(content)
        elif part.get_content_subtype() == "plain":
            texts.append(content)
    return texts, pages


def _reference_date(msg):
    try:
        return parsedate_to_datetime(str(msg.get("Date"))).date()
    except (TypeError, ValueError):
        return date.today()


def extract_trips(msg, lang):
    """(trajets validés, problèmes) d'un e-mail ; les trajets sont au format de validate_record."""
    texts, pages = _bodies(msg)
    ref = _reference_date(msg)
    rows = [r for page in pages for r in _json_ld_rows(page, lang)]
    if not rows:
        # Le texte tiré du HTML garde la structure (une cellule par ligne) ; le texte brut sert de secours.
        for text in [html_to_text(p) for p in pages] + texts:
            rows = _text_rows(text, ref)
            if rows:
                break
    unique = {}
    for row in rows:
        unique.setdefault((row["transport_mode"], row["origin_name"], row["dest_name"], row["depart_date"]), row)
    paired = pair_round_trips(list(enumerate(unique.values())))
    records, problems = [], []
    for _line, raw in paired:
        record, errors = validate_record(raw)
        if errors:
            problems.extend(str(e) for e in errors)
        else:
            records.append(record)
    return records, problems


# JSON-LD schema.org (https://developers.google.com/gmail/markup/reference) ---------------------

LD_JSON = re.compile(r"<script[^>]*type=[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script>", re.S | re.I)
# type de trajet schema.org → (mode, lieu de départ, lieu d'arrivée, numéro)
LD_TRIPS = {
    "Flight": ("plane", "departureAirport", "arrivalAirport", "flightNumber"),
    "TrainTrip": ("train", "departureStation", "arrivalStation", "trainNumber"),
    "BusTrip": ("bus", "departureBusStop", "arrivalBusStop", "busNumber"),
    "BoatTrip": ("boat", "departureBoatTerminal", "arrivalBoatTerminal", None),
}


def _ld_nodes(node):
    if isinstance(node, list):
        for item in node:
            yield from _ld_nodes(item)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from _ld_nodes(node["@graph"])


def _ld_types(node):
    types = node.get("@type") if isinstance(node, dict) else None
    return [str(t).rpartition("/")[2] for t in (types if isinstance(types, list) else [types]) if t]


def _json_ld_rows(page, lang):
    rows = []
    for block in LD_JSON.findall(page):
        try:
            data = json.loads(html.unescape(block) if "&quot;" in block else block)
        except ValueError:
            continue
        for node in _ld_nodes(data):
            if not any(t.endswith("Reservation") for t in _ld_types(node)):
                continue
            targets = node.get("reservationFor")
            for trip in targets if isinstance(targets, list) else [targets]:
                row = _ld_row(trip, lang)
                if row:
                    rows.append(row)
    return rows


def _ld_row(trip, lang):
    kind = next((LD_TRIPS[t] for t in _ld_types(trip) if t in LD_TRIPS), None)
    if kind is None:
        return None
    mode, origin_key, dest_key, number_key = kind
    day = str(trip.get("departureTime") or trip.get("departureDay") or "")[:10]
    places = [_ld_place(trip.get(origin_key), lang), _ld_place(trip.get(dest_key), lang)]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day) or None in places:
        return None
    carrier, number = "", str(trip.get(number_key) or "").strip() if number_key else ""
    if mode == "plane":
        airline = trip.get("airline") or {}
        code = str(airline.get("iataCode") or "").strip().upper() if isinstance(airline, dict) else ""
        known = find_airline_by_iata(code) if code else None
        carrier = (known and known["name"]) or (airline.get("name") if isinstance(airline, dict) else str(airline))
        if number and number.isdigit() and code:
            number = code + number
    else:
        provider = trip.get("provider") or trip.get("trainCompany") or {}
        carrier = provider.get("name", "") if isinstance(provider, dict) else str(provider)
    return _row(day, mode, *places, carrier=carrier, number=number)


def _ld_place(node, lang):
    """{name, lat, lon, country} d'un aéroport, d'une gare ou d'un arrêt ; None si introuvable."""
    if isinstance(node, str):
        node = {"name": node}
    if not isinstance(node, dict):
        return None
    for code in (node.get("iataCode"), node.get("icaoCode")):
        airport = find_airport(code) if code else None
        if airport:
            return _airport_place(airport)
    name = str(node.get("name") or "").strip()
    geo = node.get("geo") if isinstance(node.get("geo"), dict) else {}
    try:
        return {"name": name, "lat": float(geo["latitude"]), "lon": float(geo["longitude"]), "country": ""}
    except (KeyError, TypeError, ValueError):
        pass
    if not name:
        return None
    from .geo import geocode

    try:
        found = geocode(name, lang)
    except Exception:  # Nominatim injoignable : l'e-mail finira en ticket
        current_app.logger.warning("Géocodage impossible pour « %s »", name, exc_info=True)
        return None
    if not found:
        return None
    return {"name": name, "lat": found[0]["lat"], "lon": found[0]["lon"], "country": found[0].get("country_code") or ""}


def _airport_place(airport):
    return {"name": place_name(airport), "lat": airport["lat"], "lon": airport["lon"], "country": airport["country"] or ""}


def _row(day, mode, origin, dest, carrier="", number=""):
    """Ligne au format de l'export (valeurs texte), comme les imports de fichiers."""
    out = {"depart_date": day, "transport_mode": mode, "_errors": [], "notes": "", "vehicle": "",
           "carrier": (carrier or "")[:LIMITS["carrier"]], "service_number": (number or "")[:LIMITS["service_number"]]}
    for prefix, place in (("origin", origin), ("dest", dest)):
        out.update({f"{prefix}_name": place["name"][:LIMITS[f"{prefix}_name"]], f"{prefix}_lat": str(place["lat"]),
                    f"{prefix}_lon": str(place["lon"]), f"{prefix}_country": place["country"]})
    return out


# Texte : numéros de vol, codes d'aéroports et dates ---------------------------------------------

FLIGHT_NUMBER = re.compile(r"\b([A-Z]{2}|[A-Z][0-9]|[0-9][A-Z]) ?(\d{1,4})\b")
# « Paris (CDG) », un code seul dans sa cellule, ou une paire « CDG → BCN ».
AIRPORT_CODES = [re.compile(r"\(([A-Z]{3})\)"), re.compile(r"^\s*([A-Z]{3})\s*$", re.M)]
AIRPORT_PAIR = re.compile(r"\b([A-Z]{3}) ?(?:→|⇒|➔|->|>|–|—|-|/|to|à|nach) ?([A-Z]{3})\b")

MONTHS = {}
for number, names in enumerate((
    "january jan janvier janv enero ene januar gennaio gen",
    "february feb fevrier fevr fev febrero februar febbraio",
    "march mar mars marzo marz maerz",
    "april apr avril avr abril abr aprile",
    "may mai mayo maggio mag",
    "june jun juin junio juni giugno giu",
    "july jul juillet juil julio juli luglio lug",
    "august aug aout agosto ago",
    "september sept sep septembre septiembre setiembre settembre set",
    "october oct octobre octubre oktober okt ottobre ott",
    "november nov novembre noviembre",
    "december dec decembre diciembre dic dezember dez dicembre",
), start=1):
    for name in names.split():
        MONTHS[name] = number
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = [
    ("ymd", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?=[T ]\d|\b)")),
    ("num", re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})\b")),
    # « 12 mars 2026 », « 1er avril », « 12MAR26 » (année sur deux chiffres seulement collée au mois).
    ("dmy", re.compile(rf"\b(\d{{1,2}})(?:er|st|nd|rd|th|\.)? ?(?:de )?({_MONTH})(?![a-z])\.?"
                       rf"(?:(\d{{2}})(?!\d)|,? ?(?:de )?(\d{{4}})(?!\d))?", re.I)),
    ("mdy", re.compile(rf"\b({_MONTH})(?![a-z])\.? (\d{{1,2}})(?:st|nd|rd|th)?(?!\d)(?:,? (\d{{4}})(?!\d))?", re.I)),
]


def _ascii(text):
    """Accents retirés caractère par caractère (les positions restent celles du texte d'origine)."""
    return "".join(unicodedata.normalize("NFKD", c)[0] if c.strip() else " " for c in text)


def find_dates(text, ref):
    """[(position, date)] des dates du texte. Une date sans année est la plus proche après l'e-mail
    (un mois plus tôt au plus : un e-mail transféré après le départ)."""
    plain = _ascii(text)
    order = _numeric_order([m.groups() for m in DATE_PATTERNS[1][1].finditer(plain)])
    found, taken = [], []
    for kind, pattern in DATE_PATTERNS:
        for match in pattern.finditer(plain):
            if any(start < match.end() and match.start() < end for start, end in taken):
                continue
            groups = match.groups()
            if kind == "ymd":
                year, month, day = groups
            elif kind == "num":
                day, month, year = groups if order == "dmy" else (groups[1], groups[0], groups[2])
            elif kind == "dmy":
                day, month, year = groups[0], MONTHS[groups[1].lower()], groups[2] or groups[3]
            else:
                month, day, year = MONTHS[groups[0].lower()], groups[1], groups[2]
            value = _make_date(year, month, day, ref)
            if value is not None:
                found.append((match.start(), value))
                taken.append(match.span())
    return sorted(found)


def _numeric_order(dates):
    """« dmy » ou « mdy » pour les dates JJ/MM/AAAA d'un e-mail, d'après celles qui lèvent le doute
    (jour d'abord par défaut, l'usage le plus courant hors des États-Unis)."""
    for first, second, _year in dates:
        if int(second) > 12:
            return "mdy"
        if int(first) > 12:
            return "dmy"
    return "dmy"


def _make_date(year, month, day, ref):
    try:
        if year:
            year = int(year) + (2000 if len(str(year)) == 2 else 0)
            value = date(year, int(month), int(day))
        else:
            value = date(ref.year, int(month), int(day))
            if value < ref - timedelta(days=31):
                value = date(ref.year + 1, int(month), int(day))
    except ValueError:
        return None
    return value if date(1950, 1, 1) <= value <= ref + timedelta(days=2 * 366) else None


def _airport_codes(text):
    """[(position, aéroport)] des codes d'aéroports connus, dans l'ordre du texte."""
    found = {}
    for pattern in AIRPORT_CODES:
        for match in pattern.finditer(text):
            found.setdefault(match.start(1), match.group(1))
    for match in AIRPORT_PAIR.finditer(text):
        found.setdefault(match.start(1), match.group(1))
        found.setdefault(match.start(2), match.group(2))
    return [(pos, airport) for pos, code in sorted(found.items()) if (airport := find_airport(code))]


# En-tête d'un e-mail transféré (« From: … / Sent: … / Subject: … », en cinq langues) : sa date est celle du
# transfert et son objet répète l'itinéraire ; il est effacé avant la lecture.
FORWARD_FIELD = re.compile(r"^[ >*]*(from|sent|date|to|cc|subject|de|envoy[ée]|le|[àa]|objet|von|gesendet|an|"
                           r"betreff|datum|enviado|para|asunto|fecha|da|inviato|data|oggetto)\s*:", re.I)
FORWARD_SENDER = {"from", "de", "von", "da"}


def strip_forward_headers(text):
    """Remplace par des espaces (les positions ne changent pas) chaque bloc d'au moins deux lignes d'en-tête
    consécutives qui commence par l'expéditeur."""
    lines = text.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        j = i
        while j < len(lines) and FORWARD_FIELD.match(lines[j]):
            j += 1
        block = lines[i:j]
        if len(block) >= 2 and FORWARD_FIELD.match(block[0]).group(1).lower() in FORWARD_SENDER:
            out.extend(re.sub(r"[^\n]", " ", line) for line in block)
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "".join(out)


def _text_rows(text, ref):
    """Vols du texte : chaque numéro de vol avec les deux premiers aéroports et la première date de sa zone.
    La zone est d'abord ce qui suit le numéro (jusqu'au suivant) ; à défaut, ce qui le précède (aéroports
    écrits avant le numéro). Un numéro cité plusieurs fois (résumé, puis détail) ne donne qu'un vol."""
    text = strip_forward_headers(text)
    codes, dates = _airport_codes(text), find_dates(text, ref)
    numbers = [(m.start(), m.end(), airline, m.group(1) + str(int(m.group(2))))
               for m in FLIGHT_NUMBER.finditer(text) if (airline := find_airline_by_iata(m.group(1)))]
    numbers = [n for n in numbers if any(n[0] - REGION_CHARS <= pos <= n[1] + REGION_CHARS for pos, _a in codes)]
    if numbers:
        found = {}  # numéro → (zone suivante ?, ligne)
        for i, (start, end, airline, number) in enumerate(numbers):
            after = _flight_in(codes, dates, start, numbers[i + 1][0] if i + 1 < len(numbers) else end + REGION_CHARS,
                               start, airline["name"], number)
            row = after or _flight_in(codes, dates, numbers[i - 1][1] if i else max(0, start - REGION_CHARS), end,
                                      start, airline["name"], number)
            if row and (number not in found or (after and not found[number][0])):
                found[number] = (bool(after), row)
        return [row for _after, row in found.values()]
    rows = []
    for match in AIRPORT_PAIR.finditer(text):  # sans numéro de vol : paires « CDG → BCN »
        origin, dest = find_airport(match.group(1)), find_airport(match.group(2))
        if origin and dest:
            row = _flight_in([(match.start(1), origin), (match.start(2), dest)], dates,
                             match.start(), match.end() + REGION_CHARS, match.start())
            if row:
                rows.append(row)
    return rows


def _flight_in(codes, dates, low, high, anchor, carrier="", number=""):
    airports = []
    for pos, airport in codes:
        if low <= pos <= high and (not airports or airports[-1]["iata"] != airport["iata"]):
            airports.append(airport)
    day = next((d for pos, d in dates if low <= pos <= high), None)
    if day is None:  # date écrite avant la zone (en tête de l'e-mail, par exemple)
        near = [(abs(pos - anchor), d) for pos, d in dates if abs(pos - anchor) <= REGION_CHARS]
        day = min(near)[1] if near else None
    if len(airports) < 2 or day is None:
        return None
    return _row(day.isoformat(), "plane", _airport_place(airports[0]), _airport_place(airports[1]),
                carrier=carrier, number=number)
