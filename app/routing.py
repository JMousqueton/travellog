"""Distance d'itinéraire par un serveur OSRM (facultatif, voir ROUTING_URL)."""
import requests
from flask import current_app


def profiles():
    pairs = (item.split(":", 1) for item in current_app.config["ROUTING_PROFILES"].split(",") if ":" in item)
    return {mode.strip(): profile.strip() for mode, profile in pairs}


def enabled_for(mode):
    return bool(current_app.config["ROUTING_URL"]) and mode in profiles()


def route_distance_km(mode, origin, dest):
    """Distance en km par le réseau, ou None (mode non routé, service absent ou en erreur)."""
    if not enabled_for(mode):
        return None
    (olat, olon), (dlat, dlon) = origin, dest
    url = f"{current_app.config['ROUTING_URL']}/route/v1/{profiles()[mode]}/{olon:.6f},{olat:.6f};{dlon:.6f},{dlat:.6f}"
    try:
        response = requests.get(url, params={"overview": "false"}, timeout=current_app.config["ROUTING_TIMEOUT"],
                                headers={"User-Agent": current_app.config["NOMINATIM_USER_AGENT"]})
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        current_app.logger.warning("Calcul d'itinéraire indisponible : %s", exc)
        return None
    if data.get("code") != "Ok" or not data.get("routes"):
        return None  # par exemple aucun itinéraire routier (île, autre continent)
    return round(data["routes"][0]["distance"] / 1000, 1)


def update_route(trip):
    """Recalcule la distance d'itinéraire d'un trajet (à appeler quand lieux ou mode changent)."""
    trip.route_distance_km = route_distance_km(
        trip.transport_mode, (trip.origin_lat, trip.origin_lon), (trip.dest_lat, trip.dest_lon))
