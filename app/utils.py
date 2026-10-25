from datetime import date
from urllib.parse import urlsplit

try:
    from wtforms.fields.choices import SelectChoice
except ImportError:  # WTForms < 3.3
    SelectChoice = None


def select_choices(pairs):
    """Choix de SelectField compatibles avec toutes les versions de WTForms 3.x."""
    return [SelectChoice(value, label) if SelectChoice else (value, label) for value, label in pairs]


def is_safe_redirect(target):
    """N'accepte que les chemins relatifs à l'application (pas d'open redirect)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc


def today():
    """Date du jour (fonction à part pour pouvoir la figer dans les tests)."""
    return date.today()


def trip_status(start, end, on=None):
    """« upcoming » avant le départ, « ongoing » entre départ et retour, « past » ensuite."""
    on = on or today()
    if start > on:
        return "upcoming"
    return "ongoing" if end >= on else "past"
