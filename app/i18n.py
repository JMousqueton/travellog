"""Sélection de la langue, formatage localisé et chaînes exposées au JavaScript."""
from babel import Locale
from babel.numbers import format_percent as babel_format_percent
from babel.units import format_unit
from flask import current_app, has_request_context, request
from flask_babel import format_date, format_datetime, format_decimal, format_percent, get_locale
from flask_babel import gettext as _
from flask_babel import ngettext
from flask_login import current_user

from .transport import SERVICE_FIELDS, TRANSPORT_MODES

DEFAULT_LOCALE = "fr"
LANGUAGES = {
    "fr": {"name": "Français"},
    "en": {"name": "English"},
    "es": {"name": "Español"},
    "de": {"name": "Deutsch"},
    "it": {"name": "Italiano"},
}


def select_locale():
    """Paramètre ?lang, puis profil utilisateur, puis cookie, puis Accept-Language, puis français."""
    if not has_request_context():
        return DEFAULT_LOCALE
    if request.args.get("lang") in LANGUAGES:
        return request.args["lang"]  # adresse propre à une langue (?lang=en), utilisée par les moteurs
    if current_user.is_authenticated and current_user.locale in LANGUAGES:
        return current_user.locale
    cookie = request.cookies.get(current_app.config["LANG_COOKIE_NAME"])
    if cookie in LANGUAGES:
        return cookie
    return request.accept_languages.best_match(list(LANGUAGES)) or DEFAULT_LOCALE


def current_locale():
    locale = get_locale()
    return locale.language if locale else DEFAULT_LOCALE


def format_distance(km):
    """Ex. 12 345,6 km (fr) / 12,345.6 km (en)."""
    return format_unit(km, "length-kilometer", length="short", format="#,##0.#", locale=current_locale())


def format_share(value):
    """Pourcentage à une décimale, avec la mise en forme de la langue (ex. 0,7 % en français)."""
    pattern = Locale.parse(current_locale()).percent_formats[None].pattern.replace("#,##0", "#,##0.#", 1)
    return babel_format_percent(value, pattern, locale=current_locale())


def format_co2(kg):
    """Ex. 850 kg / 1,2 t (fr) : en tonnes à partir d'une tonne."""
    if kg >= 1000:
        return format_unit(kg / 1000, "mass-tonne", length="short", format="#,##0.#", locale=current_locale())
    return format_unit(kg, "mass-kilogram", length="short", format="#,##0", locale=current_locale())


def format_countdown(start, end=None):
    """« Dans 12 jours », « Demain », « Aujourd'hui », « En cours »… ; chaîne vide pour un voyage passé."""
    from . import utils

    if start == utils.today():
        return _("Aujourd'hui")
    status = utils.trip_status(start, end or start)
    if status == "ongoing":
        return _("En cours")
    if status == "past":
        return ""
    days = (start - utils.today()).days
    if days == 1:
        return _("Demain")
    return ngettext("Dans %(num)s jour", "Dans %(num)s jours", days)


def format_day(value, fmt="medium"):
    return format_date(value, fmt) if value else ""


def format_moment(value):
    """Date et heure courtes (heure UTC : BABEL_DEFAULT_TIMEZONE)."""
    from .models import as_utc

    return format_datetime(as_utc(value), "short") if value else ""


def format_number(value):
    return format_decimal(value)


