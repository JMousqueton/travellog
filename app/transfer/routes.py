import io
import json
import os
import re
import secrets
import time
import zipfile
from datetime import date

from flask import Response, current_app, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l
from flask_babel import ngettext
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import HiddenField, SubmitField

from ..extensions import db
from ..mail_import.wallet import is_pass
from ..models import Journey, Trip
from ..photos import PhotoError, clean_exif, photo_path, save_upload
from ..tags import MAX_TAGS, parse_tags, resolve
from ..trips.queries import list_trips
from . import bp
from .formats import (PARSERS, FileFormatError, detect_format, pair_round_trips, to_csv, to_geojson, to_gpx, trip_record,
                      validate_record)

EXPORTS = {  # « zip » (sauvegarde complète) a sa propre route
    "csv": ("text/csv; charset=utf-8", "csv"),
    "geojson": ("application/geo+json", "geojson"),
    "gpx": ("application/gpx+xml", "gpx"),
}
MAX_REPORTED_ERRORS = 20


class ImportForm(FlaskForm):
    file = FileField(_l("Fichier CSV, GeoJSON, GPX, carte d'embarquement Wallet (.pkpass) ou sauvegarde complète (.zip)"), validators=[FileRequired(message=_l("Choisissez un fichier."))])
    submit = SubmitField(_l("Importer"))


@bp.route("/import-export")
@login_required
def index():
    return render_template("transfer/index.html", form=ImportForm(), trip_total=current_user.trips.count())


@bp.route("/export.<fmt>")
@login_required
def export(fmt):
    if fmt not in EXPORTS:
        return redirect(url_for("transfer.index"))
    records = [trip_record(t) for t in sorted(list_trips(current_user), key=lambda t: (t.depart_date, t.id))]
    if fmt == "csv":
        body = to_csv(records)
    elif fmt == "geojson":
        body = to_geojson(records)
    else:
        body = to_gpx(records, current_app.config["SITE_NAME"])
    mimetype, ext = EXPORTS[fmt]
    response = Response(body, mimetype=mimetype)
    response.headers["Content-Disposition"] = f'attachment; filename="voyages-{date.today().isoformat()}.{ext}"'
    response.cache_control.no_store = True
    return response


@bp.route("/export.zip")
@login_required
def export_archive():
    """Sauvegarde complète du compte : trajets (GeoJSON, mêmes champs que l'export) et photos."""
    trips = sorted(list_trips(current_user), key=lambda t: (t.depart_date, t.id))
    records, seen_journeys = [], set()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:  # JPEG déjà compressés
        def add_photos(photos):
            entries = []
            for photo in photos:
                name = f"photos/{photo.stored_name}.jpg"
                try:
                    archive.write(photo_path(photo), name)
                except FileNotFoundError:
                    continue
                entries.append({"file": name, "name": photo.original_name, "exif": photo.exif})
            return entries

        for trip in trips:
            record = trip_record(trip)
            record["photos"] = add_photos(trip.photos)
            # Les photos d'un voyage sont rattachées à son premier trajet exporté.
            record["journey_photos"] = []
            if trip.journey and trip.journey_id not in seen_journeys:
                seen_journeys.add(trip.journey_id)
                record["journey_photos"] = add_photos(trip.journey.photos)
            records.append(record)
        archive.writestr("trips.geojson", to_geojson(records))
        archive.writestr("LISEZMOI.txt", _("Sauvegarde complète de votre compte Voyage Voyage. Pour la restaurer, "
                                           "importez ce fichier .zip depuis la page Importer / exporter."))
    response = Response(out.getvalue(), mimetype="application/zip")
    response.headers["Content-Disposition"] = f'attachment; filename="voyage-voyage-{date.today().isoformat()}.zip"'
    response.cache_control.no_store = True
    return response


class _ArchivedFile:
    """Fichier d'une archive présenté comme un envoi (interface FileStorage minimale pour save_upload)."""

    def __init__(self, data, filename):
        self.stream, self.filename = io.BytesIO(data), filename


