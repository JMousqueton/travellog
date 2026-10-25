from babel.dates import get_month_names
from flask import Response, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_babel import gettext as _
from flask_babel import ngettext
from flask_login import current_user, login_required

from ..extensions import db
from ..geo import GeocodingError, geocode
from ..i18n import current_locale
from .. import ics, review_image
from ..models import Journey, Photo, Trip, User
from ..photos import PhotoError, merge_notes, move_photos, photo_path, save_upload
from ..routing import update_route
from ..tags import parse_tags, prune_unused, resolve, tags_text
from ..transport import CO2_KG_PER_KM, DETOUR_FACTORS, PLANE_CO2_BANDS
from .. import utils
from ..utils import is_safe_redirect
from . import bp
from .forms import JourneyForm, PhotoUploadForm, TripForm
from .queries import list_trips
from .absences import absence_summary
from .badges import compute_badges, continent_summary
from .places import visited_places
from .stats import (compute_stats, country_summary, happened, review_years, tag_stats, upcoming_trips, year_review,
                    yearly_stats)

# Clés de tri d'une ligne de la liste : un trajet isolé ou un voyage (trié selon son premier trajet).
SORTS = {
    "date_desc": lambda u: (u.start_date, u.id),
    "date_asc": lambda u: (u.start_date, u.id),
    "distance": lambda u: u.total_distance_km,
    "origin": lambda u: u.origin_name.casefold(),
}


class ListRow:
    def __init__(self, trip=None, journey=None):
        self.trip, self.journey = trip, journey
        first = journey.legs[0] if journey else trip
        self.id = journey.id if journey else trip.id
        self.start_date = first.depart_date
        self.origin_name = first.origin_name
        self.total_distance_km = (journey or trip).total_distance_km


def list_rows(trips):
    rows, seen = [], set()
    for trip in trips:
        if trip.journey_id is None:
            rows.append(ListRow(trip=trip))
        elif trip.journey_id not in seen:
            seen.add(trip.journey_id)
            rows.append(ListRow(journey=trip.journey))
    return rows


def map_tiles():
    cfg = current_app.config
    return {
        "light": cfg["MAP_TILE_URL"],
        "dark": cfg["MAP_TILE_URL_DARK"] or None,
        "subdomains": cfg["MAP_TILE_SUBDOMAINS"],
        "attribution": cfg["MAP_TILE_ATTRIBUTION"],
        "maxZoom": cfg["MAP_TILE_MAX_ZOOM"],
    }


def get_own_trip_or_404(trip_id):
    """404 (et non 403) pour ne pas révéler l'existence des voyages d'autrui."""
    trip = db.session.get(Trip, trip_id)
    if trip is None or trip.user_id != current_user.id:
        abort(404)
    return trip


def get_own_journey_or_404(journey_id):
    journey = db.session.get(Journey, journey_id)
    if journey is None or journey.user_id != current_user.id:
        abort(404)
    return journey


def _dissolve(journey, legs):
    """Supprime un voyage ; ses notes et photos passent à son premier trajet restant."""
    if legs:
        first = legs[0]
        first.notes = merge_notes(first.notes, journey.notes)
        move_photos(journey, first)
    for leg in legs:
        leg.journey = None
    db.session.delete(journey)


def _dissolve_if_too_small(journey):
    """Un voyage n'a de sens qu'avec au moins deux trajets."""
    remaining = [leg for leg in journey.legs if leg not in db.session.deleted]
    if len(remaining) < 2:
        _dissolve(journey, remaining)


def resolve_place(form, prefix):
    """Complète latitude/longitude (et pays) si l'utilisateur n'a pas choisi de suggestion."""
    name_field = getattr(form, f"{prefix}_name")
    lat_field, lon_field = getattr(form, f"{prefix}_lat"), getattr(form, f"{prefix}_lon")
    country_field = getattr(form, f"{prefix}_country")
    if lat_field.data is not None and lon_field.data is not None:
        return True
    try:
        results = geocode(name_field.data, current_locale())
    except GeocodingError:
        name_field.errors.append(_("La recherche de lieux est momentanément indisponible."))
        return False
    if not results:
        name_field.errors.append(_("Lieu introuvable : choisissez une suggestion de la liste."))
        return False
    lat_field.data, lon_field.data = results[0]["lat"], results[0]["lon"]
    country_field.data = results[0].get("country_code")
    return True


