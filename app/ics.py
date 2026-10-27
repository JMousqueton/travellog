"""Agenda iCalendar (RFC 5545) : un événement « journée entière » par trajet, du départ au retour.

Les notes ne sont pas incluses : l'adresse d'abonnement est secrète mais transmise au service d'agenda.
"""
from datetime import datetime, timedelta, timezone

from flask import request

from .i18n import format_distance
from .transport import mode_label

MODE_EMOJI = {"plane": "✈️", "train": "🚆", "car": "🚗", "bus": "🚌", "boat": "⛴️", "bike": "🚲", "walk": "🚶"}


def _escape(text):
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line):
    """Coupe les lignes à 75 octets (continuation par une espace), sans couper un caractère UTF-8."""
    out, current = [], ""
    for char in line:
        limit = 75 if not out else 74
        if len((current + char).encode("utf-8")) > limit:
            out.append(current)
            current = char
        else:
            current += char
    out.append(current)
    return "\r\n ".join(out)


def _date(value):
    return value.strftime("%Y%m%d")


def trip_event(trip, stamp):
    route = f"{trip.origin_name} → {trip.dest_name}"
    description = [mode_label(trip.transport_mode), format_distance(trip.total_distance_km)]
    if trip.journey:
        description.append(trip.journey.display_name)
    lines = [
        "BEGIN:VEVENT",
        f"UID:trip-{trip.id}@{request.host.split(':')[0]}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{_date(trip.depart_date)}",
        # DTEND est exclusif pour un événement « journée entière ».
        f"DTEND;VALUE=DATE:{_date(trip.end_date + timedelta(days=1))}",
        f"SUMMARY:{_escape(MODE_EMOJI.get(trip.transport_mode, '') + ' ' + route)}",
        f"DESCRIPTION:{_escape(' · '.join(description))}",
        f"LOCATION:{_escape(trip.dest_name)}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]
    return lines


def calendar(trips, name):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Voyage Voyage//FR", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_escape(name)}", "REFRESH-INTERVAL;VALUE=DURATION:PT6H"]
    for trip in trips:
        lines.extend(trip_event(trip, stamp))
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
