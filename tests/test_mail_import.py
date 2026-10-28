"""Import de voyages par e-mail (flask mail-import)."""
import base64
import json
import shutil
import subprocess
from datetime import date
from email.message import EmailMessage

import pytest

from app import mail_import
from app.models import MailImport, Ticket, Trip, User

from .conftest import make_user


@pytest.fixture(autouse=True)
def no_dkim(app):
    """La signature DKIM est vérifiée à part (test_dkim_*) : les autres tests ne l'exigent pas."""
    app.config["MAIL_IMPORT_REQUIRE_DKIM"] = False


def make_mail(text=None, html=None, sender="alice@example.com", subject="Votre réservation",
              message_id="<resa-1@airline.example>", day="Tue, 27 Oct 2026 10:00:00 +0000"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "addto@voyage-voyage.app"
    msg["Subject"] = subject
    msg["Date"] = day
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content(text or "Confirmation")
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def json_ld(*reservations):
    return f'<html><head><script type="application/ld+json">{json.dumps(list(reservations))}</script></head>' \
           f'<body>Merci pour votre réservation.</body></html>'


def flight(origin, dest, when, number="1148", airline="AF"):
    return {"@context": "http://schema.org", "@type": "FlightReservation", "reservationNumber": "XYZ123",
            "reservationFor": {"@type": "Flight", "flightNumber": number,
                               "airline": {"@type": "Airline", "iataCode": airline},
                               "departureAirport": {"@type": "Airport", "iataCode": origin},
                               "arrivalAirport": {"@type": "Airport", "iataCode": dest},
                               "departureTime": when}}


AIR_FRANCE_TEXT = """Bonjour,
Votre voyage est confirmé.

Aller
Vol AF1148
Paris (CDG) 10:05
Barcelone (BCN) 12:00
jeudi 12 mars 2026

Retour
Vol AF1549
Barcelone (BCN) 13:20
Paris (CDG) 15:15
dimanche 15 mars 2026
"""


def test_json_ld_flight_is_imported_and_mail_deleted(app, db, user):
    outcome = mail_import.process(make_mail(html=json_ld(flight("CDG", "BCN", "2026-03-12T10:05:00+01:00"))).as_bytes())
    assert outcome.status == "imported" and outcome.delete
    trip = user.trips.one()
    assert (trip.transport_mode, trip.depart_date, trip.service_number) == ("plane", date(2026, 3, 12), "AF1148")
    assert "(CDG)" in trip.origin_name and "(BCN)" in trip.dest_name
    assert (trip.origin_country, trip.dest_country) == ("FR", "ES")
    entry = db.session.execute(db.select(MailImport)).scalar_one()
    assert (entry.status, entry.trip_count, entry.user_id) == ("imported", 1, user.id)


def test_json_ld_train_with_coordinates(app, db, user):
    train = {"@context": "http://schema.org", "@type": "TrainReservation",
             "reservationFor": {"@type": "TrainTrip", "trainNumber": "6201", "provider": {"name": "SNCF"},
                                "departureStation": {"@type": "TrainStation", "name": "Paris Gare de Lyon",
                                                     "geo": {"latitude": 48.844, "longitude": 2.374}},
                                "arrivalStation": {"@type": "TrainStation", "name": "Lyon Part-Dieu",
                                                   "geo": {"latitude": 45.760, "longitude": 4.859}},
                                "departureTime": "2026-11-20T08:00:00+01:00"}}
    assert mail_import.process(make_mail(html=json_ld(train)).as_bytes()).status == "imported"
    trip = user.trips.one()
    assert (trip.transport_mode, trip.carrier, trip.service_number) == ("train", "SNCF", "6201")
    assert (trip.origin_country, trip.dest_country) == ("FR", "FR")


def test_text_round_trip_is_paired(app, db, user):
    assert mail_import.process(make_mail(text=AIR_FRANCE_TEXT).as_bytes()).status == "imported"
    trip = user.trips.one()
    assert (trip.depart_date, trip.return_date, trip.is_round_trip) == (date(2026, 3, 12), date(2026, 3, 15), True)
    assert trip.service_number == "AF1148 / AF1549" and trip.carrier == "Air France"


def test_html_text_and_forwarded_attachment(app, db, user):
    original = make_mail(html="<table><tr><td>Flight</td><td>LH 1035</td></tr>"
                              "<tr><td>FRA</td><td>&rarr;</td><td>LHR</td></tr><tr><td>Nov 5, 2026</td></tr></table>",
                         sender="noreply@lufthansa.example", message_id="<orig@lh.example>")
    forward = make_mail(text="Pour Voyage Voyage", message_id="<fwd@example.com>")
    forward.add_attachment(original)
    assert mail_import.process(forward.as_bytes()).status == "imported"
    trip = user.trips.one()
    assert (trip.depart_date, trip.service_number) == (date(2026, 11, 5), "LH1035")
    assert "(FRA)" in trip.origin_name and "(LHR)" in trip.dest_name


def test_sender_matching_ignores_case(app, db, user):
    raw = make_mail(html=json_ld(flight("CDG", "BCN", "2026-03-12")), sender="Alice <ALICE@Example.com>").as_bytes()
    assert mail_import.process(raw).status == "imported"


def test_duplicate_trip_counts_as_imported(app, db, user):
    raw = make_mail(html=json_ld(flight("CDG", "BCN", "2026-03-12"))).as_bytes()
    mail_import.process(raw)
    again = make_mail(html=json_ld(flight("CDG", "BCN", "2026-03-12")), message_id="<resa-2@airline.example>")
    outcome = mail_import.process(again.as_bytes())
    assert outcome.status == "imported" and outcome.delete
    assert user.trips.count() == 1


def test_unknown_sender_is_ignored_without_ticket(app, db, user):
    outcome = mail_import.process(make_mail(text=AIR_FRANCE_TEXT, sender="spam@example.org").as_bytes())
    assert outcome.status == "ignored" and not outcome.delete
    assert db.session.execute(db.select(Ticket)).first() is None
    assert Trip.query.count() == 0


def test_unrecognised_mail_opens_one_ticket_and_stays(app, db, user):
    admin = make_user("admin@example.com")
    admin.is_admin = True
    db.session.commit()
    raw = make_mail(text="Merci pour votre commande de chaussettes.", subject="Commande 42").as_bytes()

    outcome = mail_import.process(raw)
    assert outcome.status == "failed" and not outcome.delete
    ticket = db.session.execute(db.select(Ticket)).scalar_one()
    assert ticket.user.email == app.config["MAIL_IMPORT_ERROR_EMAIL"]
    assert ticket.subject == "Import Error : Commande 42" and ticket.status == "open" and not ticket.notify
    body = ticket.messages[0].body
    assert "alice@example.com" in body and "Message-ID: <resa-1@airline.example>" in body and "chaussettes" in body
    outbox = app.extensions["mail_outbox"]
    assert [m["To"] for m in outbox] == ["admin@example.com", "alice@example.com"]  # équipe, puis expéditeur
    reply = outbox[1]
    assert reply["Subject"] == "Import impossible : Commande 42" and reply["Auto-Submitted"] == "auto-replied"
    assert "ajoutera vos trajets à la main" in reply.get_content()

    # Relevé suivant : le même e-mail, toujours dans la boîte, n'ouvre pas de second ticket.
    again = mail_import.process(raw)
    assert again.status == "done" and not again.delete
    assert db.session.execute(db.select(Ticket)).scalars().all() == [ticket]
    assert len(outbox) == 2  # ni second ticket, ni second compte rendu


def test_import_error_account_cannot_sign_in(app, client, db):
    mail_import.import_error_account()
    db.session.commit()
    account = db.session.execute(db.select(User).filter_by(email=app.config["MAIL_IMPORT_ERROR_EMAIL"])).scalar_one()
    assert not account.check_password("!") and not account.check_password("")
    response = client.post("/auth/login", data={"email": account.email, "password": "!"})
    assert "/auth/login" in (response.headers.get("Location") or "/auth/login")


def test_mail_without_message_id_is_recognised_by_content(app, db, user):
    raw = make_mail(text="Rien ici", message_id=None).as_bytes()
    assert mail_import.process(raw).status == "failed"
    assert mail_import.process(raw).status == "done"
    assert db.session.execute(db.select(Ticket)).scalars().all().__len__() == 1


def test_dry_run_writes_nothing(app, db, user):
    outcome = mail_import.process(make_mail(text=AIR_FRANCE_TEXT).as_bytes(), dry_run=True)
    assert outcome.status == "imported" and len(outcome.records) == 1
    assert Trip.query.count() == 0 and db.session.execute(db.select(MailImport)).first() is None


def test_dkim_required_rejects_unsigned_mail(app, db, user):
    app.config["MAIL_IMPORT_REQUIRE_DKIM"] = True
    outcome = mail_import.process(make_mail(text=AIR_FRANCE_TEXT).as_bytes())
    assert outcome.status == "ignored" and "DKIM" in outcome.reason
    assert Trip.query.count() == 0 and db.session.execute(db.select(Ticket)).first() is None


@pytest.fixture
def dkim_key(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl absent")
    key = tmp_path / "dkim.pem"
    subprocess.run(["openssl", "genrsa", "-traditional", "-out", str(key), "2048"], check=True, capture_output=True)
    public = subprocess.run(["openssl", "rsa", "-in", str(key), "-pubout", "-outform", "DER"],
                            check=True, capture_output=True).stdout
    record = b"v=DKIM1; k=rsa; p=" + base64.b64encode(public)
    return key.read_bytes(), lambda name, timeout=5: record if name == b"sel._domainkey.example.com." else None


def _signed(private_key, sender="alice@example.com", body=AIR_FRANCE_TEXT):
    import dkim

    raw = make_mail(text=body, sender=sender).as_bytes()
    return dkim.sign(raw, b"sel", b"example.com", private_key, include_headers=[b"from", b"subject", b"date"]) + raw


def test_dkim_signature_of_sender_domain_is_accepted(app, dkim_key):
    private_key, dns = dkim_key
    assert mail_import.dkim_aligned(_signed(private_key), "example.com", dnsfunc=dns)
    assert mail_import.dkim_aligned(_signed(private_key, sender="a@mail.example.com"), "mail.example.com", dnsfunc=dns)


def test_dkim_signature_of_another_domain_or_tampered_is_refused(app, dkim_key):
    private_key, dns = dkim_key
    assert not mail_import.dkim_aligned(_signed(private_key, sender="alice@other.org"), "other.org", dnsfunc=dns)
    tampered = _signed(private_key).replace(b"AF1148", b"AF6666")
    assert not mail_import.dkim_aligned(tampered, "example.com", dnsfunc=dns)
    assert not mail_import.dkim_aligned(make_mail().as_bytes(), "example.com", dnsfunc=dns)


class FakeIMAP:
    """Boîte IMAP en mémoire : {uid: e-mail brut}."""

    def __init__(self, messages):
        self.messages, self.deleted, self.expunged, self.capabilities = dict(messages), set(), [], ("UIDPLUS",)

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        return "OK", [b"Logged in"]

    def select(self, folder, readonly=False):
        self.readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b" ".join(self.messages)]
        if command == "FETCH":
            raw = self.messages[args[0]]
            if "HEADER.FIELDS" in args[1]:
                raw = b"".join(line for line in raw.splitlines(keepends=True) if line.lower().startswith(b"message-id"))
            return "OK", [(b"1 (UID 1 BODY[] {%d}" % len(raw), raw), b")"]
        if command == "STORE":
            self.deleted.add(args[0])
            return "OK", []
        if command == "EXPUNGE":
            self.expunged.append(args[0])
            return "OK", []
        raise AssertionError(command)


def test_run_deletes_only_imported_mails(app, db, user, monkeypatch):
    app.config.update(IMAP_SERVER="imap.example.org", IMAP_USERNAME="addto@example.org", IMAP_PASSWORD="x")
    box = FakeIMAP({
        b"1": make_mail(text=AIR_FRANCE_TEXT, message_id="<ok@x>").as_bytes(),
        b"2": make_mail(text="Pas de vol ici", message_id="<ko@x>").as_bytes(),
        b"3": make_mail(text=AIR_FRANCE_TEXT, sender="stranger@example.org", message_id="<who@x>").as_bytes(),
    })
    monkeypatch.setattr(mail_import.mailbox.imaplib, "IMAP4_SSL", box)

    assert mail_import.run() == {"imported": 1, "failed": 1, "ignored": 1}
    assert box.deleted == {b"1"} and box.expunged == [b"1"]

    del box.messages[b"1"]  # supprimé par EXPUNGE
    box.deleted.clear()
    box.expunged.clear()
    assert mail_import.run() == {"done": 2}
    assert not box.deleted and db.session.execute(db.select(Ticket)).scalars().all().__len__() == 1


def test_dry_run_opens_mailbox_read_only(app, db, user, monkeypatch):
    app.config.update(IMAP_SERVER="imap.example.org")
    box = FakeIMAP({b"1": make_mail(text=AIR_FRANCE_TEXT).as_bytes()})
    monkeypatch.setattr(mail_import.mailbox.imaplib, "IMAP4_SSL", box)
    assert mail_import.run(dry_run=True) == {"imported": 1}
    assert box.readonly and not box.deleted and Trip.query.count() == 0


@pytest.mark.parametrize("text, expected", [
    ("12 mars 2026", date(2026, 3, 12)),
    ("Thu, March 12, 2026", date(2026, 3, 12)),
    ("12MAR26", date(2026, 3, 12)),
    ("Sonntag, 3. Mai 2026", date(2026, 5, 3)),
    ("2026-11-03T10:00", date(2026, 11, 3)),
    ("03/04/2026", date(2026, 4, 3)),           # jour d'abord par défaut
    ("04/23/2026 et 05/01/2026", date(2026, 4, 23)),  # usage américain reconnu
    ("12 March 10:30", date(2027, 3, 12)),     # sans année : la prochaine, « 10 » n'est pas une année
    ("le 2 novembre", date(2026, 11, 2)),
])
def test_find_dates(text, expected):
    assert mail_import.find_dates(text, date(2026, 10, 27))[0][1] == expected


def test_html_to_text_keeps_cells_on_their_own_line():
    assert mail_import.html_to_text("<style>p{}</style><table><tr><td>CDG</td><td>BCN&nbsp;</td></tr></table>") == "CDG\nBCN"


def test_import_page_shows_address_only_when_configured(app, auth_client):
    assert "Import par e-mail" not in auth_client.get("/import-export").text
    app.config["IMPORT_ADDRESS"] = "addto@voyage-voyage.app"
    page = auth_client.get("/import-export").text
    assert "addto@voyage-voyage.app" in page and "alice@example.com" in page


FORWARDED_SAME_DAY = """---------- Forwarded message ---------
From: Alice <alice@example.com>
Sent: Tuesday, October 27, 2026 9:05 PM
To: addto@voyage-voyage.app
Subject: FW: Your Nov 10 CDG–MUC flight is confirmed [XHY3J2]

Your trip to Munich
CDG – MUC
Booking reference XHY3J2

Outbound flight
AF1722
Tue, Nov 10
Paris (CDG) 07:15
Munich (MUC) 08:45

Return flight
AF1823
Tue, Nov 10
Munich (MUC) 19:05
Paris (CDG) 20:40
"""


def test_forwarded_summary_then_flights_gives_one_same_day_round_trip(app, db, user):
    """Régression : le résumé « CDG – MUC » en tête faisait lire les aéroports du vol précédent (retour à
    l'envers) et la date du transfert (« Sent: ») comme date de l'aller."""
    assert mail_import.process(make_mail(text=FORWARDED_SAME_DAY).as_bytes()).status == "imported"
    trip = user.trips.one()
    assert (trip.depart_date, trip.return_date) == (date(2026, 11, 10), date(2026, 11, 10))
    assert "(CDG)" in trip.origin_name and "(MUC)" in trip.dest_name
    assert trip.service_numbers == ("AF1722", "AF1823")


def test_trip_entered_by_hand_is_not_duplicated(app, db, user):
    """Le même aller-retour saisi à la main (autres noms de lieux) : rien n'est ajouté, l'e-mail est supprimé."""
    from .conftest import make_trip

    make_trip(user, origin_name="Charles de Gaulle International Airport, France", origin_lat=49.0097,
              origin_lon=2.5479, dest_name="Munich International Airport, Germany", dest_lat=48.3538,
              dest_lon=11.7861, transport_mode="plane", depart_date=date(2026, 11, 10), is_round_trip=True,
              return_date=date(2026, 11, 10), service_number="AF1722 / AF1823")
    outcome = mail_import.process(make_mail(text=FORWARDED_SAME_DAY).as_bytes())
    assert outcome.status == "imported" and outcome.delete
    assert user.trips.count() == 1
    assert db.session.execute(db.select(MailImport)).scalar_one().trip_count == 0


def test_return_leg_of_existing_round_trip_is_a_duplicate(app, db, user):
    from .conftest import make_trip

    make_trip(user, origin_name="Paris CDG", origin_lat=49.0097, origin_lon=2.5479, dest_name="Barcelone",
              dest_lat=41.2974, dest_lon=2.0833, transport_mode="plane", depart_date=date(2026, 3, 12),
              is_round_trip=True, return_date=date(2026, 3, 15))
    mail_import.process(make_mail(html=json_ld(flight("BCN", "CDG", "2026-03-15T13:20:00+01:00", "1549"))).as_bytes())
    assert user.trips.count() == 1


def test_forward_header_is_blanked_but_booking_dates_are_kept():
    text = "De : Alice <a@example.com>\nEnvoyé : mardi 27 octobre 2026\nObjet : Vol\n\nDate : 12 mars 2026\n"
    cleaned = mail_import.strip_forward_headers(text)
    assert len(cleaned) == len(text) and "27 octobre" not in cleaned and "Date : 12 mars 2026" in cleaned


def _replies(app, to="alice@example.com"):
    return [m for m in app.extensions.get("mail_outbox", []) if m["To"] == to]


def test_reply_lists_imported_trips_in_the_account_language(app, db, user):
    user.locale = "en"
    db.session.commit()
    mail_import.process(make_mail(text=AIR_FRANCE_TEXT, subject="Booking").as_bytes())
    [reply] = _replies(app)
    body = reply.get_content()
    assert reply["Subject"] == "Trips imported: Booking"
    assert "have been added to your account" in body and "CDG ⇄ BCN · AF1148 / AF1549 · Air France" in body
    assert "Mar 12, 2026 → Mar 15, 2026" in body and "/trips" in body


def test_reply_reports_duplicates(app, db, user):
    raw = make_mail(text=AIR_FRANCE_TEXT, subject="Résa").as_bytes()
    mail_import.process(raw)
    mail_import.process(make_mail(text=AIR_FRANCE_TEXT, subject="Résa", message_id="<again@x>").as_bytes())
    first, second = _replies(app)
    assert first["Subject"] == "Voyages importés : Résa"
    assert second["Subject"] == "Voyages déjà enregistrés : Résa"
    assert "rien n'a été ajouté une seconde fois" in second.get_content() and "CDG ⇄ BCN" in second.get_content()


def test_reply_with_new_and_duplicate_trips(app, db, user):
    from .conftest import make_trip

    make_trip(user, origin_name="CDG", origin_lat=49.0097, origin_lon=2.5479, dest_name="BCN", dest_lat=41.2974,
              dest_lon=2.0833, transport_mode="plane", depart_date=date(2026, 3, 12))
    page = json_ld(flight("CDG", "BCN", "2026-03-12"), flight("ORY", "NCE", "2026-05-02", "6202"))
    mail_import.process(make_mail(html=page).as_bytes())
    body = _replies(app)[0].get_content()
    assert "ont été ajoutés à votre compte" in body and "ORY → NCE" in body
    assert "n'ont pas été ajoutés une seconde fois" in body and "CDG → BCN" in body


def test_reply_goes_to_the_import_address_that_sent_it(app, db, user):
    from app.models import ImportAddress

    db.session.add(ImportAddress(user_id=user.id, email="work@example.org"))
    db.session.commit()
    mail_import.process(make_mail(text=AIR_FRANCE_TEXT, sender="work@example.org").as_bytes())
    assert len(_replies(app, "work@example.org")) == 1 and not _replies(app)


def test_ignored_senders_get_no_reply(app, db, user):
    mail_import.process(make_mail(text=AIR_FRANCE_TEXT, sender="stranger@example.org").as_bytes())
    app.config["MAIL_IMPORT_REQUIRE_DKIM"] = True
    mail_import.process(make_mail(text=AIR_FRANCE_TEXT, message_id="<unsigned@x>").as_bytes())
    assert app.extensions.get("mail_outbox", []) == []


def test_account_deletion_forgets_import_log_and_error_tickets(app, db, user, client):
    from .conftest import login

    mail_import.process(make_mail(text="rien à lire", message_id="<a@x>").as_bytes())  # échec : ticket
    mail_import.process(make_mail(html=json_ld(flight("CDG", "BCN", "2026-03-12T10:05:00+01:00")),
                                  message_id="<b@x>").as_bytes())
    assert db.session.execute(db.select(db.func.count(MailImport.id))).scalar() == 2
    assert db.session.execute(db.select(db.func.count(Ticket.id))).scalar() == 1
    login(client)
    client.post("/auth/delete", data={"del-delete_password": "password123"})
    assert db.session.execute(db.select(db.func.count(MailImport.id))).scalar() == 0
    assert db.session.execute(db.select(db.func.count(Ticket.id))).scalar() == 0


def test_maintenance_purges_old_import_log_but_keeps_failures(app, db, user):
    from datetime import timedelta

    from app.jobs import run_job
    from app.models import utcnow

    old = utcnow() - timedelta(days=app.config["MAIL_IMPORT_LOG_DAYS"] + 1)
    db.session.add_all([MailImport(message_key=k, status=s, created_at=old)
                        for k, s in (("1", "imported"), ("2", "ignored"), ("3", "failed"))]
                       + [MailImport(message_key="4", status="imported")])
    db.session.commit()
    assert "2 e-mail(s) d'import" in run_job("maintenance").summary
    assert sorted(db.session.execute(db.select(MailImport.message_key)).scalars()) == ["3", "4"]
