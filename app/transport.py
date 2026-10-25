"""Modes de transport : libellé traduisible, icône Font Awesome et couleurs."""
from flask_babel import lazy_gettext as _l

# L'ordre de ce dictionnaire est celui des listes déroulantes et de la légende.
TRANSPORT_MODES = {
    "plane": {"label": _l("Avion"), "icon": "fa-plane", "color": "#4f46e5", "color_dark": "#818cf8"},
    "train": {"label": _l("Train"), "icon": "fa-train", "color": "#dc2626", "color_dark": "#f87171"},
    "car": {"label": _l("Voiture"), "icon": "fa-car", "color": "#c2410c", "color_dark": "#fb923c"},
    "bus": {"label": _l("Bus"), "icon": "fa-bus", "color": "#a16207", "color_dark": "#facc15"},
    "boat": {"label": _l("Bateau"), "icon": "fa-ship", "color": "#0369a1", "color_dark": "#38bdf8"},
    "bike": {"label": _l("Vélo"), "icon": "fa-bicycle", "color": "#15803d", "color_dark": "#4ade80"},
    "walk": {"label": _l("À pied"), "icon": "fa-person-walking", "color": "#7e22ce", "color_dark": "#c084fc"},
}


# Distance réelle ≈ distance à vol d'oiseau × facteur de détour (ordres de grandeur des études de
# « circuité » des réseaux : 1,2 à 1,4 pour la route, un peu moins pour le rail). L'avion suit
# l'orthodromie : les facteurs CO₂ de l'ADEME s'appliquent déjà à cette distance.
DETOUR_FACTORS = {"plane": 1.0, "train": 1.25, "car": 1.3, "bus": 1.3, "boat": 1.1, "bike": 1.3, "walk": 1.3}

# Émissions en kg CO2e par voyageur et par km, d'après l'ADEME (Base Carbone), valeurs moyennes arrondies.
# Avion : selon la distance du vol, traînées de condensation comprises ; voiture : une personne à bord.
CO2_KG_PER_KM = {"train": 0.03, "car": 0.218, "bus": 0.03, "boat": 0.12, "bike": 0.0, "walk": 0.0}
PLANE_CO2_BANDS = [(1000, 0.258), (3500, 0.187), (float("inf"), 0.152)]


def co2_factor(mode, km):
    if mode == "plane":
        return next(factor for limit, factor in PLANE_CO2_BANDS if km < limit)
    return CO2_KG_PER_KM.get(mode, 0.0)


def co2_kg(mode, km):
    """Estimation des émissions d'un trajet simple de `km` kilomètres."""
    return km * co2_factor(mode, km)


def mode_choices():
    from .utils import select_choices

    return select_choices((key, mode["label"]) for key, mode in TRANSPORT_MODES.items())


def mode_label(key):
    return str(TRANSPORT_MODES[key]["label"]) if key in TRANSPORT_MODES else key
