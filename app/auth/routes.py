import secrets

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_babel import force_locale
from flask_babel import gettext as _
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db, limiter
from ..i18n import LANGUAGES, current_locale
from ..mail import mail_enabled, send_email
from ..models import (ImportAddress, User, import_address_token, is_import_address, read_import_address_token,
                      read_signup_token, registration_open, signup_token)
from ..utils import is_safe_redirect
from . import bp
from .forms import (ChangePasswordForm, DeleteAccountForm, ForgotPasswordForm, HomeForm, ImportAddressForm, LoginForm,
                    ProfileForm, PublicProfileForm, RegisterForm, ResetPasswordForm, SignupCompleteForm,
                    SignupRequestForm)


def _email_key():
    """Clé de limitation par adresse e-mail visée (en plus de la limite par adresse IP)."""
    return "email:" + (request.form.get("email") or "").strip().lower()


def _login_failed(response):
    # Une connexion réussie redirige : seuls les échecs sont décomptés.
    return response.status_code != 302


def _login_limit():
    return current_app.config["LOGIN_RATE_LIMIT"]


def _reset_limit():
    return current_app.config["PASSWORD_RESET_RATE_LIMIT"]


def _with_lang_cookie(response, locale):
    response.set_cookie(
        current_app.config["LANG_COOKIE_NAME"], locale,
        max_age=current_app.config["LANG_COOKIE_MAX_AGE"], samesite="Lax", secure=request.is_secure,
    )
    return response


def _external_url(endpoint, **values):
    """Lien absolu pour un e-mail ; APP_BASE_URL évite de faire confiance à l'en-tête Host de la requête."""
    base = current_app.config["APP_BASE_URL"]
    return base + url_for(endpoint, **values) if base else url_for(endpoint, _external=True, **values)


def _registration_closed():
    flash(_("Les inscriptions sont fermées. Contactez un administrateur pour obtenir un compte."), "info")
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["REGISTER_RATE_LIMIT"], methods=["POST"])
@limiter.limit(lambda: current_app.config["REGISTER_RATE_LIMIT"], methods=["POST"], key_func=_email_key)
def register():
    if current_user.is_authenticated:
        return redirect(url_for("trips.index"))
    if not registration_open():
        return _registration_closed()
    if mail_enabled():
        return _register_with_magic_link()
    # Sans serveur d'e-mail : inscription directe avec mot de passe.
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(email=form.email.data.strip().lower(), locale=current_locale())
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(_("Bienvenue ! Votre compte a été créé."), "success")
        return redirect(url_for("trips.index"))
    return render_template("auth/register.html", form=form)


