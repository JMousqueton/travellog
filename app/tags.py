"""Étiquettes : saisie « vacances, famille », création à la volée et nettoyage des étiquettes inutilisées."""
from .extensions import db
from .models import Tag, trip_tags

MAX_TAGS = 10
MAX_LENGTH = 40


def parse_tags(text):
    """« Vacances, famille,vacances » -> ["Vacances", "famille"] (sans doublon, casse de la 1re saisie)."""
    seen, names = set(), []
    for raw in (text or "").replace(";", ",").split(","):
        name = " ".join(raw.split())
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    return names


def tags_text(tags):
    return ", ".join(tag.name for tag in tags)


def resolve(user, names):
    """Étiquettes de l'utilisateur correspondant aux noms (insensible à la casse), créées si besoin."""
    existing = {tag.name.casefold(): tag for tag in user.tags}
    result = []
    for name in names:
        tag = existing.get(name.casefold())
        if tag is None:
            tag = Tag(user_id=user.id, name=name[:MAX_LENGTH])
            db.session.add(tag)
            user.tags.append(tag)
            existing[name.casefold()] = tag
        result.append(tag)
    return result


def prune_unused(user):
    """Supprime les étiquettes de l'utilisateur qui ne sont plus portées par aucun trajet."""
    db.session.flush()
    used = db.select(trip_tags.c.tag_id)
    for tag in db.session.execute(
        db.select(Tag).where(Tag.user_id == user.id, Tag.id.not_in(used))
    ).scalars():
        db.session.delete(tag)