def _save(form, trip):
    before = (trip.origin_lat, trip.origin_lon, trip.dest_lat, trip.dest_lon, trip.transport_mode)
    trip.origin_name = form.origin_name.data.strip()
    trip.origin_lat, trip.origin_lon = form.origin_lat.data, form.origin_lon.data
    trip.dest_name = form.dest_name.data.strip()
    trip.dest_lat, trip.dest_lon = form.dest_lat.data, form.dest_lon.data
    trip.depart_date = form.depart_date.data
    trip.transport_mode = form.transport_mode.data
    trip.is_round_trip = bool(form.is_round_trip.data)
    trip.return_date = form.return_date.data if trip.is_round_trip else None
    trip.origin_country = (form.origin_country.data or "").upper() or None
    trip.dest_country = (form.dest_country.data or "").upper() or None
    trip.fill_missing_countries()
    trip.notes = (form.notes.data or "").strip() or None
    if (trip.origin_lat, trip.origin_lon, trip.dest_lat, trip.dest_lon, trip.transport_mode) != before:
        update_route(trip)
    trip.tags = resolve(current_user, parse_tags(form.tags.data))


def _handle_form(form, trip):
    if form.validate_on_submit():
        places_ok = resolve_place(form, "origin") & resolve_place(form, "dest")
        if places_ok:
            _save(form, trip)
            return True
    return False


@bp.route("/")
def index():
    if not current_user.is_authenticated:
        return render_template("landing.html")
    return render_template("map.html", focus=request.args.get("focus", type=int), tiles=map_tiles(),
                           user_tags=current_user.tags)


@bp.route("/trips")
@login_required
def list_view():
    sort = request.args.get("sort", "date_desc")
    if sort not in SORTS:
        sort = "date_desc"
    query = " ".join(request.args.get("q", "").split())[:200]
    trips = list_trips(current_user, {"q": query})
    rows = sorted(list_rows(trips), key=SORTS[sort], reverse=sort == "date_desc")
    return render_template("trips/list.html", rows=rows, sort=sort, q=query, match_count=len(trips),
                           has_trips=bool(rows) or current_user.trips.first() is not None)


@bp.route("/trips/new", methods=["GET", "POST"])
@login_required
def create():
    form = TripForm()
    trip = Trip(user_id=current_user.id)
    if _handle_form(form, trip):
        db.session.add(trip)
        prune_unused(current_user)
        db.session.commit()
        flash(_("Voyage ajouté."), "success")
        return redirect(url_for("trips.index", focus=trip.id))
    return render_template("trips/form.html", form=form, trip=None)


@bp.route("/trips/<int:trip_id>/edit", methods=["GET", "POST"])
@login_required
def edit(trip_id):
    trip = get_own_trip_or_404(trip_id)
    form = TripForm(obj=trip)
    if request.method == "GET":
        form.tags.data = tags_text(trip.tags)
    if _handle_form(form, trip):
        prune_unused(current_user)
        db.session.commit()
        flash(_("Voyage modifié."), "success")
        return redirect(url_for("trips.index", focus=trip.id))
    return render_template("trips/form.html", form=form, trip=trip)


@bp.route("/trips/<int:trip_id>/delete", methods=["POST"])
@login_required
def delete(trip_id):
    trip = get_own_trip_or_404(trip_id)
    journey = trip.journey
    db.session.delete(trip)
    if journey is not None:
        _dissolve_if_too_small(journey)
    prune_unused(current_user)
    db.session.commit()
    flash(_("Voyage supprimé."), "success")
    target = request.form.get("next", "")
    return redirect(target if is_safe_redirect(target) else url_for("trips.index"))


@bp.route("/journeys", methods=["POST"])
@login_required
def group():
    """Regroupe les trajets cochés en un seul voyage (en fusionnant les voyages existants)."""
    ids = {int(value) for value in request.form.getlist("trip_ids") if value.isdigit()}
    trips = db.session.execute(
        db.select(Trip).filter(Trip.user_id == current_user.id, Trip.id.in_(ids))
    ).scalars().all() if ids else []
    if len(trips) < 2:
        flash(_("Sélectionnez au moins deux trajets à regrouper."), "warning")
        return redirect(url_for("trips.list_view"))
    existing = sorted({trip.journey for trip in trips if trip.journey}, key=lambda j: j.id)
    journey = existing[0] if existing else Journey(user_id=current_user.id)
    for other in existing[1:]:
        for leg in list(other.legs):
            leg.journey = journey
        journey.notes = merge_notes(journey.notes, other.notes)
        move_photos(other, journey)
        db.session.delete(other)
    for trip in trips:
        trip.journey = journey
    db.session.add(journey)
    db.session.commit()
    flash(_("Trajets regroupés en un voyage."), "success")
    return redirect(url_for("trips.list_view"))


def _journey_tags(journey):
    return sorted({tag for leg in journey.legs for tag in leg.tags}, key=lambda t: t.name.casefold())


