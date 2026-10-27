from app.models import Ticket, TicketMessage, User

from .conftest import login, make_user


def _outbox(app):
    return app.extensions.setdefault("mail_outbox", [])


def _admin(db, email="root@example.com", locale="fr"):
    admin = make_user(email, locale=locale)
    admin.is_admin = True
    db.session.commit()
    return admin


def _open_ticket(client, subject="Import Flighty", body="Le fichier n'est pas reconnu."):
    return client.post("/support", data={"subject": subject, "body": body, "notify": "y"})


def test_support_requires_login(client):
    response = client.get("/support")
    assert response.status_code == 302 and "/auth/login" in response.location


def test_support_link_in_account_menu(auth_client):
    assert 'href="/support"' in auth_client.get("/trips").text


def test_user_opens_ticket_and_admins_are_emailed(app, db, auth_client, user):
    _admin(db, "root@example.com", locale="en")
    response = auth_client.post("/support", data={"subject": "Import Flighty", "body": "Le fichier n'est pas reconnu.", "notify": "y"})
    ticket = db.session.execute(db.select(Ticket)).scalar_one()
    assert response.status_code == 302 and response.location.endswith(f"/support/{ticket.id}")
    assert ticket.status == "open" and ticket.user_id == user.id and len(ticket.messages) == 1
    page = auth_client.get(f"/support/{ticket.id}").text
    assert "Import Flighty" in page and "Le fichier n&#39;est pas reconnu." in page
    [mail] = _outbox(app)
    assert mail["To"] == "root@example.com"
    assert mail["Subject"] == f"[Support] Ticket #{ticket.id}: Import Flighty"  # langue de l'administrateur
    body = mail.get_content()
    assert "alice@example.com" in body and f"/admin/tickets/{ticket.id}" in body


def test_ticket_requires_subject_and_message(db, auth_client):
    response = auth_client.post("/support", data={"subject": "", "body": ""})
    assert response.status_code == 200 and "Le sujet est obligatoire." in response.text
    assert db.session.scalar(db.select(db.func.count(Ticket.id))) == 0


def test_users_only_see_their_own_tickets(client, db, user, other_user):
    login(client)
    _open_ticket(client)
    ticket = db.session.execute(db.select(Ticket)).scalar_one()
    client.post("/auth/logout")
    login(client, "bob@example.com")
    assert client.get(f"/support/{ticket.id}").status_code == 404
    assert client.post(f"/support/{ticket.id}", data={"body": "intrus"}).status_code == 404
    assert client.post(f"/support/{ticket.id}/close").status_code == 404
    assert "Import Flighty" not in client.get("/support").text


def test_tickets_tab_is_admin_only(auth_client):
    assert auth_client.get("/admin/tickets").status_code == 403


def test_conversation_with_several_exchanges(app, client, db, user):
    admin = _admin(db)
    login(client)
    _open_ticket(client)
    ticket = db.session.execute(db.select(Ticket)).scalar_one()
    client.post("/auth/logout")

    # L'administrateur voit le ticket à traiter, avec un compteur dans l'onglet, et répond.
    login(client, admin.email)
    listing = client.get("/admin/tickets").text
    assert "Import Flighty" in listing and '>1<span class="visually-hidden"> ticket en attente</span>' in listing
    _outbox(app).clear()
    response = client.post(f"/admin/tickets/{ticket.id}", data={"body": "Quelle application l'a exporté ?"})
    assert response.status_code == 302
    db.session.refresh(ticket)
    assert ticket.status == "answered"
    [mail] = _outbox(app)
    assert mail["To"] == "alice@example.com" and mail["Subject"] == "Réponse du support : Import Flighty"
    assert "Quelle application l'a exporté ?" in mail.get_content() and f"/support/{ticket.id}" in mail.get_content()
    assert "Import Flighty" not in client.get("/admin/tickets").text  # plus à traiter
    assert "Import Flighty" in client.get("/admin/tickets?status=answered").text
    client.post("/auth/logout")

    # L'utilisateur relance : le ticket repasse « à traiter ».
    login(client)
    client.post(f"/support/{ticket.id}", data={"body": "Flighty, version 4."})
    db.session.refresh(ticket)
    assert ticket.status == "open"
    assert [(m.from_staff, m.body) for m in ticket.messages] == [
        (False, "Le fichier n'est pas reconnu."), (True, "Quelle application l'a exporté ?"), (False, "Flighty, version 4.")]
    page = client.get(f"/support/{ticket.id}").text
    assert page.index("Le fichier n&#39;est pas reconnu.") < page.index("Quelle application") < page.index("Flighty, version 4.")


