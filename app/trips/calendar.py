"""Vue calendrier de « Mes voyages » : un mois, semaine par semaine, chaque trajet ou voyage en barre du départ au
retour (Premium).

Les voyages (trajets regroupés) forment une seule barre, du premier départ au dernier retour ; les trajets isolés
prennent la couleur de leur mode de transport. Dans chaque semaine, les barres sont rangées sur des lignes
(« couloirs ») pour ne pas se chevaucher.
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from babel import Locale
from babel.dates import get_day_names
from flask import url_for

from ..i18n import current_locale
from ..transport import TRANSPORT_MODES
from .. import utils

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
JOURNEY_COLOR, JOURNEY_COLOR_DARK = "#0f766e", "#2dd4bf"  # distinct des couleurs des modes


def parse_month(value):
    """« AAAA-MM » → premier jour du mois ; mois courant si absent ou invalide."""
    match = MONTH_RE.match(value or "")
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1900 <= year <= 2100 and 1 <= month <= 12:
            return date(year, month, 1)
    return utils.today().replace(day=1)


def shift_month(first, delta):
    index = first.year * 12 + first.month - 1 + delta
    return date(index // 12, index % 12 + 1, 1)


@dataclass
class Item:
    """Un trajet isolé ou un voyage, du départ au retour."""
    start: date
    end: date
    label: str
    url: str
    icon: str
    color: str
    color_dark: str
    status: str
    journey: bool = False


@dataclass
class Segment:
    item: Item
    col: int        # 1 à 7
    span: int
    lane: int = 0
    cont_before: bool = False  # commence avant cette semaine
    cont_after: bool = False   # se poursuit après


@dataclass
class Week:
    days: list
    segments: list = field(default_factory=list)
    lanes: int = 0


def calendar_items(rows):
    """Lignes de la liste (voir ListRow) → éléments du calendrier."""
    items = []
    for row in rows:
        if row.journey:
            journey = row.journey
            items.append(Item(
                start=journey.start_date, end=journey.end_date, label=journey.display_name,
                url=url_for("trips.journey_detail", journey_id=journey.id), icon="fa-route",
                color=JOURNEY_COLOR, color_dark=JOURNEY_COLOR_DARK, status=journey.status, journey=True,
            ))
        else:
            trip = row.trip
            mode = TRANSPORT_MODES[trip.transport_mode]
            items.append(Item(
                start=trip.depart_date, end=trip.end_date, label=f"{trip.origin_name} → {trip.dest_name}",
                url=url_for("trips.detail", trip_id=trip.id), icon=mode["icon"],
                color=mode["color"], color_dark=mode["color_dark"], status=trip.status,
            ))
    items.sort(key=lambda i: (i.start, -(i.end - i.start).days, i.label))
    return items


def visible_range(first):
    """Premier et dernier jour affichés : des semaines entières autour du mois (selon la langue)."""
    week_start = Locale.parse(current_locale()).first_week_day  # 0 = lundi
    start = first - timedelta(days=(first.weekday() - week_start) % 7)
    last = shift_month(first, 1) - timedelta(days=1)
    end = last + timedelta(days=(week_start + 6 - last.weekday()) % 7)
    return start, end


def month_weeks(first, items):
    """Semaines du mois avec, pour chacune, les segments de barres et leur couloir."""
    start, end = visible_range(first)
    today = utils.today()
    weeks = []
    week_start = start
    while week_start <= end:
        week_end = week_start + timedelta(days=6)
        days = [{"date": d, "in_month": d.month == first.month, "today": d == today}
                for d in (week_start + timedelta(days=i) for i in range(7))]
        week = Week(days=days)
        lanes = []  # dernière colonne occupée par couloir
        for item in items:
            if item.end < week_start or item.start > week_end:
                continue
            seg_start, seg_end = max(item.start, week_start), min(item.end, week_end)
            col = (seg_start - week_start).days + 1
            span = (seg_end - seg_start).days + 1
            lane = next((i for i, last in enumerate(lanes) if last < col), len(lanes))
            if lane == len(lanes):
                lanes.append(0)
            lanes[lane] = col + span - 1
            week.segments.append(Segment(item, col, span, lane, item.start < week_start, item.end > week_end))
        week.lanes = len(lanes)
        weeks.append(week)
        week_start += timedelta(days=7)
    return weeks


def weekday_names():
    """Noms abrégés des jours, dans l'ordre de la semaine de la langue."""
    locale = current_locale()
    week_start = Locale.parse(locale).first_week_day
    names = get_day_names("abbreviated", locale=locale)
    return [names[(week_start + i) % 7] for i in range(7)]