def js_strings():
    """Toutes les chaînes affichées par le JavaScript, déjà traduites."""
    return {
        "loading": _("Chargement…"),
        "error_loading": _("Impossible de charger les voyages. Réessayez."),
        "retry": _("Réessayer"),
        "empty_title": _("Aucun voyage pour l'instant"),
        "empty_text": _("Ajoutez votre premier voyage pour le voir apparaître sur la carte."),
        "empty_filtered_title": _("Aucun voyage ne correspond aux filtres"),
        "empty_filtered_text": _("Modifiez ou réinitialisez les filtres pour afficher vos voyages."),
        "reset_filters": _("Réinitialiser les filtres"),
        "add_trip": _("Ajouter un voyage"),
        "edit": _("Modifier"),
        "delete": _("Supprimer"),
        "zoom_to_trip": _("Afficher %(route)s sur la carte"),
        "edit_trip": _("Modifier le voyage %(route)s"),
        "delete_trip": _("Supprimer le voyage %(route)s"),
        "departure": _("Départ"),
        "return": _("Retour"),
        "distance": _("Distance"),
        "round_trip": _("Aller-retour"),
        "one_way": _("Aller simple"),
        "outbound_leg": _("Trajet aller"),
        "return_leg": _("Trajet retour"),
        "legend_title": _("Légende"),
        "legend_outbound": _("Aller"),
        "legend_return": _("Retour (pointillés)"),
        "trips_here": _("Voyages passant par ce lieu"),
        "map_label": _("Carte des voyages"),
        "osm_contributors": _("contributeurs OpenStreetMap"),
        "search_no_results": _("Aucun lieu trouvé"),
        "search_error": _("La recherche de lieux est momentanément indisponible."),
        "search_searching": _("Recherche…"),
        "search_hint": _("Saisissez au moins 3 caractères"),
        "search_results": _("%(count)s suggestions disponibles, utilisez les flèches haut et bas"),
        "return_before_departure": _("La date de retour doit être postérieure ou égale à la date de départ."),
        "return_required": _("La date de retour est obligatoire pour un aller-retour."),
        "theme_light": _("Passer en mode clair"),
        "theme_dark": _("Passer en mode sombre"),
        "theme_saved_error": _("Impossible d'enregistrer la préférence de thème."),
        "selected_trip": _("Voyage sélectionné : %(route)s"),
        "journey_label": _("Voyage : %(name)s"),
        "empty_shared_title": _("Aucun voyage à afficher"),
        "copied": _("Lien copié dans le presse-papiers."),
        "copy_failed": _("Impossible de copier le lien : sélectionnez-le et copiez-le manuellement."),
        "results_updated": _("Liste mise à jour"),
        "field_required": _("Ce champ est obligatoire."),
        "filter_dates_invalid": _("La date de début doit précéder la date de fin."),
        "countries_layer": _("Pays visités"),
        "details": _("Fiche"),
        "trip_details": _("Fiche du trajet %(route)s"),
        "status_upcoming": _("À venir"),
        "status_ongoing": _("En cours"),
        "legend_upcoming": _("À venir (estompé)"),
        "places_layer": _("Lieux visités"),
        "replay": _("Rejouer"),
        "replay_title": _("Rejouer mes voyages dans l'ordre chronologique"),
        "replay_play": _("Lecture"),
        "replay_pause": _("Pause"),
        "replay_close": _("Fermer la relecture"),
        "replay_date": _("Date de la relecture"),
        "view_choice": _("Affichage des voyages"),
        "view_map": _("Carte"),
        "view_globe": _("Globe"),
        "globe_label": _("Globe des voyages : faites-le tourner en le glissant ou avec les flèches du clavier"),
        "zoom_in": _("Zoomer"),
        "zoom_out": _("Dézoomer"),
        "close": _("Fermer"),
        "share_failed": _("Impossible de partager l'image : téléchargez-la puis partagez-la."),
        "offline": _("Hors ligne : vous voyez les données de votre dernière visite."),
        "online": _("Connexion rétablie."),
        "flight_searching": _("Recherche du vol…"),
        "flight_unknown": _("Vol inconnu : renseignez la compagnie et les lieux vous-même."),
        "flight_found_route": _("Compagnie, départ et arrivée remplis d'après le numéro de vol : vérifiez-les."),
        "flight_found_kept": _("Compagnie complétée ; départ et arrivée déjà saisis, conservés."),
        "flight_found_airline": _("Compagnie trouvée ; itinéraire inconnu pour ce numéro."),
    }


def js_i18n():
    return {
        "locale": current_locale(),
        "strings": js_strings(),
        "modeOrder": list(TRANSPORT_MODES),
        "modes": {
            key: {"label": str(m["label"]), "icon": m["icon"], "color": m["color"], "colorDark": m["color_dark"]}
            for key, m in TRANSPORT_MODES.items()
        },
    }


def init_app(app):
    app.jinja_env.filters["distance"] = format_distance
    app.jinja_env.filters["co2"] = format_co2
    app.jinja_env.globals["countdown"] = format_countdown
    from .countries import country_name, flag

    app.jinja_env.filters["country_name"] = lambda code: country_name(code, current_locale())
    app.jinja_env.filters["flag"] = flag
    app.jinja_env.filters["day"] = format_day
    app.jinja_env.filters["moment"] = format_moment
    app.jinja_env.filters["number"] = format_number
    app.jinja_env.filters["percent"] = format_percent

    @app.context_processor
    def inject_i18n():
        return {
            "LANGUAGES": LANGUAGES,
            "current_locale": current_locale(),
            "js_i18n": js_i18n,
            "TRANSPORT_MODES": TRANSPORT_MODES,
            "SERVICE_FIELDS": SERVICE_FIELDS,
        }
