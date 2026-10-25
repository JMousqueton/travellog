from flask import abort, current_app, jsonify, request, url_for
from flask_babel import gettext as _
from flask_babel import ngettext
from flask_login import current_user, login_required

from .. import countries as geo_countries
from ..extensions import limiter
from ..flights import lookup_flight
from ..geo import GeocodingError, geocode
from ..i18n import LANGUAGES, current_locale, format_countdown, format_day, format_distance
from ..models import ShareLink
from ..transport import mode_label
from ..trips.queries import FilterError, list_trips, parse_filters, shared_trips_for
from ..trips.stats import compute_stats, count_label, country_summary, next_trip, trip_count
from . import bp


def _country(code, locale):
    return {"code": code, "name": geo_countries.country_name(code, locale), "flag": geo_countries.flag(code)}


def serialize_trip(trip, actions=True):
    locale = current_locale()
    return {
        "id": trip.id,
        "origin": {"name": trip.origin_name, "lat": trip.origin_lat, "lon": trip.origin_lon},
        "destination": {"name": trip.dest_name, "lat": trip.dest_lat, "lon": trip.dest_lon},
        "depart_date": trip.depart_date.isoformat(),
        "depart_date_fmt": format_day(trip.depart_date),
        "return_date": trip.return_date.isoformat() if trip.return_date else None,
        "return_date_fmt": format_day(trip.return_date) if trip.return_date else None,
        "transport_mode": trip.transport_mode,
        "mode_label": mode_label(trip.transport_mode),
        "is_round_trip": trip.is_round_trip,
        "status": trip.status,
        "countdown": format_countdown(trip.depart_date, trip.end_date),
        "distance_km": round(trip.distance_km, 1),
        "straight_km": round(trip.straight_km, 1),
        "distance_source": trip.distance_source,
        "total_distance_km": round(trip.total_distance_km, 1),
        "distance_fmt": format_distance(trip.total_distance_km),
        "countries": [_country(code, locale) for code in trip.countries],
        "co2_kg": round(trip.co2_kg, 1),
        # Notes et photos restent privées : absentes des liens de partage.
        "detail_url": url_for("trips.detail", trip_id=trip.id) if actions else None,
        "photo_count": len(trip.photos) if actions else 0,
        "tags": [tag.name for tag in trip.tags] if actions else [],
        "edit_url": url_for("trips.edit", trip_id=trip.id) if actions else None,
        "delete_url": url_for("trips.delete", trip_id=trip.id) if actions else None,
        "journey": {"id": trip.journey.id, "name": trip.journey.display_name} if trip.journey else None,
    }


def _filtered_trips(user=None):
    return list_trips(user or current_user, parse_filters(request.args))


def _shared_trips_or_404(token):
    """Trajets visibles par un lien de partage (filtres appliqués, voyages à venir masqués si demandé)."""
    link = ShareLink.active(token)
    if link is None:
        abort(404)
    return shared_trips_for(link, parse_filters(request.args))


@bp.errorhandler(FilterError)
def filter_error(exc):
    return jsonify(error=str(exc)), 400


@bp.route("/trips")
@login_required
def trips():
    items = _filtered_trips()
    return jsonify(
        trips=[serialize_trip(t) for t in items],
        count=trip_count(items),
        count_label=count_label(trip_count(items)),
    )


@bp.route("/shared/<token>/trips")
def shared_trips(token):
    items = _shared_trips_or_404(token)
    return jsonify(
        trips=[serialize_trip(t, actions=False) for t in items],
        count=trip_count(items),
        count_label=count_label(trip_count(items)),
    )


def _stats_json(items):
    """Statistiques ; avec ?year=AAAA (tableau de bord), seulement les trajets partis cette année-là.

    Le prochain départ reste cherché parmi tous les trajets : il peut tomber l'année suivante.
    """
    year = request.args.get("year", type=int)
    if not year:
        return jsonify(compute_stats(items))
    stats = compute_stats([t for t in items if t.depart_date.year == year])
    stats["next_trip"] = next_trip(items)
    return jsonify(stats)


@bp.route("/shared/<token>/stats")
def shared_stats(token):
    return _stats_json(_shared_trips_or_404(token))


@bp.route("/stats")
@login_required
def stats():
    return _stats_json(_filtered_trips())


def _countries_geojson(trips):
    """Pays visités (contours Natural Earth) avec leur nom localisé et le nombre de trajets."""
    summary = {entry["code"]: entry for entry in country_summary(trips)}
    features = []
    for feature in geo_countries.features(summary):
        entry = summary[feature["properties"]["code"]]
        features.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {"code": entry["code"], "name": entry["name"], "flag": entry["flag"],
                           "trips": entry["trips"], "trips_label": ngettext("%(num)s trajet", "%(num)s trajets", entry["trips"])},
        })
    response = jsonify(type="FeatureCollection", features=features)
    response.cache_control.private = True
    return response


def _places_json(trips, user):
    from ..trips.places import visited_places

    locale = current_locale()
    places = [{"name": p.name, "lat": p.lat, "lon": p.lon, "visits": p.visits,
               "visits_label": ngettext("%(num)s trajet", "%(num)s trajets", p.visits),
               "country": _country(p.country, locale) if p.country else None}
              for p in visited_places(trips, user)]
    response = jsonify(places=places, count=len(places))
    response.cache_control.private = True
    return response


@bp.route("/places")
@login_required
def places():
    return _places_json(_filtered_trips(), current_user)


@bp.route("/shared/<token>/places")
def shared_places(token):
    link = ShareLink.active(token)
    if link is None:
        abort(404)
    # Le domicile n'est jamais révélé : il est exclu comme pour le propriétaire.
    return _places_json(shared_trips_for(link, parse_filters(request.args)), link.user)


@bp.route("/countries")
@login_required
def countries():
    return _countries_geojson(_filtered_trips())


@bp.route("/shared/<token>/countries")
def shared_countries(token):
    return _countries_geojson(_shared_trips_or_404(token))


@bp.route("/flight")
@login_required
@limiter.limit("60 per minute")
def flight_view():
    """Compagnie et itinéraire d'un numéro de vol, pour pré-remplir le formulaire."""
    flight = lookup_flight(request.args.get("number", "")[:20])
    if flight is None or not (flight["carrier"] or flight["origin"]):
        return jsonify(error=_("Numéro de vol inconnu.")), 404
    return jsonify(flight)


@bp.route("/geocode")
@login_required
def geocode_view():
    query = request.args.get("q", "")
    lang = request.args.get("lang") or current_locale()
    if lang not in LANGUAGES:
        lang = current_locale()
    if len(query) > 200:
        return jsonify(error=_("Recherche trop longue.")), 400
    try:
        results = geocode(query, lang)
    except GeocodingError as exc:
        current_app.logger.warning("Géocodage indisponible : %s", exc)
        return jsonify(error=_("La recherche de lieux est momentanément indisponible.")), 503
    return jsonify(results=results)
