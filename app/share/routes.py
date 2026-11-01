from datetime import timedelta

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from .. import utils
from ..billing import premium_access, premium_required
from ..extensions import db
from ..i18n import current_locale
from ..models import Journey, Photo, ShareLink, Trip, TripShare, utcnow
from ..trips.routes import map_tiles, render_review, review_png_response
from . import bp
from .forms import ShareLinkForm, TripShareForm


@bp.route("/share", methods=["GET", "POST"])
@login_required
def links():
    form = ShareLinkForm()
    if form.is_submitted() and not premium_access():
        flash(_("Les liens de partage sont réservés aux abonnés Premium."), "info")
        return redirect(url_for("billing.index"))
    if form.validate_on_submit():
        days = int(form.expires_in.data) if form.expires_in.data else None
        db.session.add(ShareLink(
            user_id=current_user.id,
            label=(form.label.data or "").strip() or None,
            expires_at=utcnow() + timedelta(days=days) if days else None,
            include_upcoming=bool(form.include_upcoming.data),
            show_trips=bool(form.show_trips.data),
        ))
        db.session.commit()
        flash(_("Lien de partage créé. Toute personne qui le possède peut voir vos voyages."), "success")
        return redirect(url_for("share.links"))
    trip_shares = db.session.execute(db.select(TripShare).filter_by(user_id=current_user.id)
                                     .order_by(TripShare.created_at.desc())).scalars().all()
    return render_template("share/links.html", form=form, links=current_user.share_links, trip_shares=trip_shares)


@bp.route("/share/<int:link_id>/revoke", methods=["POST"])
@login_required
def revoke(link_id):
    link = db.session.get(ShareLink, link_id)
    if link is None or link.user_id != current_user.id:
        abort(404)
    db.session.delete(link)
    db.session.commit()
    flash(_("Lien révoqué : il ne donne plus accès à vos voyages."), "success")
    return redirect(url_for("share.links"))


@bp.route("/share/<int:link_id>/upcoming", methods=["POST"])
@login_required
def toggle_upcoming(link_id):
    link = db.session.get(ShareLink, link_id)
    if link is None or link.user_id != current_user.id:
        abort(404)
    link.include_upcoming = not link.include_upcoming
    db.session.commit()
    flash(_("Ce lien montre désormais vos voyages à venir.") if link.include_upcoming
          else _("Ce lien ne montre plus vos voyages à venir."), "success")
    return redirect(url_for("share.links"))


@bp.route("/share/<int:link_id>/trips", methods=["POST"])
@login_required
def toggle_trips(link_id):
    link = db.session.get(ShareLink, link_id)
    if link is None or link.user_id != current_user.id:
        abort(404)
    link.show_trips = not link.show_trips
    db.session.commit()
    flash(_("Ce lien montre désormais la liste de vos trajets.") if link.show_trips
          else _("Ce lien ne montre plus la liste de vos trajets."), "success")
    return redirect(url_for("share.links"))


@bp.route("/s/<token>")
def view(token):
    link = ShareLink.active(token)
    if link is None:
        abort(404)
    from ..trips.queries import shared_trips_for

    link.mark_used()
    return render_template(
        "map.html", tiles=map_tiles(), focus=None, shared=link,
        map_years=sorted({t.depart_date.year for t in shared_trips_for(link)}, reverse=True),
        trips_url=url_for("api.shared_trips", token=token), stats_url=url_for("api.shared_stats", token=token),
        countries_url=url_for("api.shared_countries", token=token),
        places_url=url_for("api.shared_places", token=token), current_year=utils.today().year,
    )


def _active_link_or_404(token):
    link = ShareLink.active(token)
    if link is None:
        abort(404)
    return link


@bp.route("/s/<token>/stats")
def stats(token):
    """Statistiques partagées : depuis le début, années et badges.

    Seuls les trajets visibles par le lien comptent (sans les voyages à venir, sauf si le lien les montre) ;
    ni notes, ni photos, ni domicile.
    """
    from ..trips.badges import compute_badges, continent_summary
    from ..trips.queries import shared_trips_for
    from ..trips.stats import compute_stats, happened, yearly_stats

    link = _active_link_or_404(token)
    link.mark_used()
    everything = shared_trips_for(link)
    trips = happened(everything)
    return render_template(
        "share/stats.html", shared=link, totals=compute_stats(trips), years=yearly_stats(trips),
        continents=continent_summary(everything, current_locale()), badges=compute_badges(everything),
        current_year=utils.today().year,
    )