def _read_archive(data):
    """Renvoie (trips.geojson, archive ouverte) après les contrôles anti « bombe zip »."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise FileFormatError(_("Archive .zip invalide.")) from None
    infos = archive.infolist()
    cfg = current_app.config
    if len(infos) > cfg["MAX_ARCHIVE_FILES"] or sum(i.file_size for i in infos) > cfg["MAX_ARCHIVE_UNCOMPRESSED_BYTES"]:
        raise FileFormatError(_("Archive trop volumineuse."))
    try:
        return archive.read("trips.geojson"), archive
    except KeyError:
        raise FileFormatError(_("Archive invalide : trips.geojson absent (utilisez une sauvegarde complète).")) from None


def _read_passes(data):
    """Trajets des cartes d'embarquement d'un .pkpass ou .pkpasses (aller et retour réunis)."""
    from ..i18n import current_locale
    from ..mail_import.wallet import WalletError, pass_rows

    try:
        rows = pass_rows(data, date.today(), current_locale())
    except WalletError:
        raise FileFormatError(_("Carte Wallet illisible : ce n'est pas un fichier .pkpass valide.")) from None
    if not rows:
        raise FileFormatError(_("Aucun trajet reconnu dans cette carte Wallet (seules les cartes d'embarquement sont lues)."))
    return pair_round_trips(list(enumerate(rows, start=1)))


def _attach_photos(archive, entries, trip=None, journey=None):
    added = failed = 0
    for entry in entries:
        try:
            data = archive.read(entry["file"])
            photo = save_upload(_ArchivedFile(data, entry.get("name") or entry["file"]), current_user,
                                trip=trip, journey=journey)
            # Le fichier de la sauvegarde n'a plus d'EXIF : les informations viennent de l'archive.
            photo.exif = photo.exif or clean_exif(entry.get("exif"))
            added += 1
        except (KeyError, PhotoError, zipfile.BadZipFile):
            failed += 1
    return added, failed


def _duplicate_key(name_o, name_d, depart, mode):
    return (name_o.casefold(), name_d.casefold(), depart, mode)


# --- Aperçu avant import ---------------------------------------------------------------------
# Les trajets lus attendent la confirmation dans IMPORT_FOLDER/<utilisateur>-<jeton>.json.

PENDING_MAX_AGE = 3600  # secondes
PENDING_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class ConfirmImportForm(FlaskForm):
    token = HiddenField()
    submit = SubmitField(_l("Importer la sélection"))


def _pending_path(token):
    return os.path.join(current_app.config["IMPORT_FOLDER"], f"{current_user.id}-{token}.json")


def _store_pending(records, filename):
    folder = current_app.config["IMPORT_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    now = time.time()
    for name in os.listdir(folder):  # aperçus abandonnés
        path = os.path.join(folder, name)
        if now - os.path.getmtime(path) > PENDING_MAX_AGE:
            os.remove(path)
    token = secrets.token_urlsafe(16)
    with open(_pending_path(token), "w", encoding="utf-8") as fh:
        json.dump({"filename": filename, "records": records}, fh, default=date.isoformat)
    return token


def _load_pending(token):
    """Trajets en attente de confirmation (dates reconstituées), ou None si l'aperçu a expiré."""
    if not PENDING_TOKEN.match(token or ""):
        return None
    try:
        with open(_pending_path(token), encoding="utf-8") as fh:
            pending = json.load(fh)
    except (OSError, ValueError):
        return None
    if time.time() - os.path.getmtime(_pending_path(token)) > PENDING_MAX_AGE:
        return None
    for record in pending["records"]:
        for key in ("depart_date", "return_date"):
            record[key] = date.fromisoformat(record[key]) if record[key] else None
    return pending


def _existing_keys():
    return {_duplicate_key(t.origin_name, t.dest_name, t.depart_date, t.transport_mode) for t in current_user.trips}


def _record_key(record):
    return _duplicate_key(record["origin_name"], record["dest_name"], record["depart_date"], record["transport_mode"])


def _render_index(form, errors=None, status=400, **extra):
    return render_template("transfer/index.html", form=form, trip_total=current_user.trips.count(), errors=errors,
                           **extra), status


