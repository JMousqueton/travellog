"""Légende des photos et lien de partage d'un seul trajet ou voyage, avec ses photos (Premium)."""
from datetime import date, timedelta

import pytest

from app.models import Journey, Photo, TripShare, utcnow
from .conftest import login, make_trip, make_user
from .test_features import _image_bytes, _upload


@pytest.fixture
def billing(app):
    app.config.update(STRIPE_SECRET_KEY="sk_test_x", PREMIUM_PRICE_MONTHLY="2", PREMIUM_PRICE_YEARLY="12")
    return app


def _photos(db):
    return db.session.execute(db.select(Photo).order_by(Photo.id)).scalars().all()


def _trip_with_photos(client, user, db, **trip):
    trip = make_trip(user, notes="Code de la porte : 1234", **trip)
    _upload(client, f"/trips/{trip.id}/photos", (_image_bytes(), "IMG_1.jpg"), (_image_bytes(), "IMG_2.jpg"))
    photos = [p for p in _photos(db) if p.trip_id == trip.id]
    photos[0].exif = {"make": "PhoneMaker", "model": "X1", "lat": 45.76, "lon": 4.84}
    db.session.commit()
    return trip, photos


def _share(client, db, url, **data):
    client.post(url, data=data)
    return db.session.execute(db.select(TripShare).order_by(TripShare.id.desc())).scalars().first()


# Légende

def test_caption_replaces_trip_name(auth_client, user, db):
    trip, (photo, _other) = _trip_with_photos(auth_client, user, db)
    assert "<figcaption>Paris, France → Lyon, France" in auth_client.get(f"/photos/{photo.id}").text
    response = auth_client.post(f"/photos/{photo.id}/description", data={"description": "  Coucher   de soleil "})
    assert response.status_code == 302
    assert photo.description == "Coucher de soleil"
    html = auth_client.get(f"/photos/{photo.id}").text
    assert "<figcaption>Coucher de soleil" in html and 'value="Coucher de soleil"' in html
    assert 'alt="Coucher de soleil"' in auth_client.get(f"/trips/{trip.id}").text
    auth_client.post(f"/photos/{photo.id}/description", data={"description": ""})  # retour au nom du trajet
    assert photo.description is None


def test_caption_too_long_and_other_user(auth_client, user, app, db):
    _trip, (photo, _other) = _trip_with_photos(auth_client, user, db)
    auth_client.post(f"/photos/{photo.id}/description", data={"description": "x" * 201})
    assert photo.description is None
    make_user("bob@example.com")
    bob = app.test_client()
    login(bob, "bob@example.com")
    assert photo.description is None and bob.post(f"/photos/{photo.id}/description", data={"description": "pirate"}).status_code == 404


# Partage d'un voyage

def test_trip_share_shows_trip_and_photos_without_notes_or_exif(auth_client, user, db, app):
    trip, (photo, other) = _trip_with_photos(auth_client, user, db)
    photo.description = "La gare"
    db.session.commit()
    share = _share(auth_client, db, f"/share/trips/{trip.id}")
    assert share.trip_id == trip.id and not share.show_exif
    assert share.token in auth_client.get(f"/trips/{trip.id}").text
    visitor = app.test_client()
    html = visitor.get(f"/v/{share.token}").text
    assert "Paris, France → Lyon, France" in html and "Code de la porte" not in html
    assert f"/v/{share.token}/photos/{photo.id}/thumb.jpg" in html
    assert visitor.get(f"/v/{share.token}/photos/{photo.id}/thumb.jpg").mimetype == "image/jpeg"
    assert visitor.get(f"/v/{share.token}/photos/{photo.id}.jpg").mimetype == "image/jpeg"
    page = visitor.get(f"/v/{share.token}/photos/{photo.id}").text
    assert "<figcaption>La gare" in page and "photoMap" not in page and "PhoneMaker" not in page
    assert f"/v/{share.token}/photos/{other.id}" in page  # suivante
    assert 'action="/photos/' not in page  # pas de formulaire de légende
    assert visitor.get(f"/v/{share.token}", headers={}).headers.get("X-Robots-Tag") == "noindex"


def test_trip_share_exif_option(auth_client, user, db, app):
    trip, (photo, _other) = _trip_with_photos(auth_client, user, db)
    share = _share(auth_client, db, f"/share/trips/{trip.id}", show_exif="y")
    visitor = app.test_client()
    page = visitor.get(f"/v/{share.token}/photos/{photo.id}").text
    assert "PhoneMaker" in page and 'id="photoMap"' in page
    auth_client.post(f"/share/voyage/{share.id}/exif")
    assert not share.show_exif
    assert "PhoneMaker" not in visitor.get(f"/v/{share.token}/photos/{photo.id}").text


def test_trip_share_only_serves_its_own_photos(auth_client, user, db, app):
    trip, _photos_a = _trip_with_photos(auth_client, user, db)
    _other_trip, photos_b = _trip_with_photos(auth_client, user, db, dest_name="Nice, France")
    share = _share(auth_client, db, f"/share/trips/{trip.id}")
    visitor = app.test_client()
    stranger = photos_b[0].id
    for path in (f"/v/{share.token}/photos/{stranger}", f"/v/{share.token}/photos/{stranger}.jpg",
                 f"/v/{share.token}/photos/{stranger}/thumb.jpg", "/v/inconnu"):
        assert visitor.get(path).status_code == 404
    assert visitor.get(f"/photos/{stranger}").status_code == 302  # la page du propriétaire reste privée


