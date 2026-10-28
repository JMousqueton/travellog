"""Filtres partagés entre l'API JSON et les pages HTML."""
import unicodedata
from datetime import date

from flask_babel import gettext as _
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import Journey, Tag, Trip
from ..transport import TRANSPORT_MODES
from .. import utils

KINDS = ("all", "oneway", "round")
WHENS = ("all", "past", "upcoming")


class FilterError(ValueError):
    pass


def _parse_date(value, message):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise FilterError(message) from None


def parse_filters(args):
    """Lit from, to (AAAA-MM-JJ), modes (liste séparée par des virgules) et kind (all|oneway|round)."""
    start = _parse_date(args.get("from"), _("Date de début invalide (format attendu : AAAA-MM-JJ)."))
    end = _parse_date(args.get("to"), _("Date de fin invalide (format attendu : AAAA-MM-JJ)."))
    if start and end and start > end:
        raise FilterError(_("La date de début doit précéder la date de fin."))
    modes = [m for m in (args.get("modes") or "").split(",") if m]
    unknown = [m for m in modes if m not in TRANSPORT_MODES]
    if unknown:
        raise FilterError(_("Mode de transport inconnu : %(modes)s", modes=", ".join(unknown)))
    kind = args.get("kind") or "all"
    if kind not in KINDS:
        raise FilterError(_("Type de voyage inconnu : %(kind)s", kind=kind))
    try:
        tags = [int(t) for t in (args.get("tags") or "").split(",") if t]
    except ValueError:
        raise FilterError(_("Étiquettes invalides.")) from None
    when = args.get("when") or "all"
    if when not in WHENS:
        raise FilterError(_("Période inconnue : %(when)s", when=when))
    query = " ".join((args.get("q") or "").split())[:200]
    return {"start": start, "end": end, "modes": modes, "kind": kind, "when": when, "tags": tags, "q": query}


def trips_query(user, filters=None):
    filters = filters or {}
    # Charge voyages et étapes en deux requêtes au lieu d'une par trajet (sérialisation, liste).
    stmt = db.select(Trip).filter(Trip.user_id == user.id).options(
        selectinload(Trip.journey).selectinload(Journey.legs),
        selectinload(Trip.photos),
        selectinload(Trip.tags),
    )
    if filters.get("start"):
        stmt = stmt.filter(Trip.depart_date >= filters["start"])
    if filters.get("end"):
        stmt = stmt.filter(Trip.depart_date <= filters["end"])
    if filters.get("modes"):
        stmt = stmt.filter(Trip.transport_mode.in_(filters["modes"]))
    if filters.get("kind") == "oneway":
        stmt = stmt.filter(Trip.is_round_trip.is_(False))
    elif filters.get("kind") == "round":
        stmt = stmt.filter(Trip.is_round_trip.is_(True))
    if filters.get("tags"):
        # Trajets portant au moins une des étiquettes choisies.
        stmt = stmt.filter(Trip.tags.any(Tag.id.in_(filters["tags"])))
    # « Passés » comprend les voyages en cours (déjà commencés).
    if filters.get("when") == "upcoming":
        stmt = stmt.filter(Trip.depart_date > utils.today())
    elif filters.get("when") == "past":
        stmt = stmt.filter(Trip.depart_date <= utils.today())
    return stmt.order_by(Trip.depart_date.desc(), Trip.id.desc())


def normalize(text):
    """Minuscules sans accents : « Séville » et « seville » se retrouvent."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().casefold()


def search_text(trip, locale):
    from ..countries import country_name

    parts = [trip.origin_name, trip.dest_name, trip.notes, *(tag.name for tag in trip.tags),
             *(country_name(code, locale) for code in trip.countries)]
    if trip.journey:
        parts += [trip.journey.name, trip.journey.notes]
    return normalize(" ".join(p for p in parts if p))


def matches(trip, query, locale):
    """Chaque mot de la recherche doit apparaître (lieux, pays, notes, étiquettes, voyage)."""
    haystack = search_text(trip, locale)
    return all(word in haystack for word in normalize(query).split())


def list_trips(user, filters=None):
    trips = db.session.execute(trips_query(user, filters)).scalars().all()
    query = (filters or {}).get("q")
    if query:
        # Filtrage en Python : insensible aux accents (sans dépendre de l'extension unaccent).
        from ..i18n import current_locale

        locale = current_locale()
        trips = [trip for trip in trips if matches(trip, query, locale)]
    return trips


def shared_trips_for(link, filters=None):
    """Trajets d'un lien de partage : sans les voyages à venir, sauf si le lien les inclut."""
    filters = dict(filters or {})
    if not link.include_upcoming:
        if filters.get("when") == "upcoming":
            return []
        filters["when"] = "past"
    return list_trips(link.user, filters)
