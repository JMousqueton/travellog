from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, SubmitField


class SettingsForm(FlaskForm):
    registration_open = BooleanField(_l("Autoriser les inscriptions"))
    free_mode = BooleanField(_l("Toutes les fonctions gratuites"))
    submit = SubmitField(_l("Enregistrer"))
