from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired, MultipleFileField
from wtforms import BooleanField, DateField, FloatField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, Regexp, ValidationError
from wtforms.widgets import HiddenInput

from ..transport import mode_choices

NOTES_MAX = 5000


def _notes_field():
    return TextAreaField(_l("Notes"), validators=[
        Optional(), Length(max=NOTES_MAX, message=_l("Les notes sont limitées à %(max)d caractères.")),
    ])


def _validate_tags(form, field):
    from ..tags import MAX_LENGTH, MAX_TAGS, parse_tags

    names = parse_tags(field.data)
    if len(names) > MAX_TAGS:
        raise ValidationError(_l("%(max)d étiquettes au maximum.", max=MAX_TAGS))
    if any(len(name) > MAX_LENGTH for name in names):
        raise ValidationError(_l("Une étiquette ne peut pas dépasser %(max)d caractères.", max=MAX_LENGTH))


def _tags_field():
    return StringField(_l("Étiquettes"), validators=[Optional(), Length(max=500), _validate_tags])


def _country_field():
    return StringField(widget=HiddenInput(), validators=[Optional(), Regexp(r"^[A-Za-z]{2}$")])


class TripForm(FlaskForm):
    origin_name = StringField(_l("Origine"), validators=[
        DataRequired(message=_l("L'origine est obligatoire.")),
        Length(max=255, message=_l("Ce nom de lieu est trop long.")),
    ])
    origin_lat = FloatField(widget=HiddenInput(), validators=[Optional(), NumberRange(-90, 90)])
    origin_lon = FloatField(widget=HiddenInput(), validators=[Optional(), NumberRange(-180, 180)])
    dest_name = StringField(_l("Destination"), validators=[
        DataRequired(message=_l("La destination est obligatoire.")),
        Length(max=255, message=_l("Ce nom de lieu est trop long.")),
    ])
    dest_lat = FloatField(widget=HiddenInput(), validators=[Optional(), NumberRange(-90, 90)])
    dest_lon = FloatField(widget=HiddenInput(), validators=[Optional(), NumberRange(-180, 180)])
    origin_country = _country_field()
    dest_country = _country_field()
    depart_date = DateField(_l("Date de départ"), validators=[
        DataRequired(message=_l("La date de départ est obligatoire.")),
    ])
    transport_mode = SelectField(_l("Mode de transport"), choices=mode_choices(), validators=[
        DataRequired(message=_l("Choisissez un mode de transport.")),
    ])
    is_round_trip = BooleanField(_l("Aller-retour"))
    return_date = DateField(_l("Date de retour"), validators=[Optional()])
    carrier = StringField(_l("Compagnie ou opérateur"), validators=[Optional(), Length(max=80)])
    service_number = StringField(_l("Numéro"), validators=[Optional(), Length(max=40)])
    # Aller-retour en avion : numéro du vol retour, enregistré avec l'aller (« AF1148 / AF1549 »).
    return_service_number = StringField(_l("Numéro du vol retour"), validators=[Optional(), Length(max=18)])
    vehicle = StringField(_l("Appareil"), validators=[Optional(), Length(max=80)])
    tags = _tags_field()
    notes = _notes_field()
    submit = SubmitField(_l("Enregistrer"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Les libellés paresseux sont résolus à chaque requête, dans la langue active.
        self.transport_mode.choices = mode_choices()

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators)
        if self.is_round_trip.data:
            if self.return_date.data is None:
                if not self.return_date.errors:
                    self.return_date.errors.append(_l("La date de retour est obligatoire pour un aller-retour."))
                valid = False
            elif self.depart_date.data and self.return_date.data < self.depart_date.data:
                self.return_date.errors.append(
                    _l("La date de retour doit être postérieure ou égale à la date de départ.")
                )
                valid = False
        back = (self.return_service_number.data or "").strip()
        if back and self.is_round_trip.data and self.transport_mode.data == "plane":
            outbound = (self.service_number.data or "").strip()
            if not outbound:
                self.return_service_number.errors.append(_l("Indiquez aussi le numéro du vol aller."))
                valid = False
            elif len(outbound) + len(back) + 3 > 40:
                self.return_service_number.errors.append(_l("Numéros de vol trop longs."))
                valid = False
        return valid


class JourneyForm(FlaskForm):
    name = StringField(_l("Nom du voyage"), validators=[
        Optional(),
        Length(max=120, message=_l("Ce nom est trop long.")),
    ])
    tags = _tags_field()
    notes = _notes_field()
    submit = SubmitField(_l("Enregistrer"))


class PhotoUploadForm(FlaskForm):
    photos = MultipleFileField(_l("Ajouter des photos"), validators=[
        FileRequired(message=_l("Choisissez au moins une photo.")),
        FileAllowed(["jpg", "jpeg", "png", "webp", "gif"],
                    message=_l("Format non pris en charge : utilisez JPEG, PNG, WebP ou GIF.")),
    ])
    submit = SubmitField(_l("Envoyer"))
