"""Photos : validation et ré-encodage avec Pillow (le fichier servi ne garde aucune métadonnée EXIF),
miniatures, et suppression des fichiers une fois la transaction validée.

Les informations utiles (appareil, réglages, date, position GPS) sont relevées à l'envoi et rangées dans
Photo.exif : seul le propriétaire les voit, sur la page de la photo."""
import io
import math
import os
import secrets
from datetime import datetime

from babel.dates import format_datetime
from babel.numbers import format_decimal
from flask import current_app
from flask_babel import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import event
from sqlalchemy.orm import Session

from .extensions import db
from .i18n import current_locale
from .models import Photo, Trip

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}  # MPO : JPEG multi-images de certains appareils
MAX_PIXELS = 60_000_000  # au-delà : refus (protection contre les « bombes de décompression »)
FULL_SIZE = 2560
THUMB_SIZE = 480


class PhotoError(ValueError):
    pass


def upload_folder():
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    return folder


def photo_path(photo, thumb=False):
    return os.path.join(upload_folder(), f"{photo.stored_name}{'.thumb' if thumb else ''}.jpg")


def _flatten(image):
    """Convertit en RGB, sur fond blanc si l'image est transparente."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def save_upload(storage, user, trip=None, journey=None):
    """Valide et enregistre un fichier envoyé (werkzeug FileStorage). Renvoie la Photo (non validée)."""
    owner_photos = (trip or journey).photos
    if len(owner_photos) >= current_app.config["MAX_PHOTOS_PER_ITEM"]:
        raise PhotoError(_("Nombre maximal de photos atteint (%(max)s).", max=current_app.config["MAX_PHOTOS_PER_ITEM"]))
    data = storage.stream.read(current_app.config["MAX_PHOTO_BYTES"] + 1)
    if len(data) > current_app.config["MAX_PHOTO_BYTES"]:
        raise PhotoError(_("Photo trop volumineuse (%(max)s Mo au maximum).",
                           max=current_app.config["MAX_PHOTO_BYTES"] // (1024 * 1024)))
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise PhotoError(_("Format non pris en charge : utilisez JPEG, PNG, WebP ou GIF."))
            if probe.width * probe.height > MAX_PIXELS:
                raise PhotoError(_("Image trop grande."))
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.seek(0)  # première image d'un GIF animé
            exif = read_exif(image)
            image = ImageOps.exif_transpose(image)
            image = _flatten(image)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise PhotoError(_("Ce fichier n'est pas une image valide.")) from None

    photo = Photo(user_id=user.id, trip=trip, journey=journey, stored_name=secrets.token_hex(16),
                  original_name=(storage.filename or "")[:255] or None, exif=exif)
    full = image.copy()
    full.thumbnail((FULL_SIZE, FULL_SIZE), Image.Resampling.LANCZOS)
    # Ré-encodage sans exif= : aucune métadonnée de l'original n'est conservée.
    full.save(photo_path(photo), "JPEG", quality=85, optimize=True, progressive=True)
    thumb = ImageOps.fit(image, (THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
    thumb.save(photo_path(photo, thumb=True), "JPEG", quality=80, optimize=True)
    photo.width, photo.height = full.size
    photo.size = os.path.getsize(photo_path(photo))
    db.session.add(photo)
    # Si la transaction est annulée, les fichiers déjà écrits sont supprimés.
    db.session.info.setdefault("photo_files_new", []).append(photo.stored_name)
    return photo


# --- Métadonnées EXIF ---------------------------------------------------------------------

EXIF_IFD, GPS_IFD = 0x8769, 0x8825
TEXT_FIELDS = ("make", "model", "lens", "software", "taken_at", "offset")
NUMBER_FIELDS = ("exposure", "f_number", "iso", "focal_length", "focal_35", "lat", "lon", "alt", "direction")


def _text(value, limit=100):
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        return None
    value = "".join(c for c in value if c.isprintable()).strip()
    return value[:limit] or None


def _number(value):
    if isinstance(value, (tuple, list)) and len(value) == 1:
        value = value[0]
    try:
        number = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return number if math.isfinite(number) else None


def _degrees(value, ref, negative):
    """(degrés, minutes, secondes) + référence N/S ou E/W → degrés décimaux signés."""
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        return None
    parts = [_number(v) for v in value]
    if None in parts:
        return None
    degrees = parts[0] + parts[1] / 60 + parts[2] / 3600
    return -degrees if _text(ref) == negative else degrees


def _taken_at(value):
    text = _text(value, 30)
    try:
        return datetime.strptime(text, "%Y:%m:%d %H:%M:%S").isoformat() if text else None
    except ValueError:
        return None


def read_exif(image):
    """Relève les informations EXIF d'une image ouverte par Pillow. Renvoie un dict, ou None si rien d'utile."""
    try:
        base = image.getexif()
        details = base.get_ifd(EXIF_IFD)
        gps = base.get_ifd(GPS_IFD)
    except Exception:  # EXIF mal formé : la photo est acceptée sans ses métadonnées
        return None
    lens = " ".join(filter(None, (_text(details.get(0xA433)), _text(details.get(0xA434)))))
    flash = details.get(0x9209)
    info = {
        "make": base.get(0x010F), "model": base.get(0x0110), "software": base.get(0x0131), "lens": lens,
        "taken_at": _taken_at(details.get(0x9003) or base.get(0x0132)), "offset": details.get(0x9011),
        "exposure": details.get(0x829A), "f_number": details.get(0x829D), "iso": details.get(0x8827),
        "focal_length": details.get(0x920A), "focal_35": details.get(0xA405),
        "flash": bool(flash & 1) if isinstance(flash, int) else None,
        "width": image.width, "height": image.height,
    }
    lat, lon = _degrees(gps.get(2), gps.get(1), "S"), _degrees(gps.get(4), gps.get(3), "W")
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        info["lat"], info["lon"] = round(lat, 6), round(lon, 6)
        alt = _number(gps.get(6))
        if alt is not None:
            info["alt"] = -alt if gps.get(5) in (1, b"\x01") else alt
        info["direction"] = gps.get(0x11)
    return clean_exif(info)


def clean_exif(info):
    """Ne garde que les champs connus, aux types attendus (sert aussi à la restauration d'une sauvegarde)."""
    if not isinstance(info, dict):
        return None
    clean = {key: _text(info.get(key)) for key in TEXT_FIELDS}
    clean.update({key: _number(info.get(key)) for key in NUMBER_FIELDS})
    clean["flash"] = info.get("flash") if isinstance(info.get("flash"), bool) else None
    try:
        datetime.fromisoformat(clean["taken_at"] or "")
    except ValueError:
        clean["taken_at"] = None
    lat, lon = clean["lat"], clean["lon"]
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        for key in ("lat", "lon", "alt", "direction"):
            clean[key] = None
    clean = {key: round(value, 6) if isinstance(value, float) else value
             for key, value in clean.items() if value is not None}
    if not clean:
        return None  # sans aucune information EXIF, les seules dimensions n'ont pas d'intérêt
    for key in ("width", "height"):
        value = info.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 100_000:
            clean[key] = value
    return clean


def _exposure(seconds):
    if seconds >= 0.3 or seconds <= 0:
        return _("%(value)s s", value=format_decimal(seconds, "#,##0.#", locale=current_locale()))
    return _("1/%(value)s s", value=round(1 / seconds))


def _coordinate(value, positive, negative):
    return f"{format_decimal(abs(value), '0.000000', locale=current_locale())}° {positive if value >= 0 else negative}"


def exif_rows(exif):
    """Lignes (libellé, valeur) à afficher : (appareil et réglages, position GPS)."""
    exif = exif or {}
    locale = current_locale()

    def number(value, fmt="#,##0.#"):
        return format_decimal(value, fmt, locale=locale)

    camera = []
    if exif.get("taken_at"):
        taken = format_datetime(datetime.fromisoformat(exif["taken_at"]), "medium", locale=locale)
        camera.append((_("Prise de vue"), f"{taken} ({exif['offset']})" if exif.get("offset") else taken))
    make, model = exif.get("make", ""), exif.get("model", "")
    device = model if make and model.casefold().startswith(make.casefold()) else f"{make} {model}".strip()
    if device:
        camera.append((_("Appareil"), device))
    if exif.get("lens"):
        camera.append((_("Objectif"), exif["lens"]))
    if exif.get("exposure") is not None:
        camera.append((_("Exposition"), _exposure(exif["exposure"])))
    if exif.get("f_number"):
        camera.append((_("Ouverture"), f"ƒ/{number(exif['f_number'])}"))
    if exif.get("iso"):
        camera.append((_("Sensibilité"), f"ISO {number(exif['iso'], '0')}"))
    if exif.get("focal_length"):
        focal = _("%(value)s mm", value=number(exif["focal_length"]))
        if exif.get("focal_35"):
            focal += " · " + _("%(value)s mm en équivalent 24×36", value=number(exif["focal_35"], "0"))
        camera.append((_("Focale"), focal))
    if "flash" in exif:
        camera.append((_("Flash"), _("Déclenché") if exif["flash"] else _("Non déclenché")))
    if exif.get("width") and exif.get("height"):
        camera.append((_("Dimensions d'origine"), f"{exif['width']} × {exif['height']} px"))
    if exif.get("software"):
        camera.append((_("Logiciel"), exif["software"]))
    gps = []
    if "lat" in exif and "lon" in exif:
        gps.append((_("Latitude"), _coordinate(exif["lat"], _("N"), _("S"))))
        gps.append((_("Longitude"), _coordinate(exif["lon"], _("E"), _("O"))))
        if exif.get("alt") is not None:
            gps.append((_("Altitude"), _("%(value)s m", value=number(exif["alt"], "#,##0"))))
        if exif.get("direction") is not None:
            gps.append((_("Direction"), f"{number(exif['direction'], '0')}°"))
    return camera, gps


def _remove_files(stored_names):
    folder = current_app.config["UPLOAD_FOLDER"]
    for name in stored_names:
        for suffix in (".jpg", ".thumb.jpg"):
            try:
                os.remove(os.path.join(folder, name + suffix))
            except FileNotFoundError:
                pass


@event.listens_for(Session, "after_flush")
def _track_deleted_photos(session, _context):
    deleted = [obj.stored_name for obj in session.deleted if isinstance(obj, Photo)]
    if deleted:
        session.info.setdefault("photo_files_deleted", []).extend(deleted)


@event.listens_for(Session, "after_commit")
def _delete_files_after_commit(session):
    session.info.pop("photo_files_new", None)
    names = session.info.pop("photo_files_deleted", [])
    if names:
        _remove_files(names)


@event.listens_for(Session, "after_soft_rollback")
def _cleanup_after_rollback(session, previous_transaction):
    if previous_transaction.parent is not None:
        return
    session.info.pop("photo_files_deleted", None)
    names = session.info.pop("photo_files_new", [])
    if names:
        _remove_files(names)


def move_photos(source, target):
    """Rattache les photos d'un trajet ou d'un voyage à un autre (regroupement, dégroupement)."""
    is_trip = isinstance(target, Trip)
    for photo in list(source.photos):
        photo.trip, photo.journey = (target, None) if is_trip else (None, target)
    # Écrit le changement de parent avant la suppression éventuelle de la source et de sa cascade.
    db.session.flush()


def merge_notes(*texts):
    return "\n\n".join(t.strip() for t in texts if t and t.strip()) or None


def orphan_files():
    """Fichiers présents dans UPLOAD_FOLDER sans ligne correspondante en base."""
    known = set(db.session.execute(db.select(Photo.stored_name)).scalars())
    orphans = []
    for name in os.listdir(upload_folder()):
        stem = name.split(".", 1)[0]
        if stem not in known:
            orphans.append(os.path.join(upload_folder(), name))
    return orphans