@bp.route("/u/<name>")
def public_profile(name):
    """Profil public choisi dans les préférences : résumé des voyages passés (pays, distances par mode, badges).

    Ni trajets, ni dates de voyage, ni notes, ni photos, ni domicile, ni voyages à venir.
    """
    from ..models import User
    from ..trips.badges import compute_badges, continent_summary
    from ..trips.stats import compute_stats, happened

    user = db.session.execute(db.select(User).filter_by(public_name=name.lower())).scalar_one_or_none()
    if user is None or user.is_blocked or not user.has_premium_access:
        abort(404)
    trips = happened(user.trips.all())
    badges = [row for row in compute_badges(trips) if row["earned"]]
    return render_template(
        "share/profile.html", profile=user, totals=compute_stats(trips), years_chart=_years_chart(trips),
        continents=continent_summary(trips, current_locale()),
        badges=sorted(badges, key=lambda row: row["earned"], reverse=True),
        since=min((t.depart_date.year for t in trips), default=None),
    )


@bp.route("/u/<name>/badge.svg")
def public_badge(name):
    """Badge SVG du profil public (pays, distance, trajets), à intégrer sur un blog ou un profil GitHub."""
    from flask_babel import format_decimal, ngettext

    from ..models import User
    from ..trips.stats import compute_stats, happened

    user = db.session.execute(db.select(User).filter_by(public_name=name.lower())).scalar_one_or_none()
    if user is None or user.is_blocked or not user.has_premium_access:
        abort(404)
    totals = compute_stats(happened(user.trips.all()))
    km = format_decimal(round(totals["total_distance_km"]), format="#,##0")
    columns = [
        (84, totals["countries_fmt"], ngettext("pays", "pays", totals["countries"])),
        (168, f"{km} km", _("parcourus")),
        (310, totals["count_fmt"], ngettext("voyage", "voyages", totals["count"])),
    ]
    label = _("%(site)s : %(countries)s pays, %(km)s km, %(trips)s voyages", site=current_app.config["SITE_NAME"],
              countries=totals["countries_fmt"], km=km, trips=totals["count_fmt"])
    svg = render_template("share/badge.svg", site=current_app.config["SITE_NAME"], name=user.public_name,
                          columns=columns, label=label)
    response = current_app.response_class(svg, mimetype="image/svg+xml")
    response.cache_control.public = True
    response.cache_control.max_age = 3600
    # Intégré sur d'autres sites (<img>) : la ressource doit pouvoir être chargée depuis n'importe quelle origine.
    response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    return response


def _years_chart(trips):
    """Graphique empilé des trajets par année et par mode ; les années sans trajet comptent pour zéro."""
    from ..transport import TRANSPORT_MODES

    if not trips:
        return None
    first, last = min(t.depart_date.year for t in trips), max(t.depart_date.year for t in trips)
    years = list(range(first, last + 1))
    counts = {mode: [0] * len(years) for mode in TRANSPORT_MODES}
    for trip in trips:
        counts[trip.transport_mode][trip.depart_date.year - first] += 1
    return {"type": "stacked", "labels": years, "unit": None,
            "series": {mode: values for mode, values in counts.items() if any(values)}}


@bp.route("/s/<token>/trips")
def trips(token):
    """Liste des voyages d'un lien qui la montre : dates, lieux, mode et distance (ni notes, ni photos)."""
    from ..trips.queries import shared_trips_for

    link = _active_link_or_404(token)
    if not link.show_trips:
        abort(404)
    link.mark_used()
    return render_template("share/trips.html", shared=link, rows=_shared_rows(shared_trips_for(link)))


def _shared_rows(trips):
    """Lignes de la liste partagée, comme « Mes voyages » : trajets isolés et voyages avec leurs trajets.

    Un voyage n'y montre que ses trajets visibles par le lien (ses dates et sa distance aussi), sans ses notes.
    """
    rows, journeys = [], {}
    for trip in sorted(trips, key=lambda t: (t.depart_date, t.id)):
        if trip.journey_id is None:
            rows.append({"trip": trip, "start": trip.depart_date})
        elif trip.journey_id in journeys:
            journeys[trip.journey_id]["legs"].append(trip)
        else:
            journeys[trip.journey_id] = {"journey": trip.journey, "legs": [trip], "start": trip.depart_date}
            rows.append(journeys[trip.journey_id])
    for row in journeys.values():
        legs = row["legs"]
        row["end"] = max(leg.end_date for leg in legs)
        row["km"] = sum(leg.total_distance_km for leg in legs)
        row["status"] = utils.trip_status(row["start"], row["end"])
        row["name"] = row["journey"].name or f"{legs[0].origin_name} → {legs[-1].dest_name}"
    return sorted(rows, key=lambda r: r["start"], reverse=True)


@bp.route("/s/<token>/review")
def review_latest(token):
    from ..trips.queries import list_trips
    from ..trips.stats import open_review_years

    link = _active_link_or_404(token)
    years = open_review_years(list_trips(link.user))
    return redirect(url_for("share.review", token=token, year=years[0])) if years else render_review(link.user, None, shared=link)


@bp.route("/s/<token>/review/<int:year>")
def review(token, year):
    link = _active_link_or_404(token)
    link.mark_used()
    return render_review(link.user, year, shared=link)


@bp.route("/s/<token>/review/<int:year>.png")
def review_image(token, year):
    return review_png_response(_active_link_or_404(token).user, year, shared=True)