def _register_with_magic_link():
    """Envoie un lien d'inscription valable SIGNUP_LINK_MAX_AGE secondes. La réponse est la même que
    l'adresse ait déjà un compte ou non ; dans ce cas, l'e-mail invite simplement à se connecter."""
    form = SignupRequestForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        locale = current_locale()
        existing = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        with force_locale(existing.locale if existing else locale):
            if existing:
                body = render_template("auth/email/signup_existing.txt", login_url=_external_url("auth.login"),
                                       forgot_url=_external_url("auth.forgot_password"))
            elif is_import_address(email):  # adresse d'import d'un compte : pas d'inscription possible
                body = render_template("auth/email/signup_import_address.txt")
            else:
                body = render_template("auth/email/signup.txt",
                                       url=_external_url("auth.signup", token=signup_token(email, locale)),
                                       minutes=current_app.config["SIGNUP_LINK_MAX_AGE"] // 60)
            subject = _("Votre inscription à Voyage Voyage")
        send_email(email, subject, body)
        return render_template("auth/register_sent.html", email=email,
                               minutes=current_app.config["SIGNUP_LINK_MAX_AGE"] // 60)
    return render_template("auth/register.html", form=form, magic=True)


@bp.route("/signup/<token>", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["REGISTER_RATE_LIMIT"], methods=["POST"])
def signup(token):
    """Page ouverte par le lien magique. Le compte n'est créé qu'à l'envoi du formulaire (POST) : les
    robots des messageries qui « ouvrent » les liens pour les analyser ne peuvent pas l'utiliser à votre place."""
    if not registration_open():
        return _registration_closed()
    data = read_signup_token(token)
    if data is None:
        flash(_("Ce lien d'inscription est invalide ou a expiré (il est valable %(minutes)s minutes). Demandez-en un nouveau.",
                minutes=current_app.config["SIGNUP_LINK_MAX_AGE"] // 60), "danger")
        return redirect(url_for("auth.register"))
    email = data["email"]
    if db.session.execute(db.select(User.id).filter_by(email=email)).first():
        flash(_("Ce lien a déjà servi : le compte existe. Connectez-vous."), "info")
        return redirect(url_for("auth.login"))
    if is_import_address(email):  # devenue adresse d'import entre l'envoi du lien et son ouverture
        flash(_("Cette adresse sert à l'import par e-mail d'un compte : elle ne peut pas servir à s'inscrire."), "danger")
        return redirect(url_for("auth.register"))
    if current_user.is_authenticated:
        logout_user()
    form = SignupCompleteForm()
    if form.validate_on_submit():
        locale = data.get("locale") if data.get("locale") in LANGUAGES else current_locale()
        user = User(email=email, locale=locale)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(_("Bienvenue ! Votre compte a été créé."), "success")
        return _with_lang_cookie(redirect(url_for("trips.index")), locale)
    return render_template("auth/signup.html", form=form, email=email)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(_login_limit, methods=["POST"], deduct_when=_login_failed)
@limiter.limit(_login_limit, methods=["POST"], deduct_when=_login_failed, key_func=_email_key)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("trips.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.execute(
            db.select(User).filter_by(email=form.email.data.strip().lower())
        ).scalar_one_or_none()
        if user is None or not user.check_password(form.password.data):
            flash(_("Adresse e-mail ou mot de passe incorrect."), "danger")
        else:
            login_user(user, remember=form.remember.data)
            target = request.args.get("next", "")
            if not is_safe_redirect(target):
                target = url_for("trips.index")
            flash(_("Bon retour parmi nous !"), "success")
            # La langue du profil devient aussi celle du cookie (utile après déconnexion).
            return _with_lang_cookie(redirect(target), user.locale)
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash(_("Vous êtes déconnecté."), "info")
    return redirect(url_for("trips.index"))


def _render_profile(form=None, password_form=None, delete_form=None, home_form=None, import_form=None,
                    public_form=None):
    if form is None:
        form = ProfileForm(formdata=None, obj=current_user)
        form.theme.data = current_user.theme or ""
    return render_template(
        "auth/profile.html",
        form=form,
        home_form=home_form or HomeForm(formdata=None, obj=current_user),
        password_form=password_form or ChangePasswordForm(formdata=None, prefix="pw"),
        delete_form=delete_form or DeleteAccountForm(formdata=None, prefix="del"),
        import_form=import_form or ImportAddressForm(formdata=None, prefix="imp"),
        public_form=public_form or PublicProfileForm(formdata=None, prefix="pub", obj=current_user),
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "GET":
        return _render_profile()
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.locale = form.locale.data
        current_user.theme = form.theme.data or None
        db.session.commit()
        flash(_("Préférences enregistrées."), "success")
        return _with_lang_cookie(redirect(url_for("auth.profile")), current_user.locale)
    return _render_profile(form=form)


@bp.route("/home", methods=["POST"])
@login_required
def set_home():
    from ..countries import country_at
    from ..trips.routes import resolve_place

    form = HomeForm()
    if form.validate_on_submit() and resolve_place(form, "home"):
        current_user.home_name = form.home_name.data.strip()
        current_user.home_lat, current_user.home_lon = form.home_lat.data, form.home_lon.data
        current_user.home_country = ((form.home_country.data or "").upper()
                                     or country_at(form.home_lat.data, form.home_lon.data))
        db.session.commit()
        flash(_("Domicile enregistré : les jours d'absence sont calculés à partir de %(place)s.",
                place=current_user.home_name), "success")
        return redirect(url_for("auth.profile", _anchor="home"))
    return _render_profile(home_form=form), 400


@bp.route("/home/clear", methods=["POST"])
@login_required
def clear_home():
    current_user.home_name = current_user.home_lat = current_user.home_lon = current_user.home_country = None
    db.session.commit()
    flash(_("Domicile supprimé."), "success")
    return redirect(url_for("auth.profile", _anchor="home"))


@bp.route("/public-profile", methods=["POST"])
@login_required
def set_public_profile():
    """Choisit, change ou retire (nom vide) le nom du profil public /u/<nom>."""
    form = PublicProfileForm(prefix="pub", user=current_user)
    if form.validate_on_submit():
        current_user.public_name = form.public_name.data or None
        db.session.commit()
        if current_user.public_name:
            flash(_("Profil public activé : toute personne qui connaît son adresse voit le résumé de vos voyages."),
                  "success")
        else:
            flash(_("Profil public désactivé."), "success")
        return redirect(url_for("auth.profile", _anchor="public-profile"))
    return _render_profile(public_form=form), 400


@bp.route("/password", methods=["POST"])
@login_required
@limiter.limit(_login_limit, deduct_when=lambda response: response.status_code != 302)
def change_password():
    form = ChangePasswordForm(prefix="pw")
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            form.current_password.errors.append(_("Mot de passe actuel incorrect."))
        else:
            user = current_user._get_current_object()
            user.set_password(form.password.data)
            db.session.commit()
            # Les autres sessions sont invalidées ; celle-ci est renouvelée avec la nouvelle empreinte.
            remember = current_app.config.get("REMEMBER_COOKIE_NAME", "remember_token") in request.cookies
            login_user(user, remember=remember)
            flash(_("Mot de passe modifié. Vos autres sessions ont été déconnectées."), "success")
            return redirect(url_for("auth.profile"))
    return _render_profile(password_form=form), 400


@bp.route("/delete", methods=["POST"])
@login_required
@limiter.limit(_login_limit, deduct_when=lambda response: response.status_code != 302)
def delete_account():
    form = DeleteAccountForm(prefix="del")
    if form.validate_on_submit():
        user = current_user._get_current_object()
        if not user.check_password(form.delete_password.data):
            form.delete_password.errors.append(_("Mot de passe incorrect."))
        elif user.is_admin and db.session.scalar(
            db.select(db.func.count(User.id)).filter(User.is_admin.is_(True))
        ) <= 1:
            flash(_("Vous êtes le seul administrateur : désignez-en un autre avant de supprimer votre compte."),
                  "danger")
            return redirect(url_for("auth.profile"))
        else:
            logout_user()
            db.session.delete(user)
            db.session.commit()
            flash(_("Votre compte et tous vos voyages ont été supprimés."), "success")
            return redirect(url_for("trips.index"))
    return _render_profile(delete_form=form), 400


@bp.route("/calendar", methods=["POST"])
@login_required
def calendar_enable():
    """Active l'abonnement agenda, ou en change l'adresse (l'ancienne cesse de fonctionner)."""
    current_user.calendar_token = secrets.token_urlsafe(24)
    db.session.commit()
    flash(_("Nouvelle adresse d'abonnement créée. L'ancienne adresse ne fonctionne plus."), "success")
    return redirect(url_for("auth.profile", _anchor="calendar"))


@bp.route("/calendar/disable", methods=["POST"])
@login_required
def calendar_disable():
    current_user.calendar_token = None
    db.session.commit()
    flash(_("Abonnement agenda désactivé."), "success")
    return redirect(url_for("auth.profile", _anchor="calendar"))


# --- Adresses d'import supplémentaires ---------------------------------------------------------
# Une adresse n'est enregistrée qu'à la confirmation du lien envoyé à cette adresse : demander une adresse
# ne la réserve pas (personne ne peut bloquer l'adresse d'un autre).

def _import_address_limit():
    return current_app.config["REGISTER_RATE_LIMIT"]


@bp.route("/import-addresses", methods=["POST"])
@login_required
@limiter.limit(_import_address_limit)
def add_import_address():
    if not mail_enabled():
        abort(404)
    form = ImportAddressForm(prefix="imp")
    if not form.validate_on_submit():
        return _render_profile(import_form=form), 400
    email = form.email.data.strip().lower()
    mine = {a.email for a in current_user.import_addresses}
    if email == current_user.email.lower() or email in mine:
        form.email.errors.append(_("Cette adresse est déjà autorisée pour votre compte."))
    elif len(mine) >= current_app.config["MAX_IMPORT_ADDRESSES"]:
        form.email.errors.append(_("Vous avez atteint le nombre maximal d'adresses (%(max)s).",
                                   max=current_app.config["MAX_IMPORT_ADDRESSES"]))
    elif ImportAddress.taken(email):
        # Même message qu'il s'agisse d'un compte ou de l'adresse d'un autre : rien n'est révélé.
        form.email.errors.append(_("Cette adresse ne peut pas être ajoutée."))
    if form.email.errors:
        return _render_profile(import_form=form), 400
    minutes = current_app.config["IMPORT_ADDRESS_LINK_MAX_AGE"] // 60
    with force_locale(current_user.locale):
        body = render_template("auth/email/import_address.txt", account=current_user.email, minutes=minutes,
                               url=_external_url("auth.confirm_import_address",
                                                 token=import_address_token(current_user, email)))
        subject = _("Confirmez votre adresse d'import pour Voyage Voyage")
    send_email(email, subject, body)
    flash(_("Un lien de confirmation a été envoyé à %(email)s (valable %(minutes)s minutes).",
            email=email, minutes=minutes), "success")
    return redirect(url_for("auth.profile", _anchor="mail-import"))


@bp.route("/import-addresses/confirm/<token>", methods=["GET", "POST"])
@limiter.limit(_import_address_limit, methods=["POST"])
def confirm_import_address(token):
    """Page du lien de confirmation ; l'adresse n'est ajoutée qu'à l'envoi du formulaire (POST), pour que les
    robots des messageries qui ouvrent les liens ne la confirment pas. Pas besoin d'être connecté."""
    data = read_import_address_token(token)
    user = db.session.get(User, data["id"]) if data else None
    if user is None:
        flash(_("Ce lien de confirmation est invalide ou a expiré. Demandez-en un nouveau depuis vos préférences."),
              "danger")
        return redirect(url_for("auth.profile" if current_user.is_authenticated else "auth.login"))
    email = data["email"]
    if any(a.email == email for a in user.import_addresses):
        flash(_("Adresse %(email)s déjà confirmée.", email=email), "info")
        return redirect(url_for("auth.profile", _anchor="mail-import"))
    if request.method == "POST":
        if ImportAddress.taken(email):  # devenue entre-temps un compte ou l'adresse d'un autre
            flash(_("Cette adresse ne peut pas être ajoutée."), "danger")
        else:
            db.session.add(ImportAddress(user_id=user.id, email=email))
            db.session.commit()
            flash(_("Adresse %(email)s confirmée : ses confirmations de voyage peuvent être transférées à "
                    "l'adresse d'import.", email=email), "success")
        return redirect(url_for("auth.profile", _anchor="mail-import"))
    return render_template("auth/import_address_confirm.html", email=email, account=user.email)


@bp.route("/import-addresses/<int:address_id>/delete", methods=["POST"])
@login_required
def delete_import_address(address_id):
    address = db.session.get(ImportAddress, address_id)
    if address is None or address.user_id != current_user.id:
        abort(404)
    db.session.delete(address)
    db.session.commit()
    flash(_("Adresse %(email)s retirée.", email=address.email), "success")
    return redirect(url_for("auth.profile", _anchor="mail-import"))


def _reset_url(user):
    return _external_url("auth.reset_password", token=user.password_reset_token())


@bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit(_reset_limit, methods=["POST"])
@limiter.limit(_reset_limit, methods=["POST"], key_func=_email_key)
def forgot_password():
    if not mail_enabled():
        abort(404)
    if current_user.is_authenticated:
        return redirect(url_for("auth.profile"))
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = db.session.execute(
            db.select(User).filter_by(email=form.email.data.strip().lower())
        ).scalar_one_or_none()
        if user is not None:
            with force_locale(user.locale):
                body = render_template(
                    "auth/email/reset_password.txt", url=_reset_url(user),
                    minutes=current_app.config["PASSWORD_RESET_MAX_AGE"] // 60,
                )
                subject = _("Réinitialisation de votre mot de passe")
            send_email(user.email, subject, body)
        # Même message que le compte existe ou non, pour ne pas révéler les adresses inscrites.
        flash(_("Si un compte correspond à cette adresse, un e-mail contenant un lien de réinitialisation "
                "vient d'être envoyé."), "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=form)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = User.from_password_reset_token(token)
    if user is None:
        flash(_("Ce lien de réinitialisation est invalide ou a expiré. Demandez-en un nouveau."), "danger")
        return redirect(url_for("auth.forgot_password") if mail_enabled() else url_for("auth.login"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        if current_user.is_authenticated:
            logout_user()
        flash(_("Mot de passe modifié. Vous pouvez vous connecter."), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form)
