from datetime import timedelta

from flask import abort, flash, redirect, render_template, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from .. import utils
from ..extensions import db
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


@bp.route("/s/<token>")
def view(token):
    link = ShareLink.active(token)
    if link is None:
        abort(404)
    link.mark_used()
    return render_template(
        "map.html", tiles=map_tiles(), focus=None, shared=link,
        trips_url=url_for("api.shared_trips", token=token), stats_url=url_for("api.shared_stats", token=token),
        countries_url=url_for("api.shared_countries", token=token),
        places_url=url_for("api.shared_places", token=token), current_year=utils.today().year,
    )


def _active_link_or_404(token):
    link = ShareLink.active(token)
    if link is None:
        abort(404)
    return link


@bp.route("/s/<token>/review")
def review_latest(token):
    from ..trips.queries import list_trips
    from ..trips.stats import review_years

    link = _active_link_or_404(token)
    years = review_years(list_trips(link.user))
    return redirect(url_for("share.review", token=token, year=years[0])) if years else render_review(link.user, None, shared=link)


@bp.route("/s/<token>/review/<int:year>")
def review(token, year):
    link = _active_link_or_404(token)
    link.mark_used()
    return render_review(link.user, year, shared=link)


@bp.route("/s/<token>/review/<int:year>.png")
def review_image(token, year):
    return review_png_response(_active_link_or_404(token).user, year)
