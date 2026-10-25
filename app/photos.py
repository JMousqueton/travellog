"""Photos : validation et ré-encodage avec Pillow (supprime les métadonnées EXIF, dont la position GPS),
miniatures, et suppression des fichiers une fois la transaction validée."""
import io
import os
import secrets

from flask import current_app
from flask_babel import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import event
from sqlalchemy.orm import Session

from .extensions import db
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
            image = ImageOps.exif_transpose(image)
            image = _flatten(image)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise PhotoError(_("Ce fichier n'est pas une image valide.")) from None

    photo = Photo(user_id=user.id, trip=trip, journey=journey, stored_name=secrets.token_hex(16),
                  original_name=(storage.filename or "")[:255] or None)
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