@bp.route("/import", methods=["POST"])
@login_required
def import_file():
    form = ImportForm()
    if not form.validate_on_submit():
        return _render_index(form)
    storage = form.file.data
    is_archive = (storage.filename or "").lower().endswith(".zip")
    limit = current_app.config["MAX_CONTENT_LENGTH"] if is_archive else current_app.config["MAX_IMPORT_BYTES"]
    data = storage.stream.read(limit + 1)
    errors, archive = [], None
    if len(data) > limit:
        errors.append(_("Fichier trop volumineux (%(max)s Mo au maximum).",
                        max=limit // (1024 * 1024)))
    else:
        try:
            if is_archive:
                geojson, archive = _read_archive(data)
                rows = PARSERS["geojson"](geojson)
            elif is_pass(storage.filename, storage.mimetype):
                rows = _read_passes(data)
            else:
                rows = PARSERS[detect_format(storage.filename, data)](data)
        except FileFormatError as exc:
            errors.append(str(exc))
        else:
            if not rows:
                errors.append(_("Ce fichier ne contient aucun trajet."))
            elif len(rows) > current_app.config["MAX_IMPORT_ROWS"]:
                errors.append(_("Trop de trajets dans ce fichier (%(max)s au maximum).",
                                max=current_app.config["MAX_IMPORT_ROWS"]))
    if errors:
        return _render_index(form, errors)

    cancelled = [raw for _line, raw in rows if raw.get("_cancelled")]  # vols annulés : montrés, jamais importés
    records = []
    for line, raw in rows:
        if raw.get("_cancelled"):
            continue
        record, problems = validate_record(raw)
        errors.extend(_("Ligne %(line)s : %(error)s", line=line, error=problem) for problem in problems)
        records.append(record)
    if errors:
        # Rien n'est importé tant que le fichier contient des erreurs.
        return _render_index(form, errors[:MAX_REPORTED_ERRORS], hidden_errors=max(0, len(errors) - MAX_REPORTED_ERRORS))
    if not records:
        return _render_index(form, [_("Ce fichier ne contient aucun trajet.")])
    if archive is not None:
        # Sauvegarde complète : restauration directe, photos comprises.
        _create(records, archive)
        return redirect(url_for("trips.list_view"))

    existing = _existing_keys()
    duplicates = [_record_key(r) in existing for r in records]
    token = _store_pending(records, storage.filename or "")
    years = sorted({r["depart_date"].year for r in records}, reverse=True)
    return render_template("transfer/preview.html", form=ConfirmImportForm(token=token), filename=storage.filename,
                           rows=list(enumerate(zip(records, duplicates))), years=years, cancelled=cancelled,
                           duplicate_total=sum(duplicates))


@bp.route("/import/confirm", methods=["POST"])
@login_required
def confirm_import():
    form = ConfirmImportForm()
    pending = _load_pending(form.token.data) if form.validate_on_submit() else None
    if pending is None:
        flash(_("Cet aperçu a expiré : importez le fichier à nouveau."), "warning")
        return redirect(url_for("transfer.index"))
    os.remove(_pending_path(form.token.data))
    records = pending["records"]
    selected = {int(i) for i in request.form.getlist("rows") if i.isdigit() and int(i) < len(records)}
    if not selected:
        flash(_("Aucun trajet sélectionné : rien n'a été importé."), "info")
        return redirect(url_for("transfer.index"))
    _create([r for i, r in enumerate(records) if i in selected])
    return redirect(url_for("trips.list_view"))


def new_trip(user, record):
    """Trajet d'une ligne validée (validate_record), pays et étiquettes compris ; à ajouter à la session."""
    trip = Trip(
        user_id=user.id,
        origin_name=record["origin_name"], origin_lat=record["origin_lat"], origin_lon=record["origin_lon"],
        origin_country=record["origin_country"],
        dest_name=record["dest_name"], dest_lat=record["dest_lat"], dest_lon=record["dest_lon"],
        dest_country=record["dest_country"],
        depart_date=record["depart_date"], transport_mode=record["transport_mode"],
        is_round_trip=record["return_date"] is not None, return_date=record["return_date"],
        notes=record["notes"],
        carrier=record["carrier"], service_number=record["service_number"], vehicle=record["vehicle"],
    )
    trip.fill_missing_countries()
    trip.tags = resolve(user, parse_tags(record["tags"])[:MAX_TAGS])
    return trip


def _create(records, archive=None):
    """Crée les trajets (sauf doublons), regroupe les voyages, restaure les photos d'une archive."""
    existing = _existing_keys()
    created, created_records, skipped, groups = [], [], 0, {}
    for record in records:
        key = _record_key(record)
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        trip = new_trip(current_user, record)
        db.session.add(trip)
        created.append(trip)
        created_records.append((trip, record))
        if record["journey_key"]:
            groups.setdefault(record["journey_key"], []).append((trip, record))

    journeys = 0
    for members in groups.values():
        if len(members) < 2:
            continue  # un voyage compte au moins deux trajets
        first = members[0][1]
        journey = Journey(user_id=current_user.id, name=first["journey_name"], notes=first["journey_notes"])
        db.session.add(journey)
        for trip, _record in members:
            trip.journey = journey
        journeys += 1
    db.session.flush()

    photos_added = photos_failed = 0
    if archive is not None:
        for trip, record in created_records:
            for entries, owner in ((record["photos"], {"trip": trip}),
                                   (record["journey_photos"], {"journey": trip.journey} if trip.journey else {"trip": trip})):
                added, failed = _attach_photos(archive, entries, **owner)
                photos_added += added
                photos_failed += failed
    db.session.commit()

    message = ngettext("%(num)s trajet importé.", "%(num)s trajets importés.", len(created))
    if journeys:
        message += " " + ngettext("%(num)s voyage recréé.", "%(num)s voyages recréés.", journeys)
    if skipped:
        message += " " + ngettext("%(num)s doublon ignoré.", "%(num)s doublons ignorés.", skipped)
    if photos_added:
        message += " " + ngettext("%(num)s photo restaurée.", "%(num)s photos restaurées.", photos_added)
    if photos_failed:
        message += " " + ngettext("%(num)s photo illisible ignorée.", "%(num)s photos illisibles ignorées.", photos_failed)
    flash(message, "success" if created else "info")