@bp.route("/journeys/<int:journey_id>/edit", methods=["GET", "POST"])
@login_required
def edit_journey(journey_id):
    journey = get_own_journey_or_404(journey_id)
    form = JourneyForm(obj=journey)
    if request.method == "GET":
        form.tags.data = tags_text(_journey_tags(journey))
    if form.validate_on_submit():
        journey.name = (form.name.data or "").strip() or None
        journey.notes = (form.notes.data or "").strip() or None
        # Les étiquettes d'un voyage s'appliquent à chacun de ses trajets.
        tags = resolve(current_user, parse_tags(form.tags.data))
        for leg in journey.legs:
            leg.tags = list(tags)
        prune_unused(current_user)
        db.session.commit()
        flash(_("Voyage enregistré."), "success")
        return redirect(url_for("trips.journey_detail", journey_id=journey.id))
    return render_template("trips/journey.html", form=form, journey=journey)


@bp.route("/journeys/<int:journey_id>/ungroup", methods=["POST"])
@login_required
def ungroup(journey_id):
    journey = get_own_journey_or_404(journey_id)
    _dissolve(journey, list(journey.legs))
    db.session.commit()
    flash(_("Voyage dégroupé : ses trajets sont de nouveau indépendants."), "success")
    return redirect(url_for("trips.list_view"))


@bp.route("/trips/<int:trip_id>/detach", methods=["POST"])
@login_required
def detach(trip_id):
    trip = get_own_trip_or_404(trip_id)
    journey = trip.journey
    if journey is not None:
        trip.journey = None
        _dissolve_if_too_small(journey)
        db.session.commit()
        flash(_("Trajet retiré du voyage."), "success")
    return redirect(url_for("trips.list_view"))


# --- Fiches détaillées : notes et photos --------------------------------------------------

@bp.route("/trips/<int:trip_id>")
@login_required
def detail(trip_id):
    trip = get_own_trip_or_404(trip_id)
    return render_template("trips/detail.html", trip=trip, journey=None, photos=trip.photos,
                           upload_form=PhotoUploadForm(),
                           upload_url=url_for("trips.upload_trip_photos", trip_id=trip.id))


@bp.route("/journeys/<int:journey_id>")
@login_required
def journey_detail(journey_id):
    journey = get_own_journey_or_404(journey_id)
    return render_template("trips/detail.html", trip=None, journey=journey, photos=journey.photos,
                           upload_form=PhotoUploadForm(),
                           upload_url=url_for("trips.upload_journey_photos", journey_id=journey.id))


def _upload(trip=None, journey=None):
    back = url_for("trips.detail", trip_id=trip.id) if trip else url_for("trips.journey_detail", journey_id=journey.id)
    form = PhotoUploadForm()
    if not form.validate_on_submit():
        for error in form.photos.errors:
            flash(error, "danger")
        return redirect(back)
    saved, errors = 0, []
    for storage in form.photos.data:
        try:
            save_upload(storage, current_user, trip=trip, journey=journey)
            saved += 1
        except PhotoError as exc:
            errors.append(f"{storage.filename} : {exc}")
    db.session.commit()
    if saved:
        flash(ngettext("%(num)s photo ajoutée.", "%(num)s photos ajoutées.", saved), "success")
    for error in errors[:5]:
        flash(error, "danger")
    return redirect(back)


@bp.route("/trips/<int:trip_id>/photos", methods=["POST"])
@login_required
def upload_trip_photos(trip_id):
    return _upload(trip=get_own_trip_or_404(trip_id))


@bp.route("/journeys/<int:journey_id>/photos", methods=["POST"])
@login_required
def upload_journey_photos(journey_id):
    return _upload(journey=get_own_journey_or_404(journey_id))


def _own_photo_or_404(photo_id):
    photo = db.session.get(Photo, photo_id)
    if photo is None or photo.user_id != current_user.id:
        abort(404)
    return photo


@bp.route("/photos/<int:photo_id>", endpoint="photo_file")
@bp.route("/photos/<int:photo_id>/thumb", endpoint="photo_thumb", defaults={"thumb": True})
@login_required
def photo_file(photo_id, thumb=False):
    photo = _own_photo_or_404(photo_id)
    try:
        response = send_file(photo_path(photo, thumb=thumb), mimetype="image/jpeg", max_age=86400,
                             download_name=f"photo-{photo.id}.jpg", conditional=True)
    except FileNotFoundError:
        abort(404)
    response.cache_control.private = True
    response.cache_control.public = False
    return response


