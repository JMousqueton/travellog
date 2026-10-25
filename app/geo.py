"""Distances (haversine) et géocodage Nominatim avec cache en base et limitation de débit."""
import math
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

try:
    import fcntl
except ImportError:  # Windows : verrou propre au processus uniquement
    fcntl = None

import requests
from flask import current_app
from sqlalchemy.exc import IntegrityError

EARTH_RADIUS_KM = 6371.0088
MIN_QUERY_LENGTH = 3
MAX_RESULTS = 6


def haversine_km(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


class GeocodingError(Exception):
    pass


def normalize_query(query):
    return " ".join((query or "").split()).casefold()


class NominatimClient:
    """Client minimaliste. Les appels sont sérialisés pour garantir l'intervalle minimal exigé par
    la politique d'utilisation de Nominatim : un verrou de thread dans le processus, et un fichier
    verrou (flock) partagé par tous les workers de la machine, qui contient l'heure du dernier appel."""

    _lock = threading.Lock()
    _last_call = 0.0  # utilisé seulement sans fichier verrou (time.time())

    @staticmethod
    @contextmanager
    def _serialized(lock_path):
        """Section critique ; renvoie le fichier verrou ouvert, ou None sans verrou inter-processus."""
        with NominatimClient._lock:
            if fcntl is None or not lock_path or lock_path == "none":
                yield None
                return
            with open(lock_path, "a+", encoding="ascii") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    yield fh
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    @staticmethod
    def _read_last_call(fh):
        if fh is None:
            return NominatimClient._last_call
        fh.seek(0)
        try:
            return float(fh.read().strip() or 0)
        except ValueError:
            return 0.0

    @staticmethod
    def _write_last_call(fh, value):
        if fh is None:
            NominatimClient._last_call = value
            return
        fh.seek(0)
        fh.truncate()
        fh.write(repr(value))
        fh.flush()

    def search(self, query, lang):
        cfg = current_app.config
        params = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": MAX_RESULTS,
            "accept-language": lang,
        }
        if cfg.get("NOMINATIM_EMAIL"):
            params["email"] = cfg["NOMINATIM_EMAIL"]
        headers = {"User-Agent": cfg["NOMINATIM_USER_AGENT"]}
        with self._serialized(cfg.get("NOMINATIM_LOCK_FILE")) as fh:
            # Horloge murale (et non monotonic) : la valeur est partagée entre processus.
            wait = cfg["NOMINATIM_MIN_INTERVAL"] - (time.time() - self._read_last_call(fh))
            if wait > 0:
                time.sleep(min(wait, cfg["NOMINATIM_MIN_INTERVAL"]))
            try:
                response = requests.get(
                    cfg["NOMINATIM_URL"], params=params, headers=headers, timeout=cfg["NOMINATIM_TIMEOUT"]
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise GeocodingError(str(exc)) from exc
            finally:
                self._write_last_call(fh, time.time())
        return [_simplify(item) for item in payload if "lat" in item and "lon" in item]


def _simplify(item):
    address = item.get("address") or {}
    name = item.get("name") or item.get("display_name", "").split(",")[0]
    country = address.get("country")
    short = f"{name}, {country}" if country and country != name else name
    return {
        "name": short,
        "label": item.get("display_name", short),
        "lat": round(float(item["lat"]), 6),
        "lon": round(float(item["lon"]), 6),
        "type": item.get("type"),
        "country_code": (address.get("country_code") or "").upper()[:2] or None,
    }


client = NominatimClient()


def geocode(query, lang):
    """Renvoie une liste de suggestions [{name, label, lat, lon, type}], depuis le cache si possible."""
    from .extensions import db
    from .models import GeocodeCache

    key = normalize_query(query)
    if len(key) < MIN_QUERY_LENGTH:
        return []
    max_age = timedelta(days=current_app.config["GEOCODE_CACHE_DAYS"])
    cached = db.session.execute(
        db.select(GeocodeCache).filter_by(query=key, lang=lang)
    ).scalar_one_or_none()
    if cached is not None:
        created = cached.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created < max_age:
            return cached.results or []
        db.session.delete(cached)
        db.session.flush()

    results = client.search(query.strip(), lang)
    first = results[0] if results else {}
    entry = GeocodeCache(
        query=key,
        lang=lang,
        name=first.get("name"),
        lat=first.get("lat"),
        lon=first.get("lon"),
        results=results,
    )
    db.session.add(entry)
    try:
        db.session.commit()
    except IntegrityError:
        # Une requête concurrente a déjà rempli le cache.
        db.session.rollback()
    return results


def purge_geocode_cache(everything=False):
    """Supprime les entrées expirées du cache (ou toutes) et renvoie leur nombre."""
    from .extensions import db
    from .models import GeocodeCache

    stmt = db.delete(GeocodeCache)
    if not everything:
        cutoff = datetime.now(timezone.utc) - timedelta(days=current_app.config["GEOCODE_CACHE_DAYS"])
        stmt = stmt.where(GeocodeCache.created_at < cutoff)
    count = db.session.execute(stmt).rowcount
    db.session.commit()
    return count
