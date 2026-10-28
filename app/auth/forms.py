from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, FloatField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, Regexp, ValidationError
from wtforms.widgets import HiddenInput

from ..extensions import db
from ..i18n import LANGUAGES
from ..models import User, is_import_address
from ..utils import select_choices

PASSWORD_MIN = 8


class LoginForm(FlaskForm):
    email = EmailField(_l("Adresse e-mail"), validators=[
        DataRequired(message=_l("L'adresse e-mail est obligatoire.")),
        Email(message=_l("Adresse e-mail invalide.")),
    ])
    password = PasswordField(_l("Mot de passe"), validators=[
        DataRequired(message=_l("Le mot de passe est obligatoire.")),
    ])
    remember = BooleanField(_l("Rester connecté"))
    submit = SubmitField(_l("Se connecter"))


class RegisterForm(FlaskForm):
    email = EmailField(_l("Adresse e-mail"), validators=[
        DataRequired(message=_l("L'adresse e-mail est obligatoire.")),
        Email(message=_l("Adresse e-mail invalide.")),
        Length(max=255, message=_l("L'adresse e-mail est trop longue.")),
    ])
    password = PasswordField(_l("Mot de passe"), validators=[
        DataRequired(message=_l("Le mot de passe est obligatoire.")),
        Length(min=PASSWORD_MIN, max=128,
               message=_l("Le mot de passe doit contenir au moins %(min)d caractères.")),
    ])
    confirm = PasswordField(_l("Confirmer le mot de passe"), validators=[
        DataRequired(message=_l("Veuillez confirmer le mot de passe.")),
        EqualTo("password", message=_l("Les mots de passe ne correspondent pas.")),
    ])
    submit = SubmitField(_l("Créer mon compte"))

    def validate_email(self, field):
        exists = db.session.execute(
            db.select(User.id).filter_by(email=field.data.strip().lower())
        ).first()
        if exists:
            raise ValidationError(_l("Un compte existe déjà avec cette adresse e-mail."))
        if is_import_address(field.data):
            raise ValidationError(_l("Cette adresse sert à l'import par e-mail d'un compte : elle ne peut pas servir à "
                                     "s'inscrire."))


class ProfileForm(FlaskForm):
    locale = SelectField(_l("Langue"), choices=select_choices((code, lang["name"]) for code, lang in LANGUAGES.items()))
    theme = SelectField(_l("Thème"), choices=select_choices([
        ("", _l("Automatique (selon le système)")),
        ("light", _l("Clair")),
        ("dark", _l("Sombre")),
    ]))
    submit = SubmitField(_l("Enregistrer"))


def _new_password_fields():
    password = PasswordField(_l("Nouveau mot de passe"), validators=[
        DataRequired(message=_l("Le mot de passe est obligatoire.")),
        Length(min=PASSWORD_MIN, max=128,
               message=_l("Le mot de passe doit contenir au moins %(min)d caractères.")),
    ])
    confirm = PasswordField(_l("Confirmer le mot de passe"), validators=[
        DataRequired(message=_l("Veuillez confirmer le mot de passe.")),
        EqualTo("password", message=_l("Les mots de passe ne correspondent pas.")),
    ])
    return password, confirm


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(_l("Mot de passe actuel"), validators=[
        DataRequired(message=_l("Le mot de passe est obligatoire.")),
    ])
    password, confirm = _new_password_fields()
    submit = SubmitField(_l("Changer le mot de passe"))


class DeleteAccountForm(FlaskForm):
    delete_password = PasswordField(_l("Mot de passe"), validators=[
        DataRequired(message=_l("Le mot de passe est obligatoire.")),
    ])
    submit = SubmitField(_l("Supprimer mon compte"))


class ForgotPasswordForm(FlaskForm):
    email = EmailField(_l("Adresse e-mail"), validators=[
        DataRequired(message=_l("L'adresse e-mail est obligatoire.")),
        Email(message=_l("Adresse e-mail invalide.")),
    ])
    submit = SubmitField(_l("Envoyer le lien"))


class ResetPasswordForm(FlaskForm):
    password, confirm = _new_password_fields()
    submit = SubmitField(_l("Enregistrer le mot de passe"))


class HomeForm(FlaskForm):
    """Domicile, avec les mêmes champs cachés que les lieux d'un trajet (préfixe « home »)."""

    home_name = StringField(_l("Ville de domicile"), validators=[
        DataRequired(message=_l("Indiquez votre ville.")),
        Length(max=255, message=_l("Ce nom de lieu est trop long.")),
    ])
    home_lat = FloatField(widget=HiddenInput(), validators=[Optional(), NumberRange(-90, 90)])
    home_lon = FloatField(widget=HiddenInput(), validators=[Optional(), NumberRange(-180, 180)])
    home_country = StringField(widget=HiddenInput(), validators=[Optional(), Regexp(r"^[A-Za-z]{2}$")])
    submit = SubmitField(_l("Enregistrer le domicile"))


class SignupRequestForm(FlaskForm):
    """Première étape de l'inscription : l'adresse e-mail seule, qui recevra le lien magique."""

    email = EmailField(_l("Adresse e-mail"), validators=[
        DataRequired(message=_l("L'adresse e-mail est obligatoire.")),
        Email(message=_l("Adresse e-mail invalide.")),
        Length(max=255, message=_l("L'adresse e-mail est trop longue.")),
    ])
    submit = SubmitField(_l("Recevoir le lien d'inscription"))


class SignupCompleteForm(FlaskForm):
    """Seconde étape, depuis le lien : choix du mot de passe et création du compte."""

    password, confirm = _new_password_fields()
    submit = SubmitField(_l("Créer mon compte"))


class ImportAddressForm(FlaskForm):
    """Adresse supplémentaire autorisée à envoyer des confirmations à l'import par e-mail."""

    email = EmailField(_l("Adresse e-mail"), filters=[lambda value: value.strip() if value else value], validators=[
        DataRequired(message=_l("L'adresse e-mail est obligatoire.")),
        Email(message=_l("Adresse e-mail invalide.")),
        Length(max=255, message=_l("L'adresse e-mail est trop longue.")),
    ])
    submit = SubmitField(_l("Envoyer le lien de confirmation"))
