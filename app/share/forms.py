from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField, SubmitField
from wtforms.validators import Length, Optional

from ..utils import select_choices

# Durées de validité proposées, en jours ("" : jamais).
EXPIRY_CHOICES = [
    ("", _l("Jamais")),
    ("7", _l("Dans 7 jours")),
    ("30", _l("Dans 30 jours")),
    ("90", _l("Dans 3 mois")),
    ("365", _l("Dans 1 an")),
]


class ShareLinkForm(FlaskForm):
    label = StringField(_l("Libellé (facultatif)"), validators=[
        Optional(),
        Length(max=120, message=_l("Ce nom est trop long.")),
    ])
    expires_in = SelectField(_l("Expiration"), choices=select_choices(EXPIRY_CHOICES), default="")
    include_upcoming = BooleanField(_l("Montrer aussi les voyages à venir"), default=False)
    submit = SubmitField(_l("Générer un lien"))
