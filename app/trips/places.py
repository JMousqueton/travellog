"""Lieux visités : extrémités des trajets regroupées dans un rayon de PLACE_RADIUS_KM (aéroport et ville
comptent pour un même lieu). Le domicile, s'il est défini, n'est pas compté."""
from collections import Counter

from ..geo import haversine_km
from .absences import HOME_RADIUS_KM
from .stats import _sort_key, happened

PLACE_RADIUS_KM = 15


class Place:
    def __init__(self, lat, lon):
        self.lat, self.lon = lat, lon
        self.names, self.countries = Counter(), Counter()
        self.trip_ids, self.first, self.last = set(), None, None

    @property
    def name(self):
        return self.names.most_common(1)[0][0]

    @property
    def country(self):
        return self.countries.most_common(1)[0][0] if self.countries else None

    @property
    def visits(self):
        return len(self.trip_ids)

    def add(self, name, country, trip):
        self.names[name] += 1
        if country:
            self.countries[country] += 1
        self.trip_ids.add(trip.id)
        self.first = min(self.first or trip.depart_date, trip.depart_date)
        self.last = max(self.last or trip.depart_date, trip.depart_date)


def visited_places(trips, user=None):
    """Lieux visités, du plus fréquenté au moins fréquenté."""
    places = []
    home = (user.home_lat, user.home_lon) if user is not None and user.has_home else None
    for trip in sorted(happened(trips), key=lambda t: (t.depart_date, t.id)):
        for name, lat, lon, country in ((trip.origin_name, trip.origin_lat, trip.origin_lon, trip.origin_country),
                                        (trip.dest_name, trip.dest_lat, trip.dest_lon, trip.dest_country)):
            if home and haversine_km(home[0], home[1], lat, lon) <= HOME_RADIUS_KM:
                continue
            place = next((p for p in places if haversine_km(p.lat, p.lon, lat, lon) <= PLACE_RADIUS_KM), None)
            if place is None:
                place = Place(lat, lon)
                places.append(place)
            place.add(name, country, trip)
    return sorted(places, key=lambda p: (-p.visits, _sort_key(p.name)))
