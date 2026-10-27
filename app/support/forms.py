from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length

SUBJECT_MAX = 200
BODY_MAX = 5000


def _body_field(label):
    return TextAreaField(label, validators=[
        DataRequired(message=_l("Le message est obligatoire.")),
        Length(max=BODY_MAX, message=_l("Le message est limité à %(max)d caractères.")),
    ])


class TicketForm(FlaskForm):
    subject = StringField(_l("Sujet"), validators=[
        DataRequired(message=_l("Le sujet est obligatoire.")),
        Length(max=SUBJECT_MAX, message=_l("Le sujet est limité à %(max)d caractères.")),
    ])
    body = _body_field(_l("Votre message"))
    notify = BooleanField(_l("M'informer par e-mail des réponses"), default=True)
    submit = SubmitField(_l("Envoyer la demande"))


class ReplyForm(FlaskForm):
    body = _body_field(_l("Réponse"))
    submit = SubmitField(_l("Envoyer"))
