"""Calendrier d'une année, façon GitHub : une case par jour, colorée selon qu'on voyage ce jour-là, qu'on est
loin de chez soi ou qu'on est à la maison.

Les jours loin de chez soi viennent des absences (domicile défini) ; sans domicile, de la durée des allers-retours.
Les voyages à venir apparaissent aussi, estompés.
"""
from datetime import date, timedelta

from babel import Locale
from babel.dates import get_day_names, get_month_names
from flask_babel import gettext as _

from .. import utils
from ..i18n import current_locale, format_day

HOME, AWAY, TRAVEL = 0, 1, 2


def _days(start, end, first, last):
    """Jours de start à end (inclus), limités à l'intervalle [first, last]."""
    day, end = max(start, first), min(end, last)
    while day <= end:
        yield day
        day += timedelta(days=1)


def year_calendar(trips, year, absences=None):
    """Semaines de l'année (listes de 7 cases, None hors de l'année), mois, jours de la semaine et totaux.

    `absences` : absences calculées depuis le domicile (voir absences.py), ou None pour se baser sur les
    allers-retours.
    """
    first, last = date(year, 1, 1), date(year, 12, 31)
    today = utils.today()
    cells = {}

    def mark(day, level, label, upcoming):
        cell = cells.setdefault(day, {"level": HOME, "labels": [], "upcoming": True})
        cell["level"] = max(cell["level"], level)
        if label not in cell["labels"]:
            cell["labels"].append(label)
        cell["upcoming"] = cell["upcoming"] and upcoming

    if absences:
        for absence in absences:
            places = ", ".join(dict.fromkeys(name for name, _country in absence.destinations))
            for day in _days(absence.start, absence.end, first, last):
                mark(day, AWAY, places, False)
    # Allers-retours : sans domicile, ce sont les seules absences connues ; avec, seuls ceux à venir s'ajoutent
    # (les absences ne couvrent que le passé).
    for trip in trips:
        if trip.is_round_trip and trip.return_date and (not absences or trip.depart_date > today):
            for day in _days(trip.depart_date, trip.return_date, first, last):
                mark(day, AWAY, trip.dest_name, day > today)
    for trip in trips:
        moves = [(trip.depart_date, trip.origin_name, trip.dest_name)]
        if trip.is_round_trip and trip.return_date:
            moves.append((trip.return_date, trip.dest_name, trip.origin_name))
        for when, origin, dest in moves:
            if first <= when <= last:
                mark(when, TRAVEL, f"{origin} → {dest}", when > today)

    locale = current_locale()
    week_start = Locale.parse(locale).first_week_day  # 0 = lundi
    offset = (first.weekday() - week_start) % 7
    weeks, months, column = [], [], [None] * offset
    month_names = get_month_names("abbreviated", locale=locale)
    states = {TRAVEL: _("Jour de voyage"), AWAY: _("Loin de chez moi"), HOME: _("À la maison")}
    for day in _days(first, last, first, last):
        if len(column) == 7:
            weeks.append(column)
            column = []
        if day.day == 1:
            months.append({"week": len(weeks), "name": month_names[day.month]})
        cell = cells.get(day) or {"level": HOME, "labels": [], "upcoming": False}
        parts = [format_day(day)]
        if cell["level"] != HOME or day <= today:
            parts.append(states[cell["level"]])
        column.append({
            "date": day,
            "level": cell["level"],
            "upcoming": cell["upcoming"],
            "future": day > today,
            "today": day == today,
            "title": " · ".join(parts + cell["labels"]),
        })
    weeks.append(column + [None] * (7 - len(column)))

    day_names = get_day_names("abbreviated", locale=locale)
    weekdays = [day_names[(week_start + i) % 7] for i in range(7)]
    past = [c for week in weeks for c in week if c and not c["future"]]
    return {
        "year": year,
        "weeks": weeks,
        "months": months,
        "weekdays": weekdays,
        "travel_days": sum(1 for c in past if c["level"] == TRAVEL),
        "away_days": sum(1 for c in past if c["level"] >= AWAY),
        "planned_days": sum(1 for week in weeks for c in week if c and c["future"] and c["level"] >= AWAY),
        "from_absences": bool(absences),
    }
