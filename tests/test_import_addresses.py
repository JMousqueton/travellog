"""Adresses d'import supplémentaires : confirmées par lien magique, jamais utilisables pour se connecter ni
pour s'inscrire, et uniques (ni l'adresse d'un compte, ni celle d'un autre utilisateur)."""
import re
from email.message import EmailMessage

import pytest

from app import mail_import
from app.models import ImportAddress, User, signup_token

from .conftest import login, make_user


@pytest.fixture(autouse=True)
def import_enabled(app):
    app.config.update(IMPORT_ADDRESS="addto@voyage-voyage.app", MAIL_IMPORT_REQUIRE_DKIM=False)


def _outbox(app):
    return app.extensions.setdefault("mail_outbox", [])


def _link(app):
    return re.search(r"http://localhost(/auth/import-addresses/confirm/\S+)", _outbox(app)[-1].get_content()).group(1)


def _add(client, email):
    return client.post("/auth/import-addresses", data={"imp-email": email})


def _addresses(db):
    return db.session.execute(db.select(ImportAddress.email)).scalars().all()


def test_address_is_added_only_after_confirmation(app, auth_client, db, user):
    response = _add(auth_client, " Work@Example.org ")
    assert response.status_code == 302
    message = _outbox(app)[-1]
    assert message["To"] == "work@example.org" and "alice@example.com" in message.get_content()
    assert _addresses(db) == []  # rien avant la confirmation

    link = _link(app)
    page = auth_client.get(link)
    assert page.status_code == 200 and "work@example.org" in page.text
    assert _addresses(db) == []  # un simple GET (robot de messagerie) ne confirme rien
    assert auth_client.post(link).status_code == 302
    assert [a.email for a in user.import_addresses] == ["work@example.org"]
    assert "work@example.org" in auth_client.get("/auth/profile").text

    # Le lien resservi ne crée pas de doublon.
    auth_client.post(link)
    assert _addresses(db) == ["work@example.org"]


def test_confirmation_works_without_being_signed_in(app, auth_client, client, db, user):
    _add(auth_client, "work@example.org")
    link = _link(app)
    auth_client.post("/auth/logout")
    assert client.post(link).status_code == 302
    assert _addresses(db) == ["work@example.org"]


def test_expired_or_forged_link_is_refused(app, auth_client, db):
    app.config["IMPORT_ADDRESS_LINK_MAX_AGE"] = -1
    _add(auth_client, "work@example.org")
    auth_client.post(_link(app))
    assert auth_client.post("/auth/import-addresses/confirm/forged").status_code == 302
    assert _addresses(db) == []


def test_account_addresses_are_refused_without_revealing_them(app, auth_client, db, user):
    make_user("bob@example.com")
    assert "déjà autorisée pour votre compte" in _add(auth_client, "ALICE@example.com").text
    response = _add(auth_client, "bob@example.com")
    assert response.status_code == 400 and "Cette adresse ne peut pas être ajoutée." in response.text
    assert all(m["To"] != "bob@example.com" for m in _outbox(app))


def test_another_users_import_address_is_refused(app, auth_client, client, db, user):
    bob = make_user("bob@example.com")
    db.session.add(ImportAddress(user_id=bob.id, email="shared@example.org"))
    db.session.commit()
    response = _add(auth_client, "shared@example.org")
    assert response.status_code == 400 and "Cette adresse ne peut pas être ajoutée." in response.text


def test_requesting_an_address_does_not_reserve_it(app, client, db):
    """Demander une adresse ne la bloque pas : le premier à confirmer l'obtient, l'autre lien est refusé."""
    make_user()
    make_user("bob@example.com")
    login(client)
    _add(client, "work@example.org")
    alice_link = _link(app)
    client.post("/auth/logout")
    login(client, "bob@example.com")
    _add(client, "work@example.org")
    bob_link = _link(app)
    client.post(bob_link)
    client.post(alice_link)
    owner = db.session.execute(db.select(ImportAddress)).scalar_one()
    assert owner.user.email == "bob@example.com"


def test_address_becoming_an_account_before_confirmation_is_refused(app, auth_client, db):
    _add(auth_client, "work@example.org")
    link = _link(app)
    make_user("work@example.org")
    auth_client.post(link)
    assert _addresses(db) == []


def test_limit_and_removal(app, auth_client, client, db, user):
    app.config["MAX_IMPORT_ADDRESSES"] = 1
    db.session.add(ImportAddress(user_id=user.id, email="one@example.org"))
    db.session.commit()
    assert "nombre maximal" in _add(auth_client, "two@example.org").text
    address = db.session.execute(db.select(ImportAddress)).scalar_one()

    bob = make_user("bob@example.com")  # personne d'autre ne peut la retirer
    other = app.test_client()
    login(other, "bob@example.com")
    assert other.post(f"/auth/import-addresses/{address.id}/delete").status_code == 404
    assert auth_client.post(f"/auth/import-addresses/{address.id}/delete").status_code == 302
    assert _addresses(db) == [] and bob.import_addresses == []


def test_import_address_cannot_sign_in_or_reset_password(app, client, db, user):
    db.session.add(ImportAddress(user_id=user.id, email="work@example.org"))
    db.session.commit()
    assert login(client, "work@example.org", "password123").status_code != 302
    client.post("/auth/forgot", data={"email": "work@example.org"})
    assert all(m["To"] != "work@example.org" for m in _outbox(app))


def test_import_address_cannot_sign_up(app, client, db, user):
    db.session.add(ImportAddress(user_id=user.id, email="work@example.org"))
    db.session.commit()
    client.post("/auth/register", data={"email": "Work@example.org"})
    message = _outbox(app)[-1]
    assert message["To"] == "work@example.org" and "/auth/signup/" not in message.get_content()
    # Lien d'inscription obtenu avant que l'adresse devienne une adresse d'import : refusé aussi.
    response = client.post(f"/auth/signup/{signup_token('work@example.org', 'fr')}",
                           data={"password": "longpassword", "confirm": "longpassword"})
    assert response.status_code == 302
    assert db.session.execute(db.select(User).filter_by(email="work@example.org")).first() is None


def test_direct_signup_refuses_import_address(app, client, db, user):
    db.session.add(ImportAddress(user_id=user.id, email="work@example.org"))
    db.session.commit()
    app.config["TESTING"] = False  # sans serveur d'e-mail : inscription directe avec mot de passe
    try:
        response = client.post("/auth/register", data={"email": "work@example.org", "password": "longpassword",
                                                       "confirm": "longpassword"})
    finally:
        app.config["TESTING"] = True
    assert "ne peut pas servir à s'inscrire" in response.text
    assert db.session.execute(db.select(User).filter_by(email="work@example.org")).first() is None


def test_mail_from_import_address_goes_to_its_owner(app, db, user):
    db.session.add(ImportAddress(user_id=user.id, email="work@example.org"))
    db.session.commit()
    msg = EmailMessage()
    msg["From"], msg["Subject"], msg["Message-ID"] = "Work <WORK@example.org>", "Vol", "<w@x>"
    msg["Date"] = "Tue, 27 Oct 2026 10:00:00 +0000"
    msg.set_content("Vol AF1148\nParis (CDG)\nBarcelone (BCN)\n12 mars 2026")
    assert mail_import.process(msg.as_bytes()).status == "imported"
    assert user.trips.count() == 1


def test_deleting_the_account_removes_its_addresses(app, db, user):
    db.session.add(ImportAddress(user_id=user.id, email="work@example.org"))
    db.session.commit()
    db.session.delete(user)
    db.session.commit()
    assert _addresses(db) == []
