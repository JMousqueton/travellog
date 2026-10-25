"""Jours d'absence : périodes passées loin du domicile, reconstituées à partir des déplacements.

On est absent dès qu'un trajet quitte la zone du domicile (rayon HOME_RADIUS_KM, pour que l'aéroport compte
comme le domicile) et jusqu'au trajet qui y ramène. Une absence qui commence ailleurs (trajet saisi depuis une
autre ville) s'arrête au retour dans cette ville. Un aller-retour produit deux déplacements (aller à la date
de départ, retour à la date de retour) ; les allers simples s'enchaînent (Paris → Lisbonne, puis Lisbonne → Paris).
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from .. import utils
from ..geo import haversine_km

HOME_RADIUS_KM = 30


@dataclass
class Absence:
    start: date
    end: date
    # Nuits passées dans chaque pays : [(première nuit, lendemain de la dernière nuit, code pays)]
    stays: list = field(default_factory=list)
    destinations: list = field(default_factory=list)
    ongoing: bool = False  # en cours aujourd'hui
    open: bool = False     # retour au domicile non renseigné : se termine au dernier déplacement connu
    last_trip: object = field(default=None, repr=False)
    # Point de départ quand l'absence ne commence pas au domicile (trajet saisi depuis une autre ville).
    anchor: tuple = field(default=None, repr=False)
    here: tuple = field(default=None, repr=False)  # dernier lieu atteint

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @property
    def nights(self):
        return (self.end - self.start).days

    def nights_abroad(self, home_country, year=None):
        total = 0
        for first, after_last, country in self.stays:
            if country and country == home_country:
                continue
            total += _overlap_nights(first, after_last, year)
        return total

    def days_in(self, year):
        start, end = max(self.start, date(year, 1, 1)), min(self.end, date(year, 12, 31))
        return max(0, (end - start).days + 1)


def covered_days(absences, year=None):
    """Nombre de jours distincts passés hors du domicile (un jour partagé par deux absences compte une fois)."""
    days = set()
    for absence in absences:
        for offset in range(absence.days):
            day = absence.start + timedelta(days=offset)
            if year is None or day.year == year:
                days.add(day)
    return len(days)


def _overlap_nights(first, after_last, year):
    if year is not None:
        first, after_last = max(first, date(year, 1, 1)), min(after_last, date(year + 1, 1, 1))
    return max(0, (after_last - first).days)


def _movements(trips, today):
    """(date, ordre, origine, destination, trajet) des déplacements déjà effectués, dans l'ordre."""
    moves = []
    for trip in trips:
        origin = (trip.origin_name, trip.origin_lat, trip.origin_lon, trip.origin_country)
        dest = (trip.dest_name, trip.dest_lat, trip.dest_lon, trip.dest_country)
        # Un même jour : d'abord les retours de voyages commencés avant, puis les départs, puis les retours
        # des allers-retours faits dans la journée (on rentre de Lyon le 3, puis on part pour Lisbonne le 3).
        if trip.depart_date <= today:
            moves.append((trip.depart_date, 1, trip.id, origin, dest, trip))
        if trip.is_round_trip and trip.return_date <= today:
            order = 2 if trip.return_date == trip.depart_date else 0
            moves.append((trip.return_date, order, trip.id, dest, origin, trip))
    return sorted(moves, key=lambda m: m[:3])


def compute_absences(user, trips):
    """Périodes d'absence de l'utilisateur, les plus anciennes d'abord. Vide sans domicile défini."""
    if not user.has_home:
        return []
    today = utils.today()

    def at_home(place):
        return haversine_km(user.home_lat, user.home_lon, place[1], place[2]) <= HOME_RADIUS_KM

    absences, current, since = [], None, None
    def near(a, b):
        return haversine_km(a[1], a[2], b[1], b[2]) <= HOME_RADIUS_KM

    for when, _order, _id, origin, dest, trip in _movements(trips, today):
        # Nouveau départ du domicile (on était donc rentré), ou trajet qui ne part pas du dernier lieu atteint
        # (déplacement non saisi entre les deux) : l'absence en cours s'arrête à son dernier trajet connu.
        if current is not None and (at_home(origin) or not near(origin, current.here)):
            current.open = True
            current.stays.append((since, current.end, current.destinations[-1][1]))
            absences.append(current)
            current = None
        if current is None:
            if at_home(dest):
                continue  # retour au domicile sans départ connu (données incomplètes)
            current = Absence(start=when, end=when, anchor=None if at_home(origin) else origin)
        else:
            current.stays.append((since, when, current.destinations[-1][1] if current.destinations else None))
        # Une absence commencée ailleurs se termine au retour dans sa ville de départ, mais pas dès le
        # premier trajet si celui-ci reste dans les environs (Nice -> Monaco).
        back_to_anchor = current.anchor is not None and current.destinations and near(dest, current.anchor)
        if at_home(dest) or back_to_anchor:
            # Retour au domicile, ou à la ville d'où partait une absence commencée ailleurs (le trajet
            # domicile -> cette ville n'a pas été saisi) : l'absence s'arrête là.
            current.end = when
            absences.append(current)
            current = None
            continue
        current.destinations.append((dest[0], dest[3]))
        current.end, since, current.here = when, when, dest
        current.last_trip = trip
    if current is not None:
        last = current.last_trip
        if last.is_round_trip and last.return_date > today:
            current.end, current.ongoing = today, True  # voyage en cours
        else:
            current.open = True  # pas de retour renseigné : on s'arrête au dernier déplacement
        current.stays.append((since, current.end, current.destinations[-1][1]))
        absences.append(current)
    return absences


def absence_summary(user, trips):
    """Totaux et détail par année : jours d'absence, part de l'année, nuits à l'étranger, plus longue absence."""
    absences = compute_absences(user, trips)
    if not absences:
        return None
    today = utils.today()
    years = sorted({y for a in absences for y in range(a.start.year, a.end.year + 1)}, reverse=True)
    per_year = []
    for year in years:
        elapsed = (min(today, date(year, 12, 31)) - date(year, 1, 1)).days + 1
        days = covered_days(absences, year)
        per_year.append({
            "year": year,
            "days": days,
            "share": days / elapsed if elapsed > 0 else 0,
            "nights_abroad": sum(a.nights_abroad(user.home_country, year) for a in absences),
            "absences": sum(1 for a in absences if a.days_in(year)),
        })
    return {
        "absences": absences[::-1],
        "days": covered_days(absences),
        "nights_abroad": sum(a.nights_abroad(user.home_country) for a in absences),
        "longest": max(absences, key=lambda a: (a.days, a.start)),
        "per_year": per_year,
        "by_year": {row["year"]: row for row in per_year},
        "open_count": sum(1 for a in absences if a.open),
    }