# --- Lien vers un seul trajet ou voyage, avec ses photos ------------------------------------------------------

def _target_url(share):
    return (url_for("trips.detail", trip_id=share.trip_id) if share.trip_id
            else url_for("trips.journey_detail", journey_id=share.journey_id))


def _back_to(share):
    """Retour vers la page d'où vient la demande (fiche du voyage ou page Partager)."""
    return redirect(url_for("share.links") if request.form.get("back") == "links" else _target_url(share))


def _create_trip_share(trip=None, journey=None):
    target = trip or journey
    if target is None or target.user_id != current_user.id:
        abort(404)
    form = TripShareForm()
    if form.validate_on_submit():
        days = int(form.expires_in.data) if form.expires_in.data else None
        db.session.add(TripShare(user_id=current_user.id, trip=trip, journey=journey,
                                 show_exif=bool(form.show_exif.data),
                                 expires_at=utcnow() + timedelta(days=days) if days else None))
        db.session.commit()
        flash(_("Lien créé : toute personne qui le possède peut voir ce voyage et ses photos."), "success")
    return redirect(url_for("trips.detail", trip_id=trip.id) if trip
                    else url_for("trips.journey_detail", journey_id=journey.id))


@bp.route("/share/trips/<int:trip_id>", methods=["POST"])
@premium_required
def create_trip_share(trip_id):
    return _create_trip_share(trip=db.session.get(Trip, trip_id))


@bp.route("/share/journeys/<int:journey_id>", methods=["POST"])
@premium_required
def create_journey_share(journey_id):
    return _create_trip_share(journey=db.session.get(Journey, journey_id))


def _own_trip_share_or_404(share_id):
    share = db.session.get(TripShare, share_id)
    if share is None or share.user_id != current_user.id:
        abort(404)
    return share


@bp.route("/share/voyage/<int:share_id>/exif", methods=["POST"])
@login_required
def toggle_trip_share_exif(share_id):
    share = _own_trip_share_or_404(share_id)
    share.show_exif = not share.show_exif
    db.session.commit()
    flash(_("Ce lien montre désormais les informations EXIF et GPS des photos.") if share.show_exif
          else _("Ce lien ne montre plus les informations EXIF et GPS des photos."), "success")
    return _back_to(share)


@bp.route("/share/voyage/<int:share_id>/revoke", methods=["POST"])
@login_required
def revoke_trip_share(share_id):
    share = _own_trip_share_or_404(share_id)
    response = _back_to(share)
    db.session.delete(share)
    db.session.commit()
    flash(_("Lien révoqué : il ne donne plus accès à ce voyage."), "success")
    return response


def _active_trip_share_or_404(token):
    share = TripShare.active(token)
    if share is None:
        abort(404)
    return share


def _shared_photo_or_404(share, photo_id):
    photo = next((p for p in share.photos if p.id == photo_id), None)
    if photo is None:
        abort(404)
    return photo


@bp.route("/v/<token>")
def trip_share(token):
    """Un trajet ou un voyage partagé : dates, lieux, modes, distance et photos (ni notes, ni domicile)."""
    share = _active_trip_share_or_404(token)
    share.mark_used()
    return render_template("share/trip.html", share=share, trip=share.trip, journey=share.journey,
                           photos=sorted(share.photos, key=lambda p: p.id))


@bp.route("/v/<token>/photos/<int:photo_id>")
def trip_share_photo(token, photo_id):
    from ..trips.routes import photo_page_context

    share = _active_trip_share_or_404(token)
    photo = _shared_photo_or_404(share, photo_id)
    context = photo_page_context(photo, share.photos,
                                 lambda p: url_for("share.trip_share_photo", token=token, photo_id=p.id))
    target = share.target
    title = f"{target.origin_name} → {target.dest_name}" if share.trip else target.display_name
    return render_template(
        "trips/photo.html", back=url_for("share.trip_share", token=token), back_title=title,
        show_meta=share.show_exif, description_form=None, trip_share=share,
        image_url=url_for("share.trip_share_image", token=token, photo_id=photo.id), **context)


def _shared_photo_file(token, photo_id, thumb):
    from ..photos import photo_path

    share = _active_trip_share_or_404(token)
    photo = _shared_photo_or_404(share, photo_id)
    try:
        response = send_file(photo_path(photo, thumb=thumb), mimetype="image/jpeg", max_age=3600,
                             download_name=f"photo-{photo.id}.jpg", conditional=True)
    except FileNotFoundError:
        abort(404)
    response.cache_control.private = True
    response.cache_control.public = False
    return response


@bp.route("/v/<token>/photos/<int:photo_id>.jpg")
def trip_share_image(token, photo_id):
    return _shared_photo_file(token, photo_id, thumb=False)


@bp.route("/v/<token>/photos/<int:photo_id>/thumb.jpg")
def trip_share_thumb(token, photo_id):
    return _shared_photo_file(token, photo_id, thumb=True)