def test_close_and_reopen(client, db, user):
    admin = _admin(db)
    login(client)
    _open_ticket(client)
    ticket = db.session.execute(db.select(Ticket)).scalar_one()
    client.post(f"/support/{ticket.id}/close")
    db.session.refresh(ticket)
    assert ticket.status == "closed"
    client.post(f"/support/{ticket.id}", data={"body": "Finalement, encore une question."})
    db.session.refresh(ticket)
    assert ticket.status == "open"  # répondre rouvre la demande
    client.post("/auth/logout")

    login(client, admin.email)
    client.post(f"/admin/tickets/{ticket.id}/status", data={"status": "closed"})
    db.session.refresh(ticket)
    assert ticket.status == "closed"
    assert "Import Flighty" in client.get("/admin/tickets?status=closed").text
    client.post(f"/admin/tickets/{ticket.id}/status", data={"status": "open"})
    db.session.refresh(ticket)
    assert ticket.status == "open"
    assert client.post(f"/admin/tickets/{ticket.id}/status", data={"status": "bogus"}).status_code == 400


def test_deleting_accounts_keeps_or_removes_tickets(client, db, user):
    admin = _admin(db)
    login(client)
    _open_ticket(client)
    ticket_id = db.session.execute(db.select(Ticket.id)).scalar_one()
    client.post("/auth/logout")
    login(client, admin.email)
    client.post(f"/admin/tickets/{ticket_id}", data={"body": "Réponse"})

    # Supprimer l'administrateur garde sa réponse (sans auteur) ; supprimer l'utilisateur supprime ses tickets.
    db.session.delete(db.session.get(User, admin.id))
    db.session.commit()
    staff = db.session.execute(db.select(TicketMessage).filter_by(from_staff=True)).scalar_one()
    assert staff.author_id is None
    db.session.delete(db.session.get(User, user.id))
    db.session.commit()
    assert db.session.scalar(db.select(db.func.count(Ticket.id))) == 0
    assert db.session.scalar(db.select(db.func.count(TicketMessage.id))) == 0


def test_user_can_turn_off_reply_emails_per_ticket(app, client, db, user):
    admin = _admin(db)
    login(client)
    client.post("/support", data={"subject": "Sans e-mail", "body": "Juste ici, merci."})  # case décochée
    client.post("/support", data={"subject": "Avec e-mail", "body": "Prévenez-moi.", "notify": "y"})
    quiet, loud = db.session.execute(db.select(Ticket).order_by(Ticket.id)).scalars().all()
    assert not quiet.notify and loud.notify
    client.post("/auth/logout")

    login(client, admin.email)
    assert "a désactivé les e-mails" in client.get(f"/admin/tickets/{quiet.id}").text
    _outbox(app).clear()
    client.post(f"/admin/tickets/{quiet.id}", data={"body": "Réponse 1"})
    client.post(f"/admin/tickets/{loud.id}", data={"body": "Réponse 2"})
    assert [m["Subject"] for m in _outbox(app)] == ["Réponse du support : Avec e-mail"]
    client.post("/auth/logout")

    # Réglable ensuite depuis la page du ticket.
    login(client)
    client.post(f"/support/{quiet.id}/notify", data={"notify": "1"})
    client.post(f"/support/{loud.id}/notify", data={"notify": "0"})
    db.session.refresh(quiet)
    db.session.refresh(loud)
    assert quiet.notify and not loud.notify
    assert "Ne plus recevoir les réponses par e-mail" in client.get(f"/support/{quiet.id}").text
    client.post("/auth/logout")


def test_notify_toggle_is_owner_only(client, db, user, other_user):
    login(client)
    _open_ticket(client)
    ticket = db.session.execute(db.select(Ticket)).scalar_one()
    client.post("/auth/logout")
    login(client, "bob@example.com")
    assert client.post(f"/support/{ticket.id}/notify", data={"notify": "0"}).status_code == 404


def test_admin_can_turn_off_ticket_emails(app, client, db, user):
    on = _admin(db, "on@example.com")
    off = _admin(db, "off@example.com")
    login(client, off.email)
    client.post("/admin/tickets/notifications", data={"enabled": "0"})
    db.session.refresh(off)
    assert not off.ticket_emails and "M'informer par e-mail</button>" in client.get("/admin/tickets").text
    client.post("/auth/logout")

    login(client)
    _outbox(app).clear()
    _open_ticket(client)
    assert [m["To"] for m in _outbox(app)] == [on.email]
