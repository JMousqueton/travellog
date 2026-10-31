from datetime import timedelta

from flask import abort, flash, redirect, render_template, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from .. import utils
from ..extensions import db
from ..i18n import current_locale
from ..models import ShareLink, utcnow
from ..trips.routes import map_tiles, render_review, review_png_response
from . import bp
from .forms import ShareLinkForm


@bp.route("/share", methods=["GET", "POST"])
@login_required
def links():
    form = ShareLinkForm()
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
    return render_template("share/links.html", form=form, links=current_user.share_links)


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
    if user is None or user.is_blocked:
        abort(404)
    trips = happened(user.trips.all())
    badges = [row for row in compute_badges(trips) if row["earned"]]
    return render_template(
        "share/profile.html", profile=user, totals=compute_stats(trips), years_chart=_years_chart(trips),
        continents=continent_summary(trips, current_locale()),
        badges=sorted(badges, key=lambda row: row["earned"], reverse=True),
        since=min((t.depart_date.year for t in trips), default=None),
    )


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