def test_journey_share_includes_legs_photos(auth_client, user, db, app):
    a, (photo, _other) = _trip_with_photos(auth_client, user, db)
    b = make_trip(user, depart_date=date(2025, 5, 3), origin_name="Lyon, France", dest_name="Paris, France")
    journey = Journey(user_id=user.id, name="Week-end à Lyon")
    a.journey = b.journey = journey
    db.session.add(journey)
    db.session.commit()
    share = _share(auth_client, db, f"/share/journeys/{journey.id}")
    html = app.test_client().get(f"/v/{share.token}").text
    assert "Week-end à Lyon" in html and f"/photos/{photo.id}/thumb.jpg" in html and "Étapes" in html


def test_trip_share_revoke_expiry_and_deletion(auth_client, user, db, app):
    trip, _photos_ = _trip_with_photos(auth_client, user, db)
    visitor = app.test_client()
    share = _share(auth_client, db, f"/share/trips/{trip.id}", expires_in="7")
    assert share.expires_at is not None and visitor.get(f"/v/{share.token}").status_code == 200
    share.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert visitor.get(f"/v/{share.token}").status_code == 404
    assert "Expiré" in auth_client.get(f"/trips/{trip.id}").text
    token = share.token
    response = auth_client.post(f"/share/voyage/{share.id}/revoke", data={"back": "links"})
    assert response.location.endswith("/share") and visitor.get(f"/v/{token}").status_code == 404
    second_id = _share(auth_client, db, f"/share/trips/{trip.id}").id
    assert "Paris, France → Lyon, France" in auth_client.get("/share").text  # listé sur la page Partager
    auth_client.post(f"/trips/{trip.id}/delete")
    assert db.session.execute(db.select(TripShare).filter_by(id=second_id)).first() is None


def test_trip_share_is_premium(auth_client, user, db, app, billing):
    trip = make_trip(user)
    response = auth_client.post(f"/share/trips/{trip.id}")
    assert response.status_code == 302 and response.location.endswith("/billing/")
    assert db.session.execute(db.select(TripShare)).first() is None
    html = auth_client.get(f"/trips/{trip.id}").text
    assert "Le partage d'un voyage est réservé aux abonnés Premium." in html
    # Un lien créé pendant l'abonnement n'est plus servi sans Premium.
    db.session.add(TripShare(user_id=user.id, trip_id=trip.id))
    db.session.commit()
    share = db.session.execute(db.select(TripShare)).scalar_one()
    assert app.test_client().get(f"/v/{share.token}").status_code == 404


def test_cannot_share_or_manage_someone_elses_trip(auth_client, user, db):
    bob = make_user("bob@example.com")
    trip = make_trip(bob)
    assert auth_client.post(f"/share/trips/{trip.id}").status_code == 404
    share = TripShare(user_id=bob.id, trip_id=trip.id)
    db.session.add(share)
    db.session.commit()
    assert auth_client.post(f"/share/voyage/{share.id}/exif").status_code == 404
    assert auth_client.post(f"/share/voyage/{share.id}/revoke").status_code == 404


# Carte des photos d'un voyage partagé (seulement si le lien montre les EXIF et GPS)

def test_trip_share_photo_map_with_exif(auth_client, user, db, app):
    trip, (geotagged, plain) = _trip_with_photos(auth_client, user, db)
    geotagged.description = "Place Bellecour"
    db.session.commit()
    share = _share(auth_client, db, f"/share/trips/{trip.id}", show_exif="y")
    visitor = app.test_client()
    assert f'href="/v/{share.token}/map"' in visitor.get(f"/v/{share.token}").text
    html = visitor.get(f"/v/{share.token}/map").text
    assert 'id="photosMap"' in html and html.count('"thumb":') == 1  # seule la photo localisée
    assert f"/v/{share.token}/photos/{geotagged.id}/thumb.jpg" in html and "Place Bellecour" in html
    assert f'href="/v/{share.token}"' in html  # retour à la fiche partagée
    assert "/photos/" + str(geotagged.id) + '"' not in html.replace(f"/v/{share.token}/photos/", "")  # pas d'adresse privée


def test_trip_share_photo_map_hidden_without_exif_or_gps(auth_client, user, db, app):
    trip, (geotagged, plain) = _trip_with_photos(auth_client, user, db)
    share = _share(auth_client, db, f"/share/trips/{trip.id}")
    visitor = app.test_client()
    assert f"/v/{share.token}/map" not in visitor.get(f"/v/{share.token}").text
    assert visitor.get(f"/v/{share.token}/map").status_code == 404
    # EXIF et GPS montrés, mais aucune photo localisée : pas de carte non plus.
    share.show_exif = True
    geotagged.exif = {"make": "PhoneMaker"}
    db.session.commit()
    assert f"/v/{share.token}/map" not in visitor.get(f"/v/{share.token}").text
    assert visitor.get(f"/v/{share.token}/map").status_code == 404