@bp.route("/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
def delete_photo(photo_id):
    photo = _own_photo_or_404(photo_id)
    back = (url_for("trips.detail", trip_id=photo.trip_id) if photo.trip_id
            else url_for("trips.journey_detail", journey_id=photo.journey_id))
    db.session.delete(photo)
    db.session.commit()
    flash(_("Photo supprimée."), "success")
    return redirect(back)


# --- Statistiques par année --------------------------------------------------------------

def _co2_factors_g():
    """Facteurs d'émission en g/km, pour la note explicative."""
    factors = {mode: round(kg * 1000) for mode, kg in CO2_KG_PER_KM.items()}
    factors["plane"] = [round(kg * 1000) for _limit, kg in PLANE_CO2_BANDS]
    return factors


@bp.route("/stats")
@login_required
def stats_view():
    everything = list_trips(current_user)
    # Les trajets à venir n'ont pas encore eu lieu : ils ne comptent ni dans les pays visités ni dans le CO₂.
    trips = happened(everything)
    return render_template("trips/stats.html", totals=compute_stats(trips), years=yearly_stats(trips),
                           countries=country_summary(trips), factors=_co2_factors_g(), detour=DETOUR_FACTORS,
                           upcoming=upcoming_trips(everything), tags=tag_stats(trips), current_year=utils.today().year,
                           away=absence_summary(current_user, everything),
                           badges=compute_badges(everything), continents=continent_summary(everything, current_locale()),
                           places=visited_places(everything, current_user),
                           missing_countries=sum(1 for t in trips if not t.origin_country or not t.dest_country))


# --- Agenda (.ics) -----------------------------------------------------------------------

def _ics_response(trips, filename, name):
    response = Response(ics.calendar(trips, name), mimetype="text/calendar")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.cache_control.private = True
    return response


@bp.route("/trips/<int:trip_id>.ics")
@login_required
def trip_ics(trip_id):
    trip = get_own_trip_or_404(trip_id)
    return _ics_response([trip], f"trajet-{trip.id}.ics", _("Carnet de voyages"))


@bp.route("/journeys/<int:journey_id>.ics")
@login_required
def journey_ics(journey_id):
    journey = get_own_journey_or_404(journey_id)
    return _ics_response(journey.legs, f"voyage-{journey.id}.ics", journey.display_name)


@bp.route("/calendar/<token>.ics")
def calendar_feed(token):
    """Abonnement : les applications d'agenda ne se connectent pas, d'où le jeton secret dans l'adresse."""
    user = db.session.execute(db.select(User).filter_by(calendar_token=token)).scalar_one_or_none() if token else None
    if user is None:
        abort(404)
    response = _ics_response(list_trips(user), "voyages.ics", _("Carnet de voyages"))
    response.headers["Content-Disposition"] = 'inline; filename="voyages.ics"'
    return response


# --- Bilan de l'année --------------------------------------------------------------------

def add_absences(review, user, trips):
    """Jours d'absence de l'année (si un domicile est défini) ajoutés au bilan."""
    summary = absence_summary(user, trips)
    row = summary["by_year"].get(review["year"]) if summary else None
    review["days_away"] = row["days"] if row else None
    review["nights_abroad"] = row["nights_abroad"] if row else None
    review["badges"] = [b for b in compute_badges(trips) if b["earned"] and b["earned"].year == review["year"]]
    year_trips = [t for t in trips if t.depart_date.year == review["year"]]
    review["places"] = len(visited_places(year_trips, user))


def render_review(user, year, shared=None):
    trips = list_trips(user)
    years = review_years(trips)
    review = year_review(trips, year) if year in years else None
    if review is None and years:
        abort(404)
    if review is not None:
        add_absences(review, user, trips)
    if shared:
        image_url = url_for("share.review_image", token=shared.token, year=year) if review else None
        year_url = lambda y: url_for("share.review", token=shared.token, year=y)  # noqa: E731
    else:
        image_url = url_for("trips.review_png", year=year) if review else None
        year_url = lambda y: url_for("trips.review", year=y)  # noqa: E731
    return render_template("trips/review.html", review=review, years=years, shared=shared,
                           image_url=image_url, year_url=year_url,
                           month_names=get_month_names("wide", locale=current_locale()),
                           month_letters=get_month_names("narrow", locale=current_locale()))


def review_png_response(user, year):
    trips = list_trips(user)
    review = year_review(trips, year)
    if review is None:
        abort(404)
    add_absences(review, user, trips)
    response = Response(review_image.render(review, _("Carnet de voyages")), mimetype="image/png")
    response.headers["Content-Disposition"] = f'inline; filename="bilan-{year}.png"'
    response.cache_control.private = True
    response.cache_control.max_age = 300
    return response


@bp.route("/review")
@login_required
def review_latest():
    years = review_years(list_trips(current_user))
    return redirect(url_for("trips.review", year=years[0])) if years else render_review(current_user, None)


@bp.route("/review/<int:year>")
@login_required
def review(year):
    return render_review(current_user, year)


@bp.route("/review/<int:year>.png")
@login_required
def review_png(year):
    return review_png_response(current_user, year)
